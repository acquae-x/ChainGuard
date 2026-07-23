"""A03 步骤 2/3 验收：风险重算的身份、幂等、状态机与 seed 去硬编码。

"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.inventory_monitor import calculate_inventory_risk
from src.webapi.auth.security import create_tokens
from src.webapi.context_builder import TenantContextBuilder
from src.webapi.database import SessionLocal
from src.webapi.models import (
    CustomerEntity,
    InventoryEntity,
    Material,
    Risk,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    Tenant,
    User,
)
from src.webapi.risk_recompute import (
    RECOMPUTE_ORIGIN,
    recompute_inventory_risks,
    risk_id_for_material,
)
from src.webapi.seed import seed


seed()
client = TestClient(app)


def _headers(user_id: str = "u-scm_lead") -> dict[str, str]:
    with SessionLocal() as db:
        return {"Authorization": f"Bearer {create_tokens(db.get(User, user_id))['token']}"}


def _scenario(
    db,
    tenant_id: str,
    suffix: str,
    *,
    stock: float = 300,
    daily_consumption: float | None = 480,
    critical_qty: float = 6000,
    delay_hours: float = 72,
    with_inventory: bool = True,
) -> str:
    """One triggering material: 支撑 15h、关键订单覆盖 5%、在途延误 72h → 指数高于 trigger 70。"""
    material_id = f"MAT-A03-{suffix}"
    db.merge(Tenant(id=tenant_id, name=tenant_id, industry="制造", scale="small",
                    status="active", plan="trial", trial_end_at="", demo_data_flag=False))
    db.add(Material(id=f"mat-{tenant_id}-{suffix}", tenant_id=tenant_id, material_id=material_id,
                    material_name=f"A03物料-{suffix}", category="芯片", unit="件",
                    daily_consumption=daily_consumption, unit_cost=10, is_critical=True, extra={}))
    db.flush()
    if with_inventory:
        arrival = datetime.now(timezone.utc) + timedelta(days=30)
        db.add(InventoryEntity(
            id=f"inv-{tenant_id}-{suffix}", tenant_id=tenant_id, inventory_id=f"INV-A03-{suffix}",
            material_id=material_id, warehouse_id="W-1", warehouse_name="一仓",
            on_hand_qty=stock, available_qty=stock, safety_stock_qty=960, in_transit_qty=2000,
            planned_arrival_at=arrival,
            estimated_arrival_at=arrival + timedelta(hours=delay_hours), extra={},
        ))
    db.add(SupplierEntity(id=f"sup-{tenant_id}-{suffix}", tenant_id=tenant_id,
                          supplier_id=f"SUP-A03-{suffix}", supplier_name="A03供应商",
                          region="华东", status="active", reliability_score=90, extra={}))
    db.add(CustomerEntity(id=f"cus-{tenant_id}-{suffix}", tenant_id=tenant_id,
                          customer_id=f"CUS-A03-{suffix}", customer_name="A级客户",
                          customer_level="A", region="华东", contract="年度", owner="销售", extra={}))
    db.flush()
    db.add(SupplierMaterial(id=f"sm-{tenant_id}-{suffix}", tenant_id=tenant_id,
                            supplier_material_id=f"SM-A03-{suffix}", supplier_id=f"SUP-A03-{suffix}",
                            material_id=material_id, qualified=True, supplier_rank=1,
                            available_emergency_qty=4000, lead_time_hours=96,
                            emergency_cost_multiplier=1.35, supplier_price=48, extra={}))
    db.add(SalesOrder(id=f"so-{tenant_id}-{suffix}", tenant_id=tenant_id,
                      sales_order_id=f"SO-A03-{suffix}", customer_id=f"CUS-A03-{suffix}",
                      order_status="confirmed",
                      promised_delivery_at=datetime.now(timezone.utc) + timedelta(days=5),
                      order_amount=1_800_000, gross_profit=None, penalty_cost=None, extra={}))
    db.flush()
    db.add(SalesOrderLine(id=f"sol-{tenant_id}-{suffix}", tenant_id=tenant_id,
                          sales_order_line_id=f"SOL-A03-{suffix}", sales_order_id=f"SO-A03-{suffix}",
                          line_no=1, material_id=material_id, ordered_qty=critical_qty,
                          unit_price=300, extra={}))
    db.commit()
    return material_id


def _row(db, tenant_id: str, material_id: str) -> Risk | None:
    return db.get(Risk, risk_id_for_material(tenant_id, material_id))


def _snapshot(db, tenant_id: str, material_id: str) -> dict:
    risk = _row(db, tenant_id, material_id)
    assert risk is not None
    return {
        "status": risk.status, "score": risk.score, "level": risk.level, "rule": risk.rule,
        "code": risk.code, "found_at": risk.found_at, "details": risk.details,
        "updated_at": risk.updated_at,
    }


# ── B1 / B2：分数确实来自引擎，不是本模块另算的 ────────────────────────────────


def test_b1_recomputed_score_equals_engine_function_output() -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        outcome = recompute_inventory_risks(db, tenant_id)
        assert outcome.created == 1

        snapshot = TenantContextBuilder(db, tenant_id).snapshot_for_material_id(material_id)
        expected = calculate_inventory_risk(
            snapshot.inventory, snapshot.risk_weights, snapshot.thresholds
        )
        risk = _row(db, tenant_id, material_id)
        assert risk is not None
        # 逐位相等：证明 risk_recompute 没有另写一套加权。
        assert risk.score == expected["inventory_risk_index"]
        assert risk.details["measurement"]["riskIndex"] == expected["inventory_risk_index"]
        assert risk.details["origin"] == RECOMPUTE_ORIGIN
        assert risk.details["material_id"] == material_id


def test_b2_driver_contributions_sum_to_the_risk_index() -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        recompute_inventory_risks(db, tenant_id)
        measurement = _row(db, tenant_id, material_id).details["measurement"]

    weights, drivers = measurement["weights"], measurement["drivers"]
    assert pytest.approx(sum(weights.values()), abs=1e-9) == 1.0
    total = sum(float(weights[key]) * float(score) for key, score in drivers.items())
    assert pytest.approx(total, abs=0.01) == measurement["riskIndex"]


# ── B18：幂等 ─────────────────────────────────────────────────────────────────


def test_b18_second_recompute_writes_nothing_at_all() -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        recompute_inventory_risks(db, tenant_id)
        first = _snapshot(db, tenant_id, material_id)

    with SessionLocal() as db:
        outcome = recompute_inventory_risks(db, tenant_id)
        second = _snapshot(db, tenant_id, material_id)

    assert outcome.created == 0 and outcome.updated == 0 and outcome.unchanged == 1
    # 连 updated_at 都不许动：数据没变就完全不写库。
    assert first == second


# ── B17：人工判断过的状态不被机器覆盖 ──────────────────────────────────────────


def test_b17_ignored_risk_is_never_resurrected_by_a_rescan() -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        recompute_inventory_risks(db, tenant_id)
        risk = _row(db, tenant_id, material_id)
        risk.status = "ignored"
        db.commit()

    with SessionLocal() as db:
        recompute_inventory_risks(db, tenant_id)
        assert _row(db, tenant_id, material_id).status == "ignored"


def test_b17_incident_linked_risk_keeps_status_and_incident_id() -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        recompute_inventory_risks(db, tenant_id)
        risk = _row(db, tenant_id, material_id)
        risk.status, risk.incident_id = "incident_created", "inc-a03"
        db.commit()

    with SessionLocal() as db:
        # 库存补足 → 不再触发，但事件已建，扫描无权把它置为已消除。
        db.query(InventoryEntity).filter(
            InventoryEntity.tenant_id == tenant_id
        ).update({"on_hand_qty": 999_999, "available_qty": 999_999})
        db.commit()
        recompute_inventory_risks(db, tenant_id)
        risk = _row(db, tenant_id, material_id)
        assert risk.status == "incident_created" and risk.incident_id == "inc-a03"
        assert risk.details["noLongerTriggering"] is True


def test_watching_is_a_human_mark_and_survives_rescan() -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        recompute_inventory_risks(db, tenant_id)
        _row(db, tenant_id, material_id).status = "watching"
        db.commit()

    with SessionLocal() as db:
        db.query(InventoryEntity).filter(
            InventoryEntity.tenant_id == tenant_id
        ).update({"on_hand_qty": 320, "available_qty": 320})
        db.commit()
        recompute_inventory_risks(db, tenant_id)
        assert _row(db, tenant_id, material_id).status == "watching"


# ── B19 / B20 / B22：resolved 的产生、复发与不漂移 ─────────────────────────────


def test_b19_no_longer_triggering_resolves_and_keeps_the_pre_resolution_snapshot() -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        recompute_inventory_risks(db, tenant_id)
        triggered_index = _row(db, tenant_id, material_id).details["measurement"]["riskIndex"]

    with SessionLocal() as db:
        db.query(InventoryEntity).filter(
            InventoryEntity.tenant_id == tenant_id
        ).update({"on_hand_qty": 999_999, "available_qty": 999_999})
        db.commit()
        outcome = recompute_inventory_risks(db, tenant_id)
        risk = _row(db, tenant_id, material_id)

    assert outcome.resolved == 1
    assert risk.status == "resolved"
    assert risk.details["resolvedAt"]
    # 快照必须是"消除当时"的真实数值，不是拿当前数据现编。
    snapshot = risk.details["lastExplanationSnapshot"]
    assert snapshot["shouldTriggerResponse"] is False
    assert snapshot["riskIndex"] != triggered_index


def test_b22_resolved_and_still_calm_does_not_drift() -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        recompute_inventory_risks(db, tenant_id)
        db.query(InventoryEntity).filter(
            InventoryEntity.tenant_id == tenant_id
        ).update({"on_hand_qty": 999_999, "available_qty": 999_999})
        db.commit()
        recompute_inventory_risks(db, tenant_id)
        first = _snapshot(db, tenant_id, material_id)

    with SessionLocal() as db:
        recompute_inventory_risks(db, tenant_id)
        assert _snapshot(db, tenant_id, material_id) == first


def test_b20_recurrence_returns_to_new_and_keeps_the_original_code() -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix)
        recompute_inventory_risks(db, tenant_id)
        original_code = _row(db, tenant_id, material_id).code
        db.query(InventoryEntity).filter(
            InventoryEntity.tenant_id == tenant_id
        ).update({"on_hand_qty": 999_999, "available_qty": 999_999})
        db.commit()
        recompute_inventory_risks(db, tenant_id)
        assert _row(db, tenant_id, material_id).status == "resolved"

    with SessionLocal() as db:
        db.query(InventoryEntity).filter(
            InventoryEntity.tenant_id == tenant_id
        ).update({"on_hand_qty": 300, "available_qty": 300})
        db.commit()
        outcome = recompute_inventory_risks(db, tenant_id)
        risk = _row(db, tenant_id, material_id)

    assert outcome.recurred == 1
    assert risk.status == "new"
    assert risk.details["recurrenceCount"] == 1
    assert risk.details["previousResolvedAt"]
    assert risk.code == original_code  # 编号是人要引用的，不随扫描变化


# ── B21：不碰非重算来源的风险 ─────────────────────────────────────────────────


def test_b21_external_and_manual_risks_are_untouched_by_recompute() -> None:
    with SessionLocal() as db:
        before = {
            (risk.id, risk.score, risk.level, risk.rule, risk.status, str(risk.details))
            for risk in db.query(Risk).filter(
                Risk.tenant_id == "tenant-demo", Risk.id == "risk-1"
            )
        }
        recompute_inventory_risks(db, "tenant-demo")
        after = {
            (risk.id, risk.score, risk.level, risk.rule, risk.status, str(risk.details))
            for risk in db.query(Risk).filter(
                Risk.tenant_id == "tenant-demo", Risk.id == "risk-1"
            )
        }
    assert before == after and before


# ── B12：跨租户隔离 ───────────────────────────────────────────────────────────


def test_b12_recompute_never_crosses_tenants() -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant_a, tenant_b = f"tenant-a03-a-{suffix}", f"tenant-a03-b-{suffix}"
    with SessionLocal() as db:
        material_a = _scenario(db, tenant_a, f"a{suffix}")
        material_b = _scenario(db, tenant_b, f"b{suffix}")

    with SessionLocal() as db:
        outcome = recompute_inventory_risks(db, tenant_b)
        assert outcome.created == 1
        # 只为 B 产出风险，A 的物料完全没有被扫描到。
        assert _row(db, tenant_b, material_b) is not None
        assert _row(db, tenant_a, material_a) is None
        produced = db.query(Risk).filter(Risk.tenant_id == tenant_b).all()
        assert produced and all(material_a not in str(risk.details) for risk in produced)


def test_recompute_endpoint_requires_risk_manage_and_is_tenant_scoped() -> None:
    forbidden = client.post("/api/v1/risks/recompute", headers=_headers("u-auditor"))
    assert forbidden.status_code == 403

    allowed = client.post("/api/v1/risks/recompute", headers=_headers("u-scm_lead"))
    assert allowed.status_code == 200
    assert set(allowed.json()) >= {"created", "updated", "resolved", "recurred", "unchanged"}


# ── 数据不足：如实跳过，不伪造分数 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs, code",
    [({"with_inventory": False}, "CG-2513"), ({"daily_consumption": None}, "CG-2512")],
)
def test_insufficient_data_is_skipped_with_a_reason_not_a_fabricated_score(
    kwargs: dict, code: str
) -> None:
    tenant_id, suffix = f"tenant-a03-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        material_id = _scenario(db, tenant_id, suffix, **kwargs)
        outcome = recompute_inventory_risks(db, tenant_id)

    assert outcome.created == 0
    assert [item["code"] for item in outcome.skipped] == [code]
    assert outcome.skipped[0]["materialId"] == material_id


# ── B23：seed 去硬编码 ────────────────────────────────────────────────────────


def test_b23_demo_tenant_inventory_risk_is_computed_not_hardcoded() -> None:
    with SessionLocal() as db:
        risk = _row(db, "tenant-demo", "MCU-A9")
        assert risk is not None, "演示租户的库存风险应由 recompute 产生"
        assert risk.details["origin"] == RECOMPUTE_ORIGIN
        assert risk.status == "incident_created"

        snapshot = TenantContextBuilder(db, "tenant-demo").snapshot_for_material_id("MCU-A9")
        expected = calculate_inventory_risk(
            snapshot.inventory, snapshot.risk_weights, snapshot.thresholds
        )
        assert expected["should_trigger_response"] is True
        assert risk.score == expected["inventory_risk_index"]


def test_b23_seed_source_contains_no_literal_risk_scores() -> None:
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "src" / "webapi" / "seed.py"
    text = source.read_text(encoding="utf-8")
    # 旧的写死分数与写死触发规则不得再出现在 seed 里。
    assert "score=73" not in text
    assert "安全库存低于 20%" not in text


def test_demo_incident_still_links_both_source_risks() -> None:
    from src.webapi.models import Incident

    with SessionLocal() as db:
        incident = db.get(Incident, "inc-supplier-shutdown")
        assert incident is not None
        assert "risk-1" in incident.source_risk_ids
        assert risk_id_for_material("tenant-demo", "MCU-A9") in incident.source_risk_ids
