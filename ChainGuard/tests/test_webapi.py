import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.setdefault("SEED_DEMO_PASSWORD", "test-runtime-password")

from src.api import app
from src.webapi.auth.security import AuthContext, create_tokens, hash_password
from src.webapi.database import SessionLocal
from src.webapi.models import Approval, ImportJob, Job, NotificationMessage, Incident, Proposal, Risk, Tenant, User
from src.webapi import jobs
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


def test_500_never_leaks_exception_or_internal_message():
    with patch("src.api.DecisionOrchestrator") as orchestrator:
        orchestrator.return_value.run_demo.side_effect = RuntimeError("database-password-secret")
        response = client.post("/decisions/demo")
    body = response.text
    assert response.status_code == 500
    assert "RuntimeError" not in body
    assert "database-password-secret" not in body
    assert set(response.json()) == {"code", "message", "traceId"}


def test_decision_mapper_always_returns_three_frontend_proposals():
    mapped = map_decision_result({"proposals": [{"agent_name": "采购 Agent", "total_score": 88}]}, "inc-1")
    assert len(mapped) == 3
    assert [item["tag"] for item in mapped] == ["recommended", "alternative", "invalid"]
    assert all(item["incident_id"] == "inc-1" for item in mapped)


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

    with patch("src.webapi.jobs.DecisionOrchestrator.run_demo", return_value={"proposals": []}):
        futures = [jobs.job_executor.submit(jobs._run_decision_job, job_id, ctx) for job_id in job_ids]
        for future in futures:
            future.result(timeout=5)

    with SessionLocal() as db:
        assert all(db.get(Job, job_id).status == "succeeded" for job_id in job_ids)


def test_initial_migration_uses_explicit_alembic_operations():
    migration = Path("alembic/versions/20260711_0001_initial.py").read_text(encoding="utf-8")
    api_source = Path("src/api.py").read_text(encoding="utf-8")
    assert "op.create_table" in migration
    assert "metadata.create_all" not in migration
    assert "metadata.create_all" not in api_source
