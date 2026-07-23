"""A03 步骤 4 验收：风险解释接口。

"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api import app
from src.webapi.auth.security import create_tokens
from src.webapi.context_builder import TenantContextBuilder
from src.webapi.database import SessionLocal
from src.webapi.models import InventoryEntity, Material, Risk, Role, Tenant, User
from src.webapi.risk_recompute import recompute_inventory_risks, risk_id_for_material
from src.webapi.seed import seed
from tests.test_phase5b_a03_risk_recompute import _scenario

seed()
client = TestClient(app)

FULL_PERMISSIONS = [
    "dashboard:view", "risk:view", "incident:view", "risk:manage", "risk:event:create",
    "decision:view", "field:cost:view", "field:profit:view", "field:customerLevel:view",
    "field:contract:view", "field:supplierPrice:view",
]
# buyer 口径：有 risk:view，但没有任何 field:*:view，用于验证脱敏。
LIMITED_PERMISSIONS = ["dashboard:view", "risk:view", "incident:view"]


def _tenant_user(db, tenant_id: str, suffix: str, permissions: list[str]) -> str:
    db.merge(Tenant(id=tenant_id, name=tenant_id, industry="制造", scale="small",
                    status="active", plan="trial", trial_end_at="", demo_data_flag=False))
    db.flush()
    role_id, user_id = f"role-{tenant_id}-{suffix}", f"user-{tenant_id}-{suffix}"
    # roles 对 (tenant_id, code) 唯一：同租户建多个测试用户时 code 必须各不相同。
    db.add(Role(id=role_id, tenant_id=tenant_id, code=f"scm_lead_{suffix}", name="供应链负责人",
                builtin=False, permissions=permissions))
    db.flush()
    db.add(User(id=user_id, tenant_id=tenant_id, account=f"{user_id}@a03.test",
                password_hash="x", name="A03 用户", phone="", email=f"{user_id}@a03.test",
                dept_id="d", role_id=role_id, role_code="scm_lead", status="active",
                data_scope="all"))
    db.commit()
    return user_id


def _headers_for(user_id: str) -> dict[str, str]:
    with SessionLocal() as db:
        return {"Authorization": f"Bearer {create_tokens(db.get(User, user_id))['token']}"}


def _prepare(permissions: list[str] | None = None, **scenario_kwargs) -> tuple[str, str, str, str]:
    """One tenant + user + triggering material + recomputed risk."""
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"tenant-a03x-{suffix}"
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix, **scenario_kwargs)
        user_id = _tenant_user(db, tenant_id, suffix, permissions or FULL_PERMISSIONS)
    with SessionLocal() as db:
        recompute_inventory_risks(db, tenant_id)
    return tenant_id, material_id, user_id, risk_id_for_material(tenant_id, material_id)


def _explain(risk_id: str, user_id: str):
    return client.get(f"/api/v1/risks/{risk_id}/explanation", headers=_headers_for(user_id))


# ── B3 / B4：阈值、当前值对比与配置来源 ────────────────────────────────────────


def test_b3_current_value_versus_threshold_is_explicit() -> None:
    _, _, user_id, risk_id = _prepare()
    body = _explain(risk_id, user_id).json()

    assert body["available"] is True
    verdict = body["verdict"]
    assert verdict["mode"] == "computed"
    assert verdict["shouldTriggerResponse"] is True
    assert verdict["riskIndex"] > verdict["triggerThreshold"]
    assert verdict["warningLevel"] == "红色预警"

    shortage = next(item for item in body["drivers"] if item["key"] == "shortage_urgency")
    assert shortage["currentValue"] == 15.0        # 300 / (480/24)
    assert shortage["threshold"] == {"yellow": 48, "red": 24}
    assert shortage["comparison"] == "below_red"


def test_b2_contributions_still_sum_to_index_through_the_api() -> None:
    _, _, user_id, risk_id = _prepare()
    body = _explain(risk_id, user_id).json()
    total = sum(item["contribution"] for item in body["drivers"])
    assert pytest.approx(total, abs=0.05) == body["verdict"]["riskIndex"]


def test_b4_threshold_source_is_labelled_expert_default_without_tenant_config() -> None:
    _, _, user_id, risk_id = _prepare()
    body = _explain(risk_id, user_id).json()
    assert body["verdict"]["thresholdSource"] == "expert_default"
    assert body["verdict"]["configurationItems"]["thresholds"]["fallback_reason"]


# ── B16：与 C1 决策链路同源 ───────────────────────────────────────────────────


def test_b16_trigger_threshold_matches_the_c1_configuration_path() -> None:
    tenant_id, material_id, user_id, risk_id = _prepare()
    body = _explain(risk_id, user_id).json()
    with SessionLocal() as db:
        snapshot = TenantContextBuilder(db, tenant_id).snapshot_for_material_id(material_id)
        expected = snapshot.thresholds["inventory_warning"]["inventory_risk_trigger"]
    assert body["verdict"]["triggerThreshold"] == expected
    assert body["decisionLink"]["materialId"] == material_id
    assert "derived_metrics.critical_order_exposure" in body["decisionLink"]["contextKeys"]


# ── B5：证据可追溯 ────────────────────────────────────────────────────────────


def test_b5_evidence_covers_four_entity_kinds_with_real_update_times() -> None:
    _, material_id, user_id, risk_id = _prepare()
    body = _explain(risk_id, user_id).json()
    kinds = {item["entity"] for item in body["evidence"]}
    assert kinds == {"material", "inventory", "supplier", "order"}

    material_evidence = next(item for item in body["evidence"] if item["entity"] == "material")
    assert material_evidence["id"] == material_id
    assert material_evidence["updatedAt"]
    assert material_evidence["link"].startswith("/data/material?id=")

    inventory_evidence = next(item for item in body["evidence"] if item["entity"] == "inventory")
    assert inventory_evidence["fields"]["onHandQty"] == 300
    assert inventory_evidence["fields"]["safetyStockQty"] == 960


def test_provenance_is_declared_as_resource_type_scope_not_row_lineage() -> None:
    _, _, user_id, risk_id = _prepare()
    body = _explain(risk_id, user_id).json()
    assert body["provenance"]["scope"] == "resource_type"
    assert "非本行血缘" in body["provenance"]["note"]
    # 本用例的实体是直接落库的，没有导入批次；必须如实说不知道，而不是编一个。
    assert body["provenance"]["batches"] == []
    assert set(body["provenance"]["unknownResources"]) == {"material", "inventory", "supplier", "order"}


# ── B6 / B7 / B8：数据不足降级，且响应里不出现任何编造数字 ────────────────────


@pytest.mark.parametrize(
    "kwargs, code",
    [({"with_inventory": False}, "CG-2513"), ({"daily_consumption": None}, "CG-2512")],
)
def test_b7_b8_insufficient_data_returns_renderable_limitation(kwargs: dict, code: str) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"tenant-a03x-{suffix}"
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix, **kwargs)
        user_id = _tenant_user(db, tenant_id, suffix, FULL_PERMISSIONS)
        risk_id = f"risk-manual-{suffix}"
        db.add(Risk(id=risk_id, tenant_id=tenant_id, code=f"R-{suffix}", level="medium",
                    type="库存", object_type="物料", object_name=material_id, score=0,
                    rule="人工登记", found_at="2026-07-19 10:00", status="new",
                    details={"material_id": material_id}))
        db.commit()

    response = _explain(risk_id, user_id)
    body = response.json()
    assert response.status_code == 200          # 可渲染的限制，不是报错弹窗
    assert body["available"] is False
    assert body["code"] == code
    assert body["message"]
    assert body["limitations"][0]["code"] == code
    assert body["verdict"] is None and body["drivers"] == [] and body["evidence"] == []


def test_b6_risk_without_a_resolvable_material_is_blocked_not_invented() -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"tenant-a03x-{suffix}"
    with SessionLocal() as db:
        _scenario(db, tenant_id, suffix)
        user_id = _tenant_user(db, tenant_id, suffix, FULL_PERMISSIONS)
        risk_id = f"risk-nomat-{suffix}"
        db.add(Risk(id=risk_id, tenant_id=tenant_id, code=f"RN-{suffix}", level="medium",
                    type="库存", object_type="物料", object_name="不存在的物料", score=0,
                    rule="人工登记", found_at="2026-07-19 10:00", status="new",
                    details={"material_id": "MAT-DOES-NOT-EXIST"}))
        db.commit()

    body = _explain(risk_id, user_id).json()
    assert body["available"] is False and body["code"] == "CG-2511"
    assert body["verdict"] is None


# ── B9：已消除/已忽略 → 快照，且标注为快照 ────────────────────────────────────


def test_b9_resolved_risk_returns_the_snapshot_and_says_so() -> None:
    tenant_id, material_id, user_id, risk_id = _prepare()
    with SessionLocal() as db:
        db.query(InventoryEntity).filter(
            InventoryEntity.tenant_id == tenant_id
        ).update({"on_hand_qty": 999_999, "available_qty": 999_999})
        db.commit()
        recompute_inventory_risks(db, tenant_id)

    body = _explain(risk_id, user_id).json()
    assert body["available"] is False
    assert body["code"] == "CG-A031"
    assert body["isSnapshot"] is True
    assert body["snapshot"]["shouldTriggerResponse"] is False
    assert "快照" in body["message"]


def test_ignored_risk_is_also_reported_as_a_snapshot() -> None:
    tenant_id, _, user_id, risk_id = _prepare()
    with SessionLocal() as db:
        db.get(Risk, risk_id).status = "ignored"
        db.commit()
    body = _explain(risk_id, user_id).json()
    assert body["available"] is False and body["code"] == "CG-A031"
    assert "忽略" in body["message"]


# ── B10：估算值必须自曝 ───────────────────────────────────────────────────────


def test_b10_estimated_order_financials_are_disclosed_in_limitations() -> None:
    _, _, user_id, risk_id = _prepare()
    body = _explain(risk_id, user_id).json()
    codes = {item["code"] for item in body["limitations"]}
    # 场景里订单的 gross_profit / penalty_cost 是 None，必须自曝为估算。
    assert "estimated_order_financials" in codes
    message = next(item["message"] for item in body["limitations"]
                   if item["code"] == "estimated_order_financials")
    assert "估算" in message


# ── B11：跨租户隔离 ───────────────────────────────────────────────────────────


def test_b11_cross_tenant_explanation_is_404_and_leaks_nothing() -> None:
    tenant_a, material_a, _, risk_a = _prepare()
    suffix_b = uuid.uuid4().hex[:8]
    tenant_b = f"tenant-a03x-{suffix_b}"
    with SessionLocal() as db:
        _scenario(db, tenant_b, suffix_b)
        user_b = _tenant_user(db, tenant_b, suffix_b, FULL_PERMISSIONS)

    response = _explain(risk_a, user_b)
    assert response.status_code == 404
    # 整个响应体做子串断言：A 的物料名、仓库名、供应商名一个字都不能出现。
    raw = response.text
    with SessionLocal() as db:
        material = db.scalar(
            select(Material).where(
                Material.tenant_id == tenant_a, Material.material_id == material_a
            )
        )
    assert material is not None
    assert material_a not in raw
    assert material.material_name not in raw
    assert "一仓" not in raw and "A03供应商" not in raw


# ── B13：脱敏复用既有路径 ────────────────────────────────────────────────────


def test_b13_requester_without_field_permissions_sees_masked_money() -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"tenant-a03x-{suffix}"
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        full_user = _tenant_user(db, tenant_id, f"{suffix}-full", FULL_PERMISSIONS)
        limited_user = _tenant_user(db, tenant_id, f"{suffix}-lim", LIMITED_PERMISSIONS)
    with SessionLocal() as db:
        recompute_inventory_risks(db, tenant_id)
    risk_id = risk_id_for_material(tenant_id, material_id)

    full = _explain(risk_id, full_user).json()
    limited = _explain(risk_id, limited_user).json()

    full_order = next(item for item in full["evidence"] if item["entity"] == "order")
    limited_order = next(item for item in limited["evidence"] if item["entity"] == "order")
    assert full_order["fields"]["orderAmount"] == 1_800_000
    assert limited_order["fields"]["orderAmount"] == "***"
    assert limited_order["fields"]["penaltyCost"] == "***"
    assert limited_order["fields"]["grossProfit"] == "***"
    # 无 field:supplierPrice:view 时供应商报价同样不得泄露原值。
    limited_supplier = next(item for item in limited["evidence"] if item["entity"] == "supplier")
    assert limited_supplier["fields"]["supplierPrice"] == "***"
    assert "1800000" not in json.dumps(limited, ensure_ascii=False)


# ── B14：权限门槛 ────────────────────────────────────────────────────────────


def test_b14_explanation_requires_risk_view() -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"tenant-a03x-{suffix}"
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        blind_user = _tenant_user(db, tenant_id, suffix, ["dashboard:view"])
    with SessionLocal() as db:
        recompute_inventory_risks(db, tenant_id)
    response = _explain(risk_id_for_material(tenant_id, material_id), blind_user)
    assert response.status_code == 403


def test_recompute_still_requires_risk_manage_while_explanation_only_needs_view() -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"tenant-a03x-{suffix}"
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        viewer = _tenant_user(db, tenant_id, suffix, LIMITED_PERMISSIONS)
    with SessionLocal() as db:
        recompute_inventory_risks(db, tenant_id)

    assert client.post("/api/v1/risks/recompute", headers=_headers_for(viewer)).status_code == 403
    assert _explain(risk_id_for_material(tenant_id, material_id), viewer).status_code == 200


# ── B24：外部录入风险的解释形态 ──────────────────────────────────────────────


def test_b24_external_event_risk_is_labelled_not_fabricated() -> None:
    with SessionLocal() as db:
        headers = {"Authorization": f"Bearer {create_tokens(db.get(User, 'u-scm_lead'))['token']}"}
    body = client.get("/api/v1/risks/risk-1/explanation", headers=headers).json()

    assert body["available"] is True
    verdict = body["verdict"]
    assert verdict["mode"] == "declared"
    assert verdict["scoreSource"] == "declared_by_reporter"
    assert verdict["reportedChannel"] == "供应商电话通知"
    # 不得出现"由指标算出等级"那一套：computed 专有字段一个都不能有。
    assert "riskIndex" not in verdict and "triggerThreshold" not in verdict
    codes = {item["code"] for item in body["limitations"]}
    assert "CG-A034" in codes
    # 但"它驱动了什么"是真算的。
    assert body["drivenImpact"]["materialId"] == "MCU-A9"
    assert body["drivenImpact"]["riskIndex"] > 0


def test_demo_computed_risk_explains_with_real_entities() -> None:
    with SessionLocal() as db:
        headers = {"Authorization": f"Bearer {create_tokens(db.get(User, 'u-scm_lead'))['token']}"}
    risk_id = risk_id_for_material("tenant-demo", "MCU-A9")
    body = client.get(f"/api/v1/risks/{risk_id}/explanation", headers=headers).json()

    assert body["available"] is True
    assert body["verdict"]["mode"] == "computed"
    assert any(item["name"] == "上海一仓" for item in body["evidence"])
    assert body["verdict"]["narrative"], "叙述来自引擎 explanation[]，不得为空"
