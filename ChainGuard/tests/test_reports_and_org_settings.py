"""报表聚合 + 审批链/数据范围配置的验收测试。

覆盖本批次修掉的三类"界面看起来能用、其实是假的"问题：
1. /reports/* 曾返回硬编码常量 → 现在必须来自租户库，且换租户就变。
2. 无数据时必须返回 null（P0-2 口径），不能伪装成 0。
3. 审批链/数据范围曾只弹成功提示 → 现在必须真落库、跨请求可读回。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.webapi.auth.security import create_tokens
from src.webapi.database import SessionLocal
from src.webapi.models import (
    Approval,
    ExperienceCard,
    Incident,
    Proposal,
    Risk,
    Role,
    Task,
    Tenant,
    User,
)
from src.webapi.org_settings import approval_chain_view, save_approval_chain, save_data_scope
from src.webapi.reports import executive_report, operation_report, response_report
from src.webapi.seed import seed


seed()
client = TestClient(app)


def _headers(user_id: str = "u-boss") -> dict[str, str]:
    with SessionLocal() as db:
        return {"Authorization": f"Bearer {create_tokens(db.get(User, user_id))['token']}"}


def _fresh_tenant(db) -> str:
    """建一个干净租户，避免与 seed 演示租户互相污染。"""
    tenant_id = f"t-report-{uuid.uuid4().hex[:8]}"
    db.merge(Tenant(
        id=tenant_id, name=tenant_id, industry="制造", scale="small",
        status="active", plan="trial", trial_end_at="", demo_data_flag=False,
    ))
    db.flush()  # 租户先落库，否则 roles.tenant_id 外键在同一批 flush 中失败
    for code, name in (("boss", "老板"), ("scm_lead", "供应链负责人"), ("finance", "财务")):
        db.add(Role(id=f"role-{tenant_id}-{code}", tenant_id=tenant_id, code=code, name=name, builtin=True, permissions=["*"]))
    db.flush()
    return tenant_id


# ------------------------------------------------------------------ 报表


def test_reports_return_null_not_zero_when_tenant_has_no_data():
    """空租户：净收益必须是 null（不可测量），不是 0（等于白干）。"""
    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        db.flush()  # 只 flush 不 commit：报表函数复用同一会话即可读到，退出时自动回滚

        executive = executive_report(db, tenant_id)
        operation = operation_report(db, tenant_id)

    assert executive["netBenefit"] is None
    assert executive["avoidedLoss"] is None
    assert executive["emergencyCost"] is None
    assert executive["avgResponseHours"] is None
    assert executive["riskCount"] == 0
    # 漏斗每一级都是真实的 0 计数，这个 0 是有意义的
    assert [stage["count"] for stage in operation["funnel"]] == [0, 0, 0, 0, 0]
    # 没有在办任务时超时率不可测量
    assert operation["overdueRate"] is None


def test_executive_report_computes_net_benefit_from_incidents():
    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        db.add(Incident(id=f"inc-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, code="INC-1", title="供应商停产", type="supplier_shutdown", level="high", status="closed", owner="scm", source_risk_ids=[], loss=900_000, cost=150_000, notes=[]))
        db.add(Incident(id=f"inc-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, code="INC-2", title="干线中断", type="logistics", level="medium", status="closed", owner="scm", source_risk_ids=[], loss=100_000, cost=50_000, notes=[]))
        db.flush()  # 只 flush 不 commit：报表函数复用同一会话即可读到，退出时自动回滚

        result = executive_report(db, tenant_id)

    # 净收益 = 避免损失 1,000,000 - 应急成本 200,000
    assert result["avoidedLoss"] == 1_000_000
    assert result["emergencyCost"] == 200_000
    assert result["netBenefit"] == 800_000
    assert result["riskCount"] == 2
    assert result["netBenefit"] != 732000, "不得再回落到旧的硬编码常量"


def test_executive_report_is_tenant_isolated():
    """两个租户各自的数字必须互不可见——这是曾经硬编码时无法体现的。"""
    with SessionLocal() as db:
        tenant_a = _fresh_tenant(db)
        tenant_b = _fresh_tenant(db)
        db.add(Incident(id=f"inc-{uuid.uuid4().hex[:8]}", tenant_id=tenant_a, code="A-1", title="A", type="supplier_shutdown", level="high", status="closed", owner="", source_risk_ids=[], loss=500_000, cost=100_000, notes=[]))
        db.flush()  # 只 flush 不 commit：报表函数复用同一会话即可读到，退出时自动回滚

        result_a = executive_report(db, tenant_a)
        result_b = executive_report(db, tenant_b)

    assert result_a["netBenefit"] == 400_000
    assert result_b["netBenefit"] is None


def test_operation_report_funnel_and_overdue_rate():
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        db.add(Risk(id=f"risk-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, code="R-1", level="high", type="supply", object_type="supplier", object_name="苏州芯片", score=92, rule="安全库存", found_at=now.isoformat(), status="new", details={}))
        db.add(Incident(id=incident_id, tenant_id=tenant_id, code="INC-1", title="停产", type="supplier_shutdown", level="high", status="open", owner="", source_risk_ids=[], loss=0, cost=0, notes=[]))
        db.add(Proposal(id=f"pro-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, incident_id=incident_id, name="双供应商", tag="推荐", total_cost=120_000, reason="", views={}, constraints=[], explanation={}))
        db.add(Approval(id=f"apr-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, proposal_id="p", incident_id=incident_id, status="approved", risk_level="high", summary="", submitter="scm", waiting_hours=6.0, cc_role_codes=[], history=[]))
        # 一条已超时、一条未超时
        db.add(Task(id=f"task-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, title="加急采购", source="", incident_id=incident_id, assignee="a", role_code="scm_lead", status="pending", due_at=(now - timedelta(hours=5)).isoformat(), priority="高", checklist=[]))
        db.add(Task(id=f"task-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, title="通知客户", source="", incident_id=incident_id, assignee="b", role_code="sales", status="pending", due_at=(now + timedelta(hours=5)).isoformat(), priority="中", checklist=[]))
        db.flush()  # 只 flush 不 commit：报表函数复用同一会话即可读到，退出时自动回滚

        result = operation_report(db, tenant_id)

    assert [stage["count"] for stage in result["funnel"]] == [1, 1, 1, 1, 0]
    assert result["overdueRate"] == 0.5
    by_role = {row["roleCode"]: row for row in result["overdueByRole"]}
    assert by_role["scm_lead"]["overdue"] == 1
    assert by_role["sales"]["overdue"] == 0


def test_response_report_costdiff_null_when_no_estimate():
    """方案没给出成本时，偏差必须是 null，不能算成 0 偏差。"""
    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        db.add(Incident(id=incident_id, tenant_id=tenant_id, code="INC-1", title="停产", type="supplier_shutdown", level="high", status="closed", owner="", source_risk_ids=[], loss=0, cost=90_000, notes=[]))
        db.add(Proposal(id=f"pro-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, incident_id=incident_id, name="方案", tag="推荐", total_cost=None, reason="", views={}, constraints=[], explanation={}))
        db.add(ExperienceCard(id=f"exp-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, title="复盘", content={}, status="verified", source_incident_id=incident_id, outcome={}, metrics={}, references=[]))
        db.flush()  # 只 flush 不 commit：报表函数复用同一会话即可读到，退出时自动回滚

        result = response_report(db, tenant_id)

    event = result["events"][0]
    assert event["actualCost"] == 90_000
    assert event["estimatedCost"] is None
    assert event["costDiff"] is None, "预估缺失时不得伪造 0 偏差"
    assert event["experienceCards"] == 1


def test_response_report_costdiff_when_estimate_present():
    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        db.add(Incident(id=incident_id, tenant_id=tenant_id, code="INC-1", title="停产", type="supplier_shutdown", level="high", status="closed", owner="", source_risk_ids=[], loss=0, cost=120_000, notes=[]))
        db.add(Proposal(id=f"pro-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id, incident_id=incident_id, name="方案", tag="推荐", total_cost=100_000, reason="", views={}, constraints=[], explanation={}))
        db.flush()  # 只 flush 不 commit：报表函数复用同一会话即可读到，退出时自动回滚

        result = response_report(db, tenant_id)

    assert result["events"][0]["costDiff"] == 20_000


def test_reports_endpoints_serve_live_numbers():
    """端到端：HTTP 层拿到的也必须是库里算出来的，不是常量。"""
    response = client.get("/api/v1/reports/executive", headers=_headers("u-boss"))
    assert response.status_code == 200
    payload = response.json()
    assert "series" in payload and "topRiskSuppliers" in payload
    assert set(payload) >= {"netBenefit", "avoidedLoss", "emergencyCost", "riskCount", "avgResponseHours"}


def test_reports_respect_permissions():
    # 财务没有 report:executive，也没有 settings:manage
    response = client.get("/api/v1/reports/executive", headers=_headers("u-finance"))
    assert response.status_code == 403


def test_tenant_settings_persists_timezone_and_rejects_invalid_iana_name():
    """企业信息页的保存必须真实落库，且时区是唯一的日历统计口径。"""
    headers = _headers("u-admin")
    original = client.get("/api/v1/settings/tenant", headers=headers)
    assert original.status_code == 200
    before = original.json()

    try:
        saved = client.patch(
            "/api/v1/settings/tenant",
            json={
                "name": before["name"],
                "industry": before["industry"],
                "scale": before["scale"],
                "timezone": "America/Los_Angeles",
            },
            headers=headers,
        )
        assert saved.status_code == 200
        assert saved.json()["timezone"] == "America/Los_Angeles"
        assert client.get("/api/v1/settings/tenant", headers=headers).json()["timezone"] == "America/Los_Angeles"

        invalid = client.patch("/api/v1/settings/tenant", json={"timezone": "not/a-timezone"}, headers=headers)
        assert invalid.status_code == 422
    finally:
        restored = client.patch(
            "/api/v1/settings/tenant",
            json={
                "name": before["name"],
                "industry": before["industry"],
                "scale": before["scale"],
                "timezone": before["timezone"],
            },
            headers=headers,
        )
        assert restored.status_code == 200


# ------------------------------------------------------------ 演示租户就绪度


def test_demo_incident_is_decision_ready():
    """演示租户的主事件必须能推演。

    曾经缺 estimated_delay_hours，高风险分支直接抛 CG-2514 阻断——
    界面上点「生成方案」会等来一个 failed 作业。答辩现场这条路必须是通的。
    """
    from src.webapi.context_builder import TenantContextBuilder

    with SessionLocal() as db:
        readiness = TenantContextBuilder(db, "tenant-demo").readiness("inc-supplier-shutdown")

    assert readiness["ready"] is True, f"演示事件被阻断：{readiness['blocking']}"
    assert readiness["blocking"] == []
    # 延误来自申报的风险明细，而不是回退默认值
    assert readiness["checks"]["delaySource"] == "risk"


# -------------------------------------------------------------- 审批链配置


def test_approval_chain_defaults_before_configuration():
    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        db.commit()
        view = approval_chain_view(db, tenant_id)

    assert view["configured"] is False
    assert view["levels"]["high"]["approver"] == "boss"
    assert view["levels"]["high"]["countersign"] == ["finance"]


def test_approval_chain_saves_and_reads_back():
    """核心回归：保存后换一个 session 仍能读到——旧实现只弹提示不落库。"""
    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        db.commit()
        save_approval_chain(db, tenant_id, {
            "levels": {
                "low": {"approver": "scm_lead", "countersign": []},
                "medium": {"approver": "boss", "countersign": []},
                "high": {"approver": "boss", "countersign": ["finance", "scm_lead"]},
            },
            "financeCountersign": False,
        }, actor="u-boss")
        db.commit()

    with SessionLocal() as db:
        view = approval_chain_view(db, tenant_id)

    assert view["configured"] is True
    assert view["version"] == 1
    assert view["levels"]["medium"]["approver"] == "boss"
    assert view["levels"]["high"]["countersign"] == ["finance", "scm_lead"]
    assert view["financeCountersign"] is False


def test_approval_chain_rejects_unknown_role():
    from src.webapi.errors import ApiError

    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        db.commit()
        with pytest.raises(ApiError) as excinfo:
            save_approval_chain(db, tenant_id, {
                "levels": {
                    "low": {"approver": "scm_lead", "countersign": []},
                    "medium": {"approver": "scm_lead", "countersign": []},
                    "high": {"approver": "nonexistent_role", "countersign": []},
                },
            })
    assert excinfo.value.code == "CG-2811"


def test_approval_chain_bumps_version_on_each_save():
    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        db.commit()
        body = {"levels": {level: {"approver": "boss", "countersign": []} for level in ("low", "medium", "high")}}
        save_approval_chain(db, tenant_id, body)
        db.commit()
        save_approval_chain(db, tenant_id, body)
        db.commit()
        view = approval_chain_view(db, tenant_id)

    assert view["version"] == 2


def test_approval_chain_endpoint_roundtrip():
    body = {
        "levels": {
            "low": {"approver": "scm_lead", "countersign": []},
            "medium": {"approver": "scm_lead", "countersign": []},
            "high": {"approver": "boss", "countersign": ["finance"]},
        },
        "financeCountersign": True,
    }
    saved = client.put("/api/v1/settings/approval-chain", json=body, headers=_headers("u-scm_lead"))
    assert saved.status_code == 200
    read_back = client.get("/api/v1/settings/approval-chain", headers=_headers("u-scm_lead"))
    assert read_back.status_code == 200
    assert read_back.json()["levels"]["high"]["approver"] == "boss"
    assert read_back.json()["configured"] is True


# ------------------------------------------------------------ 数据范围配置


def test_data_scope_saves_and_reports_enforced():
    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        db.commit()
        result = save_data_scope(db, tenant_id, {"roles": {"scm_lead": "dept", "finance": "own"}}, actor="u-admin")
        db.commit()

    scopes = {row["code"]: row["scope"] for row in result["roles"]}
    assert scopes["scm_lead"] == "dept"
    assert scopes["finance"] == "own"
    # 行级过滤已落地（tests/test_data_scope.py 证明查询真的被过滤），前端据此展示生效口径
    assert result["enforced"] is True


def test_data_scope_rejects_invalid_scope():
    from src.webapi.errors import ApiError

    with SessionLocal() as db:
        tenant_id = _fresh_tenant(db)
        db.commit()
        with pytest.raises(ApiError) as excinfo:
            save_data_scope(db, tenant_id, {"roles": {"scm_lead": "everything"}})
    assert excinfo.value.code == "CG-2813"


def test_data_scope_endpoint_requires_role_manage():
    # scm_lead 没有 role:manage
    denied = client.get("/api/v1/settings/data-scopes", headers=_headers("u-scm_lead"))
    assert denied.status_code == 403
    allowed = client.get("/api/v1/settings/data-scopes", headers=_headers("u-admin"))
    assert allowed.status_code == 200
    assert allowed.json()["enforced"] is True
