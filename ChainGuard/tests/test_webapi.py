import os
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SEED_DEMO_PASSWORD", "test-runtime-password")

from src.api import app
from src.webapi.auth.security import AuthContext, create_tokens, hash_password
from src.webapi.database import SessionLocal
from src.webapi.models import Approval, DecisionDetail, ImportJob, Job, NotificationMessage, Incident, Proposal, Risk, Task, Tenant, User
from src.webapi import jobs
from src.webapi.notifications import FIXED_RULES, ensure_rules, notify_event
from src.webapi.routers.business import release_expired_countersigns, release_overdue_tasks
from src.webapi.proposal_mapper import map_decision_result
from src.webapi.seed import seed


seed()
client = TestClient(app)


def headers(role: str) -> dict[str, str]:
    with SessionLocal() as db:
        user = db.get(User, f"u-{role}")
        return {"Authorization": f"Bearer {create_tokens(user)['token']}"}


def test_authentication_and_error_envelope():
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert set(response.json()) == {"code", "message", "traceId"}
    assert response.headers["X-Trace-Id"] == response.json()["traceId"]


def test_refresh_token_is_http_only_cookie_and_rotates():
    with SessionLocal() as db:
        db.get(User, "u-admin").password_hash = hash_password("test-runtime-password")
        db.commit()
    login = client.post("/api/v1/auth/login", json={"account": "admin@chainguard.demo", "password": "test-runtime-password"})
    assert login.status_code == 200
    assert "refreshToken" not in login.json()
    assert "HttpOnly" in login.headers["set-cookie"]
    refreshed = client.post("/api/v1/auth/refresh", json={})
    assert refreshed.status_code == 200
    assert set(refreshed.json()) == {"token", "expiresIn"}
    assert "HttpOnly" in refreshed.headers["set-cookie"]


def test_register_provisions_real_tenant_and_operating_role():
    phone = f"139{uuid.uuid4().int % 10**8:08d}"
    response = client.post("/api/v1/auth/register", json={"phone": phone, "password": "register-password", "companyName": "注册验收企业", "industry": "电子制造", "scale": "50-200", "ownerRole": "供应链负责人"})
    assert response.status_code == 201
    body = response.json()
    assert body["currentUser"]["roleCode"] == "scm_lead"
    assert body["tenant"]["name"] == "注册验收企业"
    assert "refreshToken" not in body


def test_data_view_is_limited_to_own_business_domain_and_admin_has_read_codes():
    assert client.get("/api/v1/data/supplier", headers=headers("buyer")).status_code == 200
    assert client.get("/api/v1/data/material", headers=headers("buyer")).status_code == 403
    admin = client.get("/api/v1/auth/me", headers=headers("admin")).json()["currentUser"]
    assert {"data:view", "decision:view", "task:view", "report:view"}.issubset(set(admin["permissions"]))


def test_tenant_isolation_hides_other_tenant_rows():
    with SessionLocal() as db:
        db.merge(Tenant(id="tenant-other", name="其他租户", industry="制造", scale="small", status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        db.merge(Risk(id="risk-other", tenant_id="tenant-other", code="OTHER", level="high", type="供应", object_type="供应商", object_name="不可见", score=99, rule="隔离测试", found_at="2026-07-11", status="new", details={}))
        db.commit()
    response = client.get("/api/v1/risks", headers=headers("scm_lead"))
    assert response.status_code == 200
    assert "risk-other" not in {item["id"] for item in response.json()["data"]}


def test_illegal_incident_transition_returns_409():
    item_id = f"inc-test-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(Incident(id=item_id, tenant_id="tenant-demo", code=item_id, title="状态机测试", type="manual", level="low", status="pending", owner="测试", source_risk_ids=[], loss=0, cost=0))
        db.commit()
    response = client.patch(f"/api/v1/incidents/{item_id}", json={"status": "executing"}, headers=headers("scm_lead"))
    assert response.status_code == 409
    assert response.json()["code"] == "CG-2201"


def test_write_and_audit_are_committed_together():
    item_id = f"inc-audit-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(Incident(id=item_id, tenant_id="tenant-demo", code=item_id, title="审计测试", type="manual", level="low", status="pending", owner="测试", source_risk_ids=[], loss=0, cost=0))
        db.commit()
    response = client.patch(f"/api/v1/incidents/{item_id}", json={"status": "planning"}, headers=headers("scm_lead"))
    assert response.status_code == 200
    logs = client.get("/api/v1/audit-logs", headers=headers("admin"), params={"targetType": "incident"}).json()["data"]
    assert any(item["targetId"] == item_id and item["action"] == "更新事件" for item in logs)


def test_decision_mapper_always_returns_three_frontend_proposals():
    mapped = map_decision_result({"proposals": [{"agent_name": "采购 Agent", "proposal_title": "多源联合补货", "proposal": "采购说明", "total_score": 88}]}, "inc-1")
    assert len(mapped) == 3
    assert [item["tag"] for item in mapped] == ["recommended", "alternative", "invalid"]
    assert all(item["incident_id"] == "inc-1" for item in mapped)
    assert mapped[0]["name"] == "多源联合补货"
    assert mapped[0]["reason"] == "采购说明"
    assert "totalCost" in mapped[0]["explanation"]["dataMissing"]


def test_settings_user_crud_and_data_record_persistence():
    admin = headers("admin")
    created = client.post("/api/v1/settings/users", headers=admin, json={"name": "测试用户", "account": f"test-{uuid.uuid4().hex}@example.com", "password": "test-only-password", "roleId": "role-buyer"})
    assert created.status_code == 201
    user_id = created.json()["id"]
    assert client.patch(f"/api/v1/settings/users/{user_id}", headers=admin, json={"status": "disabled"}).status_code == 200
    assert client.delete(f"/api/v1/settings/users/{user_id}", headers=admin).status_code == 204

    record = client.post("/api/v1/data/material", headers=headers("scm_lead"), json={"name": "测试物料", "category": "芯片"})
    assert record.status_code == 201
    rows = client.get("/api/v1/data/material", headers=headers("scm_lead")).json()["data"]
    assert any(item["id"] == record.json()["id"] for item in rows)


def test_incident_create_has_no_demo_business_defaults():
    response = client.post(
        "/api/v1/incidents",
        headers=headers("scm_lead"),
        json={"riskIds": [], "title": "运输事件", "type": "transport_delay", "loss": 123, "cost": 45},
    )
    assert response.status_code == 201
    assert response.json()["type"] == "transport_delay"
    assert response.json()["loss"] == 123
    assert response.json()["cost"] == 45


def test_transfer_requires_active_user_in_same_tenant():
    suffix = uuid.uuid4().hex
    incident_id, proposal_id, approval_id = f"inc-{suffix}", f"prop-{suffix}", f"ap-{suffix}"
    with SessionLocal() as db:
        db.add(Incident(id=incident_id, tenant_id="tenant-demo", code=incident_id, title="转办测试", type="manual", level="medium", status="approving", owner="测试", source_risk_ids=[], loss=0, cost=0))
        db.add(Proposal(id=proposal_id, tenant_id="tenant-demo", incident_id=incident_id, name="转办方案", tag="recommended", total_cost=0, lead_time_impact=0, residual_risk="low", customer_impact=0, high_value_customers=0, reason="", views={}, constraints=[], explanation={}))
        db.add(Approval(id=approval_id, tenant_id="tenant-demo", proposal_id=proposal_id, incident_id=incident_id, status="submitted", risk_level="medium", summary="转办方案", cost_impact=0, submitter="供应链负责人", waiting_hours=0, cc_role_codes=[], history=[]))
        db.commit()

    invalid = client.post(f"/api/v1/approvals/{approval_id}/transfer", headers=headers("boss"), json={"assignee": "u-not-in-tenant"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "CG-2404"

    valid = client.post(f"/api/v1/approvals/{approval_id}/transfer", headers=headers("boss"), json={"assignee": "u-buyer"})
    assert valid.status_code == 200
    assert valid.json()["approval"]["transferredTo"] == "u-buyer"


def test_settings_users_exposes_account_but_never_password_hash():
    response = client.get("/api/v1/settings/users", headers=headers("admin"))
    assert response.status_code == 200
    assert all("account" in item for item in response.json()["data"])
    assert all("passwordHash" not in item for item in response.json()["data"])


def test_upload_rejects_extension_and_oversize():
    auth = headers("scm_lead")
    invalid = client.post("/api/v1/imports/upload?type=material", headers=auth, files={"file": ("payload.exe", b"bad", "application/octet-stream")})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "CG-2603"

    with patch("src.webapi.routers.imports_settings.settings", SimpleNamespace(max_import_bytes=4)):
        oversized = client.post("/api/v1/imports/upload?type=material", headers=auth, files={"file": ("payload.csv", b"12345", "text/csv")})
    assert oversized.status_code == 413
    assert oversized.json()["code"] == "CG-2604"


def test_import_confirm_requires_preflight_or_explicit_force():
    auth = headers("scm_lead")
    uploaded_id, failed_id = f"import-state-uploaded-{uuid.uuid4().hex}", f"import-state-failed-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(ImportJob(id=uploaded_id, tenant_id="tenant-demo", file_name="rows.csv", import_type="material", status="uploaded", progress=0, options={}, result={}))
        db.add(ImportJob(id=failed_id, tenant_id="tenant-demo", file_name="rows.csv", import_type="material", status="failed", progress=25, options={}, result={}))
        db.commit()
    assert client.post(f"/api/v1/imports/{uploaded_id}/confirm", headers=auth, json={"values": {}}).status_code == 409
    assert client.post(f"/api/v1/imports/{failed_id}/confirm", headers=auth, json={"values": {}}).status_code == 409
    forced = client.post(f"/api/v1/imports/{failed_id}/confirm", headers=auth, json={"values": {"force": True}})
    assert forced.status_code == 200
    assert forced.json()["status"] == "confirmed"


def test_notification_read_state_is_persisted_and_user_scoped():
    notification_id = f"notification-private-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(NotificationMessage(id=notification_id, tenant_id="tenant-demo", user_id="u-finance", kind="approval", title="仅财务可见", target="/"))
        db.commit()
    assert client.post(f"/api/v1/notifications/{notification_id}/read", headers=headers("buyer")).status_code == 404
    assert client.post(f"/api/v1/notifications/{notification_id}/read", headers=headers("finance")).status_code == 200
    refreshed = client.get("/api/v1/notifications", headers=headers("finance")).json()["data"]
    assert next(item for item in refreshed if item["id"] == notification_id)["read"] is True


def test_four_concurrent_decision_jobs_do_not_deadlock():
    from src.orchestrator import DecisionOrchestrator
    assert jobs.job_executor is not jobs.decision_executor
    ctx = AuthContext("u-scm_lead", "tenant-demo", "供应链负责人", "scm_lead", ())
    job_ids = []
    with SessionLocal() as db:
        for _ in range(4):
            suffix = uuid.uuid4().hex
            incident_id, job_id = f"inc-concurrent-{suffix}", f"job-concurrent-{suffix}"
            db.add(Incident(id=incident_id, tenant_id="tenant-demo", code=incident_id, title="并发决策", type="manual", level="low", status="planning", owner=ctx.name, source_risk_ids=[], loss=0, cost=0))
            db.add(Job(id=job_id, tenant_id="tenant-demo", kind="decision", resource_id=incident_id, idempotency_key=f"decision:{incident_id}", status="pending", progress=0, result={}))
            job_ids.append(job_id)
        db.commit()

    # C1 Web jobs no longer call run_demo; patch the worker boundary so this
    # regression remains focused on executor separation/deadlock behavior.
    with patch("src.webapi.jobs._execute_tenant_decision", return_value=DecisionOrchestrator().run_demo()):
        futures = [jobs.job_executor.submit(jobs._run_decision_job, job_id, ctx) for job_id in job_ids]
        for future in futures:
            future.result(timeout=5)

    with SessionLocal() as db:
        assert all(db.get(Job, job_id).status == "succeeded" for job_id in job_ids)


def _high_risk_approval_for_countersign() -> tuple[str, str]:
    suffix = uuid.uuid4().hex
    incident_id, proposal_id, approval_id = f"inc-high-{suffix}", f"prop-high-{suffix}", f"ap-high-{suffix}"
    with SessionLocal() as db:
        db.add(Incident(id=incident_id, tenant_id="tenant-demo", code=incident_id, title="高风险会签测试", type="manual", level="high", status="approving", owner="测试", source_risk_ids=[], loss=0, cost=0))
        db.add(Proposal(id=proposal_id, tenant_id="tenant-demo", incident_id=incident_id, name="高风险方案", tag="recommended", total_cost=123, lead_time_impact=1, residual_risk="low", customer_impact=1, high_value_customers=1, reason="测试", views={}, constraints=[], explanation={}))
        db.add(Approval(id=approval_id, tenant_id="tenant-demo", proposal_id=proposal_id, incident_id=incident_id, status="submitted", risk_level="high", summary="高风险方案", cost_impact=123, submitter="供应链负责人", waiting_hours=0, cc_role_codes=["finance"], history=[]))
        db.commit()
    return incident_id, approval_id


def test_high_risk_approval_requires_countersign_before_creating_tasks():
    incident_id, approval_id = _high_risk_approval_for_countersign()
    approved = client.post(f"/api/v1/approvals/{approval_id}/approve", headers=headers("boss"), json={})
    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "pending_countersign"
    with SessionLocal() as db:
        assert not list(db.query(__import__("src.webapi.models", fromlist=["Task"]).Task).filter_by(incident_id=incident_id))
    countersigned = client.post(f"/api/v1/approvals/{approval_id}/countersign", headers=headers("finance"), json={})
    assert countersigned.status_code == 200
    assert countersigned.json()["approval"]["status"] == "approved"
    with SessionLocal() as db:
        tasks = list(db.query(__import__("src.webapi.models", fromlist=["Task"]).Task).filter_by(incident_id=incident_id))
        assert len(tasks) == 5
        assert all(task.assignee.startswith("u-") and task.due_at for task in tasks)


def test_expired_countersign_auto_releases_and_notifies_finance():
    incident_id, approval_id = _high_risk_approval_for_countersign()
    assert client.post(f"/api/v1/approvals/{approval_id}/approve", headers=headers("boss"), json={}).json()["approval"]["status"] == "pending_countersign"
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        approval.history = [{**entry, "time": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()} if entry["action"] == "approve" else entry for entry in approval.history]
        db.commit()
    assert release_expired_countersigns() == 1
    with SessionLocal() as db:
        assert db.get(Approval, approval_id).status == "approved"
        assert db.get(Incident, incident_id).status == "executing"
        assert any("超时自动放行" in item.title for item in db.query(NotificationMessage).filter_by(tenant_id="tenant-demo"))


def test_late_boss_approval_does_not_skip_countersign_timeout_window():
    incident_id, approval_id = _high_risk_approval_for_countersign()
    with SessionLocal() as db:
        db.get(Approval, approval_id).created_at = datetime.now(timezone.utc) - timedelta(hours=5)
        db.commit()
    approved = client.post(f"/api/v1/approvals/{approval_id}/approve", headers=headers("boss"), json={})
    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "pending_countersign"
    assert release_expired_countersigns() == 0
    with SessionLocal() as db:
        assert db.get(Approval, approval_id).status == "pending_countersign"
        assert db.get(Incident, incident_id).status == "approving"
        assert not list(db.query(__import__("src.webapi.models", fromlist=["Task"]).Task).filter_by(incident_id=incident_id))


def test_finance_rejection_returns_high_risk_incident_to_planning():
    incident_id, approval_id = _high_risk_approval_for_countersign()
    client.post(f"/api/v1/approvals/{approval_id}/approve", headers=headers("boss"), json={})
    rejected = client.post(f"/api/v1/approvals/{approval_id}/reject", headers=headers("finance"), json={"reason": "预算依据不足"})
    assert rejected.status_code == 200
    assert rejected.json()["approval"]["status"] == "rejected"
    with SessionLocal() as db:
        assert db.get(Incident, incident_id).status == "planning"


def _nested_decision_payload() -> dict:
    """真实嵌套结构：覆盖 camelCase/复合财务字段散落在各层的脱敏漏洞。"""
    return {
        "proposals": [{"total_cost": 80000, "supplier_name": "机密供应商", "scores": {"cost": 55.0, "timeliness": 75.0}}],
        "audit_entry": {"cost": 70000, "net_benefit": 600000.0, "penalty_savings": 180000.0, "profit_protected": 420000.0},
        "context": {
            "orders": [{"order_id": "SO-A-001", "penalty_cost": 180000, "gross_profit": 420000, "demand_qty": 5000}],
            "suppliers": [{"supplier_id": "SUP-B", "cost_multiplier": 1.45, "reliability_score": 86}],
            "transport_options": [{"mode": "air", "cost_level": "高", "estimated_hours": 18}],
        },
        "game_analysis": {"coordination_gain": 18.25, "pareto": {"points": [{"cost_multiplier": 4.45, "system_utility": 159.49}]}},
        "constraint_analysis": {"feasible_count": 27, "all_combos": [{"cost_multiplier": 2.55, "system_utility": 203.84}]},
        "approval_chain_seed": [{"costImpact": 128000.0, "summary": "双供应商加急补货"}],
        "arbitration": {},
    }


def test_decision_detail_and_export_are_masked_by_requester_permissions():
    incident_id = f"inc-detail-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(Incident(id=incident_id, tenant_id="tenant-demo", code=incident_id, title="脱敏测试", type="manual", level="high", status="deciding", owner="测试", source_risk_ids=[], loss=90000, cost=80000))
        db.add(DecisionDetail(id=f"detail-{uuid.uuid4().hex}", tenant_id="tenant-demo", incident_id=incident_id, job_id="job-test", payload=_nested_decision_payload()))
        db.add(Approval(id=f"ap-{uuid.uuid4().hex}", tenant_id="tenant-demo", proposal_id="prop-mask", incident_id=incident_id, status="approved", risk_level="high", summary="双供应商加急补货", cost_impact=128000.0, submitter="供应链负责人", waiting_hours=1.2, cc_role_codes=["finance"], countersigned=True, history=[]))
        db.commit()
    buyer = client.get(f"/api/v1/incidents/{incident_id}/decision-detail", headers=headers("buyer"))
    boss = client.get(f"/api/v1/incidents/{incident_id}/decision-detail", headers=headers("boss"))
    assert buyer.status_code == boss.status_code == 200
    bj = buyer.json()
    # GET：各层财务字段（含 camelCase/复合字段）一律脱敏，非财务字段保留
    assert bj["proposals"][0]["total_cost"] == "***"
    assert bj["proposals"][0]["scores"]["cost"] == "***"
    assert bj["proposals"][0]["scores"]["timeliness"] == 75.0
    assert bj["audit_entry"]["cost"] == "***"
    assert bj["audit_entry"]["net_benefit"] == "***"
    assert bj["audit_entry"]["penalty_savings"] == "***"
    assert bj["audit_entry"]["profit_protected"] == "***"
    assert bj["context"]["orders"][0]["penalty_cost"] == "***"
    assert bj["context"]["orders"][0]["gross_profit"] == "***"
    assert bj["context"]["orders"][0]["demand_qty"] == 5000
    assert bj["context"]["suppliers"][0]["cost_multiplier"] == "***"
    assert bj["context"]["suppliers"][0]["reliability_score"] == 86
    assert bj["context"]["transport_options"][0]["cost_level"] == "***"
    assert bj["game_analysis"]["pareto"]["points"][0]["cost_multiplier"] == "***"
    assert bj["game_analysis"]["pareto"]["points"][0]["system_utility"] == 159.49
    assert bj["game_analysis"]["coordination_gain"] == 18.25
    assert bj["constraint_analysis"]["all_combos"][0]["cost_multiplier"] == "***"
    # approval_chain 由路由注入的真实审批记录，costImpact camelCase 必须脱敏
    assert bj["approval_chain"] and bj["approval_chain"][0]["costImpact"] == "***"
    # boss：财务字段原值可见
    bo = boss.json()
    assert bo["proposals"][0]["total_cost"] == 80000
    assert bo["audit_entry"]["net_benefit"] == 600000.0
    assert bo["context"]["orders"][0]["penalty_cost"] == 180000
    assert bo["context"]["suppliers"][0]["cost_multiplier"] == 1.45
    assert bo["approval_chain"][0]["costImpact"] == 128000.0
    # JSON 导出走同一脱敏路径
    exported = client.get(f"/api/v1/incidents/{incident_id}/decision-detail/export?format=json", headers=headers("buyer"))
    assert exported.status_code == 200
    ej = exported.json()
    assert ej["proposals"][0]["total_cost"] == "***"
    assert ej["audit_entry"]["net_benefit"] == "***"
    assert ej["context"]["orders"][0]["penalty_cost"] == "***"


def test_initial_migration_uses_explicit_alembic_operations():
    migration = Path("alembic/versions/20260711_0001_initial.py").read_text(encoding="utf-8")
    api_source = Path("src/api.py").read_text(encoding="utf-8")
    assert "op.create_table" in migration
    assert "metadata.create_all" not in migration
    assert "metadata.create_all" not in api_source


def test_notification_rules_are_consumed_for_missing_phase5a_events():
    assert {"task_assigned", "task_urged", "task_overdue", "import_succeeded", "import_failed", "risk_high"}.issubset(FIXED_RULES)
    target = f"/test-notification-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        ensure_rules(db, "tenant-demo")
        db.flush()
        notify_event(db, "tenant-demo", "task_assigned", {"assignee_user_id": "u-buyer", "title": "任务分派", "target": target})
        # The caller provides no role list: recipient comes from the stored strategy.
        messages = list(db.query(NotificationMessage).filter_by(tenant_id="tenant-demo", kind="task_assigned", target=target))
        assert [item.user_id for item in messages] == ["u-buyer"]
        approval_target = f"/approval-{uuid.uuid4().hex}"
        notify_event(db, "tenant-demo", "approval_submitted", {"risk_level": "high", "cost_impact": 90000, "title": "高风险待审批", "target": approval_target})
        recipients = {item.user_id for item in db.query(NotificationMessage).filter_by(tenant_id="tenant-demo", kind="approval_submitted", target=approval_target)}
        assert {"u-boss", "u-finance"}.issubset(recipients)
        db.rollback()


def test_overdue_task_scanner_marks_once_and_notifies_assignee_and_scm():
    task_id = f"task-overdue-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(Task(id=task_id, tenant_id="tenant-demo", title="逾期扫描测试", source="test", incident_id="", assignee="u-buyer", role_code="buyer", status="pending", due_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), priority="高", checklist=[]))
        db.commit()
    assert release_overdue_tasks() == 1
    assert release_overdue_tasks() == 0
    with SessionLocal() as db:
        assert db.get(Task, task_id).status == "overdue"
        recipients = {item.user_id for item in db.query(NotificationMessage).filter_by(tenant_id="tenant-demo", kind="task_overdue", target="/task/overdue")}
        assert {"u-buyer", "u-scm_lead"}.issubset(recipients)


def test_preflight_normalized_preview_and_insufficient_disk_is_not_forceable(tmp_path):
    from src.webapi.routers.imports_settings import normalized_preview
    path = tmp_path / "rows.csv"
    path.write_text("id,name\n1,测试\n", encoding="utf-8")
    assert normalized_preview(path)["previewRows"] == [{"id": "1", "name": "测试"}]
    item_id = f"import-disk-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(ImportJob(id=item_id, tenant_id="tenant-demo", file_name="rows.csv", import_type="material", status="failed", progress=25, options={}, result={"verdict": "INSUFFICIENT_DISK"}))
        db.commit()
    response = client.post(f"/api/v1/imports/{item_id}/confirm", headers=headers("scm_lead"), json={"values": {"force": True}})
    assert response.status_code == 409


def test_xlsx_preflight_normalizes_rows_before_estimating(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["物料编号", "物料名称", "分类"])
    sheet.append(["MAT-001", "MCU-A9", "芯片"])
    sheet.append(["MAT-002", "电源模块", "电子件"])
    source = tmp_path / "materials.xlsx"
    workbook.save(source)
    uploaded = client.post(
        "/api/v1/imports/upload?type=material",
        headers=headers("scm_lead"),
        files={"file": (source.name, source.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert uploaded.status_code == 201
    response = client.post(f"/api/v1/imports/{uploaded.json()['id']}/preflight", headers=headers("scm_lead"), json={})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["canProceed"] is True
    assert result["estimatedRows"] >= 2
    assert result["normalized"]["previewRows"] == [
        {"物料编号": "MAT-001", "物料名称": "MCU-A9", "分类": "芯片"},
        {"物料编号": "MAT-002", "物料名称": "电源模块", "分类": "电子件"},
    ]


def test_game_analysis_and_pending_job_metric_are_persistable():
    from src.observability import Metrics
    from src.orchestrator import DecisionOrchestrator
    payload = DecisionOrchestrator().run_demo().to_dict()
    analysis = jobs.build_game_analysis(payload)
    assert analysis["strategy_space_size"] == 27
    assert analysis["pareto"]["points"]
    Metrics.reset(); Metrics.set_jobs_pending(3)
    assert "chainguard_jobs_pending 3" in Metrics.render()


def _timed_out_released_approval() -> tuple[str, str]:
    """boss 终批 → 回拨时间 → 超时扫描放行，返回 (incident_id, approval_id)。"""
    incident_id, approval_id = _high_risk_approval_for_countersign()
    assert client.post(f"/api/v1/approvals/{approval_id}/approve", headers=headers("boss"), json={}).status_code == 200
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        approval.history = [{**entry, "time": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()} if entry["action"] == "approve" else entry for entry in approval.history]
        db.commit()
    assert release_expired_countersigns() >= 1
    with SessionLocal() as db:
        released = db.get(Approval, approval_id)
        assert released.status == "approved"
        assert any(entry.get("action") == "countersign_timeout_release" for entry in released.history)
    return incident_id, approval_id


def test_ratify_approve_after_timeout_release_persists_and_notifies():
    """P0-1：追认通过必须在 approved+超时放行状态下真实落库，且不回滚任务。"""
    incident_id, approval_id = _timed_out_released_approval()
    with SessionLocal() as db:
        tasks_before = len(list(db.query(Task).filter_by(incident_id=incident_id)))
    assert tasks_before == 5
    response = client.post(f"/api/v1/approvals/{approval_id}/ratify_approve", headers=headers("finance"), json={})
    assert response.status_code == 200, response.text
    body = response.json()["approval"]
    assert body["status"] == "approved"
    assert any(item["action"] == "ratify_approve" for item in body["history"])
    with SessionLocal() as db:
        # 不回滚：任务原样保留
        assert len(list(db.query(Task).filter_by(incident_id=incident_id))) == tasks_before
        # 通知 boss 与提交人（scm_lead 的用户名即 submitter）
        recipients = {item.user_id for item in db.query(NotificationMessage).filter_by(tenant_id="tenant-demo", kind="countersign_ratified", target=f"/decision/approval/{approval_id}")}
        assert {"u-boss", "u-scm_lead"}.issubset(recipients)
    logs = client.get("/api/v1/audit-logs", headers=headers("admin"), params={"targetType": "approval", "action": "财务追认通过"}).json()["data"]
    assert any(item["targetId"] == approval_id for item in logs)
    # 只能追认一次
    second = client.post(f"/api/v1/approvals/{approval_id}/ratify_object", headers=headers("finance"), json={"reason": "重复追认"})
    assert second.status_code == 409
    assert second.json()["code"] == "CG-2405"


def test_ratify_object_requires_reason_and_writes_history():
    """P0-1：追认异议必填理由；提交成功后写审批历史与审计。"""
    incident_id, approval_id = _timed_out_released_approval()
    missing_reason = client.post(f"/api/v1/approvals/{approval_id}/ratify_object", headers=headers("finance"), json={})
    assert missing_reason.status_code == 422
    assert missing_reason.json()["code"] == "CG-2402"
    response = client.post(f"/api/v1/approvals/{approval_id}/ratify_object", headers=headers("finance"), json={"reason": "资金依据不足，需事后复核"})
    assert response.status_code == 200, response.text
    body = response.json()["approval"]
    assert body["status"] == "approved"  # 留痕不回滚
    assert any(item["action"] == "ratify_object" and item["reason"] for item in body["history"])
    with SessionLocal() as db:
        assert db.get(Incident, incident_id).status == "executing"
        assert len(list(db.query(Task).filter_by(incident_id=incident_id))) == 5


def test_ratify_rejected_when_not_timeout_released_or_wrong_role():
    """P0-1：非超时放行的 approved 单与非财务角色都不能追认。"""
    incident_id, approval_id = _high_risk_approval_for_countersign()
    client.post(f"/api/v1/approvals/{approval_id}/approve", headers=headers("boss"), json={})
    client.post(f"/api/v1/approvals/{approval_id}/countersign", headers=headers("finance"), json={})
    normally_approved = client.post(f"/api/v1/approvals/{approval_id}/ratify_approve", headers=headers("finance"), json={})
    assert normally_approved.status_code == 409
    incident_id2, approval_id2 = _timed_out_released_approval()
    wrong_role = client.post(f"/api/v1/approvals/{approval_id2}/ratify_approve", headers=headers("boss"), json={})
    assert wrong_role.status_code == 409


def test_regeneration_archives_referenced_proposal_and_keeps_approval_detail_alive():
    """P1-10：重新推演后，被审批引用的旧 Proposal 必须保留，旧审批详情仍为 200。"""
    suffix = uuid.uuid4().hex
    incident_id, kept_id, dropped_id, approval_id = f"inc-regen-{suffix}", f"prop-kept-{suffix}", f"prop-dropped-{suffix}", f"ap-regen-{suffix}"
    ctx = AuthContext("u-scm_lead", "tenant-demo", "供应链负责人", "scm_lead", ())
    job_id = f"job-regen-{suffix}"
    with SessionLocal() as db:
        db.add(Incident(id=incident_id, tenant_id="tenant-demo", code=incident_id, title="重新推演保留测试", type="manual", level="high", status="planning", owner="测试", source_risk_ids=[], loss=0, cost=0))
        db.add(Proposal(id=kept_id, tenant_id="tenant-demo", incident_id=incident_id, name="被审批引用的旧方案", tag="recommended", total_cost=100, lead_time_impact=1, residual_risk="low", customer_impact=1, high_value_customers=1, reason="", views={}, constraints=[], explanation={}))
        db.add(Proposal(id=dropped_id, tenant_id="tenant-demo", incident_id=incident_id, name="未被引用的候选", tag="alternative", total_cost=200, lead_time_impact=2, residual_risk="medium", customer_impact=2, high_value_customers=0, reason="", views={}, constraints=[], explanation={}))
        db.add(Approval(id=approval_id, tenant_id="tenant-demo", proposal_id=kept_id, incident_id=incident_id, status="approved", risk_level="high", summary="被引用方案", cost_impact=100, submitter="供应链负责人", waiting_hours=0, cc_role_codes=["finance"], history=[]))
        db.add(Job(id=job_id, tenant_id="tenant-demo", kind="decision", resource_id=incident_id, idempotency_key=f"decision:{incident_id}", status="pending", progress=0, result={}))
        db.commit()
    from src.orchestrator import DecisionOrchestrator
    with patch("src.webapi.jobs._execute_tenant_decision", return_value=DecisionOrchestrator().run_demo()):
        jobs._run_decision_job(job_id, ctx)
    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "succeeded"
        kept = db.get(Proposal, kept_id)
        assert kept is not None and kept.archived is True
        assert db.get(Proposal, dropped_id) is None
    detail = client.get(f"/api/v1/approvals/{approval_id}", headers=headers("boss"))
    assert detail.status_code == 200
    assert detail.json()["proposal"]["id"] == kept_id
    # 归档方案不进方案列表
    listed = client.get(f"/api/v1/proposals?incidentId={incident_id}", headers=headers("boss")).json()["data"]
    assert kept_id not in {item["id"] for item in listed}


def test_mapper_maps_trusted_context_fields_and_never_fakes_zero():
    """P0-2：订单/客户等级/供应商交期/风险评分从 context 与 scores 映射；未知值必须是 None 而不是 0。"""
    result = {
        "proposals": [{
            "agent_name": "采购 Agent",
            "proposal_title": "多源联合补货：B备用供应商",
            "proposal": "针对核心控制芯片的供应缺口执行多源联合补货。",
            "total_score": 88,
            "scores": {"risk_reduction": 86},
        }],
        "context": {
            "inventory": {"material_id": "M-AX100", "material_name": "核心控制芯片"},
            "orders": [
                {"order_id": "SO-A-001", "priority": "A", "required_material": "M-AX100"},
                {"order_id": "SO-B-002", "priority": "B", "required_material": "M-AX100"},
                {"order_id": "SO-C-003", "priority": "C", "required_material": "M-AX100"},
            ],
            "suppliers": [{"supplier_name": "B备用供应商", "lead_time_hours": 36}],
        },
        "constraint_analysis": {"feasible_count": 27},
        "explanation": {},
    }
    mapped = map_decision_result(result, "inc-trusted")
    top = mapped[0]
    assert top["total_cost"] is None  # 引擎没有 ¥ 成本，禁止伪装成 0
    assert top["lead_time_impact"] == 2  # 36 小时按瓶颈供应商向上取整为 2 天
    assert top["customer_impact"] == 3
    assert top["high_value_customers"] == 1
    assert top["residual_risk"] == "low"  # risk_reduction=86 → low
    assert top["explanation"]["dataMissing"] == ["totalCost"]
    # 完全空的填充位：一律缺失而不是 0
    filler = mapped[2]
    assert filler["total_cost"] is None
    assert filler["lead_time_impact"] is None
    assert filler["residual_risk"] is None


def test_corrupted_xlsx_preflight_is_red_light_and_not_forceable():
    """P1-4：损坏的 XLSX 必须红灯（PARSE_ERROR），且不能强制导入。"""
    uploaded = client.post(
        "/api/v1/imports/upload?type=material",
        headers=headers("scm_lead"),
        files={"file": ("broken.xlsx", b"this-is-not-a-zip-workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert uploaded.status_code == 201
    job_id = uploaded.json()["id"]
    response = client.post(f"/api/v1/imports/{job_id}/preflight", headers=headers("scm_lead"), json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["result"]["verdict"] == "PARSE_ERROR"
    assert payload["result"]["canProceed"] is False
    assert payload["result"]["normalized"]["previewRows"] == []
    forced = client.post(f"/api/v1/imports/{job_id}/confirm", headers=headers("scm_lead"), json={"values": {"force": True}})
    assert forced.status_code == 409


def test_admin_can_read_approvals_but_cannot_act():
    """P1-11：settings:manage 管理员只读查看审批；任何审批动作仍被 403 拒绝。"""
    incident_id, approval_id = _high_risk_approval_for_countersign()
    listed = client.get("/api/v1/approvals", headers=headers("admin"))
    assert listed.status_code == 200
    detail = client.get(f"/api/v1/approvals/{approval_id}", headers=headers("admin"))
    assert detail.status_code == 200
    for action, body in (("approve", {}), ("reject", {"reason": "越权测试"}), ("countersign", {}), ("submit", {})):
        response = client.post(f"/api/v1/approvals/{approval_id}/{action}", headers=headers("admin"), json=body)
        assert response.status_code == 403, f"admin should not be able to {action}"


def test_pytest_database_url_is_isolated_from_default_db():
    """P2-15：测试进程不得使用仓库默认 chainguard.db。"""
    from src.webapi.database import engine
    url = str(engine.url)
    assert not url.endswith("/chainguard.db")
    assert url != "sqlite:///./chainguard.db"


def test_pdf_export_masks_buyer_and_keeps_boss_values_with_real_text_extraction():
    """P0-3：真实导出 buyer/boss 两份 PDF，用 pypdf 文本提取对照脱敏字段。"""
    pytest.importorskip("reportlab", reason="PDF 导出运行依赖（requirements.txt）")
    pypdf = pytest.importorskip("pypdf", reason="PDF 文本提取验证依赖（requirements-dev.txt）")
    incident_id = f"inc-pdf-{uuid.uuid4().hex}"
    approval_id = f"ap-pdf-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(Incident(id=incident_id, tenant_id="tenant-demo", code=incident_id, title="PDF 脱敏对照", type="manual", level="high", status="deciding", owner="测试", source_risk_ids=[], loss=90000, cost=80000))
        db.add(DecisionDetail(
            id=f"detail-pdf-{uuid.uuid4().hex}",
            tenant_id="tenant-demo",
            incident_id=incident_id,
            job_id="job-pdf",
            payload={
                "proposals": [{"proposal_title": "加急补货", "total_cost": 81234, "supplier_name": "机密供应商"}],
                "audit_entry": {
                    "cost": 71234,
                    "net_benefit": 612345,
                    "penalty_savings": 182345,
                    "profit_protected": 432100,
                },
                "arbitration": {},
            },
        ))
        db.add(Approval(
            id=approval_id,
            tenant_id="tenant-demo",
            proposal_id=f"prop-{approval_id}",
            incident_id=incident_id,
            status="submitted",
            risk_level="high",
            summary="PDF 审批链脱敏",
            cost_impact=129876,
            submitter="供应链负责人",
            waiting_hours=1,
            cc_role_codes=["finance"],
            history=[],
        ))
        db.commit()
    buyer = client.get(f"/api/v1/incidents/{incident_id}/decision-detail/export?format=pdf", headers=headers("buyer"))
    boss = client.get(f"/api/v1/incidents/{incident_id}/decision-detail/export?format=pdf", headers=headers("boss"))
    assert buyer.status_code == boss.status_code == 200
    assert buyer.headers["content-type"].startswith("application/pdf")

    def extract(content: bytes) -> str:
        return "".join(page.extract_text() or "" for page in pypdf.PdfReader(BytesIO(content)).pages)

    buyer_text, boss_text = extract(buyer.content), extract(boss.content)
    assert "***" in buyer_text
    sensitive_values = ("81234", "71234", "612345", "182345", "432100", "129876")
    assert all(value not in buyer_text for value in sensitive_values)
    assert all(value in boss_text for value in sensitive_values)
    assert "ChainGuard 决策报告" in buyer_text
    assert "审批链" in buyer_text and "风险与推演结果" in buyer_text
    # 布局回归：业务报告而非单页 JSON 文本墙，分页与多章节结构成立
    assert len(pypdf.PdfReader(BytesIO(buyer.content)).pages) >= 1
    assert "决策基本信息" in buyer_text and "方案摘要" in buyer_text


def test_medium_risk_with_unknown_cost_conservatively_ccs_finance():
    """P0-2 附带口径：中风险成本未知（None）按保守口径抄送财务，而不是当作 0 跳过。"""
    suffix = uuid.uuid4().hex
    incident_id, proposal_id = f"inc-nullcost-{suffix}", f"prop-nullcost-{suffix}"
    with SessionLocal() as db:
        db.add(Incident(id=incident_id, tenant_id="tenant-demo", code=incident_id, title="成本未知抄送测试", type="manual", level="medium", status="deciding", owner="测试", source_risk_ids=[], loss=0, cost=0))
        db.add(Proposal(id=proposal_id, tenant_id="tenant-demo", incident_id=incident_id, name="成本未知方案", tag="recommended", total_cost=None, lead_time_impact=None, residual_risk=None, customer_impact=None, high_value_customers=None, reason="", views={}, constraints=[], explanation={}))
        db.commit()
    response = client.post(f"/api/v1/proposals/{proposal_id}/submit", headers=headers("scm_lead"), json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["costImpact"] is None
    assert "finance" in body["ccRoleCodes"]


def test_decision_detail_natural_language_fields_are_scrubbed_for_buyer():
    """P0-1：自然语言/解释/推演/审计字段里内嵌的毛利、罚金、客户等级具体数字，
    GET decision-detail、JSON 导出、PDF 导出必须共用同一套脱敏并全部清洗。"""
    pypdf = pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")
    incident_id = f"inc-nl-{uuid.uuid4().hex}"
    payload = {
        "proposals": [{
            "agent_name": "财务 Agent",
            "proposal_title": "盈亏平衡截止",
            "reasoning": [
                "A类关键订单数量为 1，对应违约罚金 180000，占全部罚金 70.6%。",
                "当前订单总毛利为 632000，全部违约罚金为 255000，B/C类订单占比 66.7%。",
            ],
        }],
        "arbitration": {
            "final_decision_title": "分级保障",
            "final_score": 79.5,
            "final_strategy": "优先保护A类关键客户，预计避免违约损失 600000 元，应急成本约 128000 元。",
            "manual_confirmation_points": ["确认对A类订单的空运安排；违约罚金 180000 元敞口是否接受。"],
        },
        "audit_entry": {"decision_id": "d-nl", "note": "本次净收益 600000，保护利润 420000。"},
    }
    with SessionLocal() as db:
        db.add(Incident(id=incident_id, tenant_id="tenant-demo", code=incident_id, title="自然语言脱敏", type="manual", level="high", status="deciding", owner="t", source_risk_ids=[], loss=1, cost=1))
        db.add(DecisionDetail(id=f"detail-{uuid.uuid4().hex}", tenant_id="tenant-demo", incident_id=incident_id, job_id="job-nl", payload=payload))
        db.commit()
    leaks = ["180000", "632000", "255000", "600000", "420000", "128000"]
    for path in (f"/api/v1/incidents/{incident_id}/decision-detail",
                 f"/api/v1/incidents/{incident_id}/decision-detail/export?format=json"):
        text = client.get(path, headers=headers("buyer")).text
        for leaked in leaks:
            assert leaked not in text, f"{leaked} 泄漏给 buyer：{path}"
        assert "A类" not in text and "B/C类" not in text
    # boss（具备 field:cost/profit/customerLevel:view）保留真实数字与等级
    boss_text = client.get(f"/api/v1/incidents/{incident_id}/decision-detail", headers=headers("boss")).text
    assert "180000" in boss_text and "632000" in boss_text and "A类" in boss_text
    # PDF：仲裁结论与执行确认点渲染进报告，同样不得泄漏
    def pdf_text(role):
        r = client.get(f"/api/v1/incidents/{incident_id}/decision-detail/export?format=pdf", headers=headers(role))
        assert r.status_code == 200
        return "".join(p.extract_text() or "" for p in pypdf.PdfReader(BytesIO(r.content)).pages)
    bt = pdf_text("buyer")
    assert all(v not in bt for v in ("600000", "128000", "180000"))
    ot = pdf_text("boss")
    assert "600000" in ot and "128000" in ot


def test_tasks_scope_enforces_custom_data_range_without_task_manage():
    """P0-2：无 task:manage 的角色（buyer 等 custom 范围）只能看/改分派给自己的任务；
    有 task:manage 才能看全部。复用 task:manage，不新增权限码。"""
    mine = f"task-mine-{uuid.uuid4().hex}"
    other = f"task-other-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(Task(id=mine, tenant_id="tenant-demo", title="我的任务", source="test", incident_id="", assignee="u-buyer", role_code="buyer", status="pending", due_at="", priority="高", checklist=[]))
        db.add(Task(id=other, tenant_id="tenant-demo", title="他人任务", source="test", incident_id="", assignee="u-sales", role_code="sales", status="pending", due_at="", priority="高", checklist=[]))
        db.commit()
    resp = client.get("/api/v1/tasks", headers=headers("buyer"))
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()["data"]}
    assert mine in ids and other not in ids
    # 详情越权 404，本人 200
    assert client.get(f"/api/v1/tasks/{other}", headers=headers("buyer")).status_code == 404
    assert client.get(f"/api/v1/tasks/{mine}", headers=headers("buyer")).status_code == 200
    # PATCH 越权 403
    assert client.patch(f"/api/v1/tasks/{other}", headers=headers("buyer"), json={"status": "in_progress"}).status_code == 403
    # scm_lead 具 task:manage，看全部
    lead_ids = {t["id"] for t in client.get("/api/v1/tasks", headers=headers("scm_lead")).json()["data"]}
    assert mine in lead_ids and other in lead_ids
