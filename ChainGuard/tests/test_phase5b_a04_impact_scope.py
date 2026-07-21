"""A04 影响范围完整版验收。

对位 codex_landing_spec/phase5b_a04_实现范围.md §3.1 的 B1–B21。

贯穿全篇的一条纪律：每个断言都指向**真实实体行**或**真实外键**。
没有任何一处允许"看起来对"的模糊匹配，也没有任何一处允许伪造的影响结论。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.webapi.auth.security import create_tokens
from src.webapi.database import SessionLocal
from src.webapi.impact_scope import MAX_ITEMS_PER_TYPE, ImpactScopeBuilder
from src.webapi.models import (
    CustomerEntity,
    Incident,
    InventoryEntity,
    Material,
    Risk,
    Role,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    Task,
    Tenant,
    User,
)
from src.webapi.risk_recompute import RECOMPUTE_ORIGIN
from src.webapi.seed import seed

seed()
client = TestClient(app)

FULL_PERMISSIONS = [
    "dashboard:view", "risk:view", "incident:view", "risk:manage", "decision:view",
    "field:cost:view", "field:profit:view", "field:customerLevel:view",
    "field:contract:view", "field:supplierPrice:view",
]
BUYER_PERMISSIONS = ["dashboard:view", "risk:view", "incident:view"]


# ── 夹具 ──────────────────────────────────────────────────────────────────────


def _tenant(db, tenant_id: str) -> None:
    db.merge(Tenant(id=tenant_id, name=tenant_id, industry="制造", scale="small",
                    status="active", plan="trial", trial_end_at="", demo_data_flag=False))
    db.flush()


def _account(db, tenant_id: str, suffix: str, permissions: list[str]) -> str:
    role_id, user_id = f"role-a04-{suffix}", f"user-a04-{suffix}"
    db.add(Role(id=role_id, tenant_id=tenant_id, code=f"a04_{suffix}", name="A04测试角色",
                builtin=False, permissions=permissions))
    db.flush()
    db.add(User(id=user_id, tenant_id=tenant_id, account=f"a04-{suffix}@test",
                password_hash="x", name="A04测试用户", phone="", email="", dept_id="dept-1",
                role_id=role_id, role_code=f"a04_{suffix}", status="active", data_scope="all",
                must_change_password=False))
    db.flush()
    return user_id


def _headers(user_id: str) -> dict[str, str]:
    with SessionLocal() as db:
        return {"Authorization": f"Bearer {create_tokens(db.get(User, user_id))['token']}"}


def _graph(
    db,
    tenant_id: str,
    suffix: str,
    *,
    with_inventory: bool = True,
    with_supplier: bool = True,
    with_order: bool = True,
    with_sibling_material: bool = True,
    second_warehouse: bool = True,
    closed_order: bool = True,
) -> dict[str, str]:
    """一张可控的真实实体图谱。

    物料 M ─ 库存×2（两个仓库）─ 供应商 S ─ 兄弟物料 M2（同供应商）
            └ 订单 O（未关闭）─ 客户 C
            └ 订单 OC（已交付，应被排除）
    """
    material_id = f"MAT-A04-{suffix}"
    sibling_id = f"MAT-A04-SIB-{suffix}"
    supplier_id = f"SUP-A04-{suffix}"
    customer_id = f"CUS-A04-{suffix}"
    order_id = f"SO-A04-{suffix}"
    closed_id = f"SO-A04-CLOSED-{suffix}"

    _tenant(db, tenant_id)
    db.add(Material(id=f"mat-{tenant_id}-{suffix}", tenant_id=tenant_id, material_id=material_id,
                    material_name=f"A04主控芯片-{suffix}", category="芯片", unit="件",
                    daily_consumption=480, unit_cost=10, is_critical=True, extra={}))
    if with_sibling_material:
        db.add(Material(id=f"mat-sib-{tenant_id}-{suffix}", tenant_id=tenant_id,
                        material_id=sibling_id, material_name=f"A04电源模块-{suffix}",
                        category="模块", unit="件", daily_consumption=120, unit_cost=8,
                        is_critical=False, extra={}))
    db.flush()

    if with_inventory:
        arrival = datetime.now(timezone.utc) + timedelta(days=30)
        db.add(InventoryEntity(
            id=f"inv1-{tenant_id}-{suffix}", tenant_id=tenant_id, inventory_id=f"INV-A04-1-{suffix}",
            material_id=material_id, warehouse_id=f"WH-A04-1-{suffix}", warehouse_name="A04上海一仓",
            on_hand_qty=300, available_qty=300, safety_stock_qty=960, in_transit_qty=2000,
            planned_arrival_at=arrival, estimated_arrival_at=arrival + timedelta(hours=72), extra={}))
        # 同一仓库的第二条库存行：仓库分组必须去重成 1 条
        db.add(InventoryEntity(
            id=f"inv1b-{tenant_id}-{suffix}", tenant_id=tenant_id, inventory_id=f"INV-A04-1B-{suffix}",
            material_id=material_id, warehouse_id=f"WH-A04-1-{suffix}", warehouse_name="A04上海一仓",
            on_hand_qty=40, available_qty=40, safety_stock_qty=100, in_transit_qty=0, extra={}))
        if second_warehouse:
            db.add(InventoryEntity(
                id=f"inv2-{tenant_id}-{suffix}", tenant_id=tenant_id,
                inventory_id=f"INV-A04-2-{suffix}", material_id=material_id,
                warehouse_id=f"WH-A04-2-{suffix}", warehouse_name="A04苏州二仓",
                on_hand_qty=120, available_qty=120, safety_stock_qty=200, in_transit_qty=0, extra={}))

    if with_supplier:
        db.add(SupplierEntity(id=f"sup-{tenant_id}-{suffix}", tenant_id=tenant_id,
                              supplier_id=supplier_id, supplier_name=f"A04封测厂-{suffix}",
                              region="江苏", status="停产", reliability_score=62, extra={}))
    if with_order:
        db.add(CustomerEntity(id=f"cus-{tenant_id}-{suffix}", tenant_id=tenant_id,
                              customer_id=customer_id, customer_name=f"A04整机客户-{suffix}",
                              customer_level="A", region="华东", contract="年度框架",
                              owner="销售一部", extra={}))
    db.flush()

    if with_supplier:
        db.add(SupplierMaterial(
            id=f"sm-{tenant_id}-{suffix}", tenant_id=tenant_id,
            supplier_material_id=f"SM-A04-{suffix}", supplier_id=supplier_id,
            material_id=material_id, qualified=True, supplier_rank=1,
            available_emergency_qty=4000, lead_time_hours=96,
            emergency_cost_multiplier=1.35, supplier_price=48, extra={}))
        if with_sibling_material:
            db.add(SupplierMaterial(
                id=f"sm-sib-{tenant_id}-{suffix}", tenant_id=tenant_id,
                supplier_material_id=f"SM-A04-SIB-{suffix}", supplier_id=supplier_id,
                material_id=sibling_id, qualified=True, supplier_rank=2,
                available_emergency_qty=1000, lead_time_hours=120,
                emergency_cost_multiplier=1.2, supplier_price=15, extra={}))

    if with_order:
        db.add(SalesOrder(id=f"so-{tenant_id}-{suffix}", tenant_id=tenant_id,
                          sales_order_id=order_id, customer_id=customer_id,
                          order_status="confirmed",
                          promised_delivery_at=datetime.now(timezone.utc) + timedelta(days=5),
                          order_amount=1_800_000, gross_profit=420_000, penalty_cost=180_000,
                          extra={}))
        if closed_order:
            db.add(SalesOrder(id=f"soc-{tenant_id}-{suffix}", tenant_id=tenant_id,
                              sales_order_id=closed_id, customer_id=customer_id,
                              order_status="delivered",
                              promised_delivery_at=datetime.now(timezone.utc) - timedelta(days=5),
                              order_amount=900_000, gross_profit=200_000, penalty_cost=0, extra={}))
        db.flush()
        db.add(SalesOrderLine(id=f"sol-{tenant_id}-{suffix}", tenant_id=tenant_id,
                              sales_order_line_id=f"SOL-A04-{suffix}", sales_order_id=order_id,
                              line_no=1, material_id=material_id, ordered_qty=6000,
                              unit_price=300, extra={}))
        if closed_order:
            db.add(SalesOrderLine(id=f"solc-{tenant_id}-{suffix}", tenant_id=tenant_id,
                                  sales_order_line_id=f"SOLC-A04-{suffix}",
                                  sales_order_id=closed_id, line_no=1, material_id=material_id,
                                  ordered_qty=1000, unit_price=300, extra={}))
    db.commit()
    return {
        "material": material_id, "sibling": sibling_id, "supplier": supplier_id,
        "customer": customer_id, "order": order_id, "closedOrder": closed_id,
        "warehouse1": f"WH-A04-1-{suffix}", "warehouse2": f"WH-A04-2-{suffix}",
    }


def _risk(db, tenant_id: str, suffix: str, details: dict, *, incident_id: str | None = None) -> str:
    risk_id = f"risk-a04-{suffix}"
    db.add(Risk(id=risk_id, tenant_id=tenant_id, code=f"RISK-A04-{suffix}", level="high",
                type="库存", object_type="物料", object_name=f"A04主控芯片-{suffix}", score=78.0,
                rule="A04 测试风险", found_at="2026-07-19 09:00", status="new",
                details={"origin": RECOMPUTE_ORIGIN, **details}, incident_id=incident_id))
    db.commit()
    return risk_id


def _group(payload: dict, entity_type: str) -> dict:
    return next(g for g in payload["groups"] if g["entityType"] == entity_type)


def _ids(payload: dict, entity_type: str) -> set[str]:
    return {item["id"] for item in _group(payload, entity_type)["items"]}


def _item(payload: dict, entity_type: str, entity_id: str) -> dict:
    return next(item for item in _group(payload, entity_type)["items"] if item["id"] == entity_id)


def _codes(payload: dict) -> set[str]:
    return {item["code"] for item in payload["limitations"]}


def _scope(tenant_id: str, risk_id: str) -> dict:
    with SessionLocal() as db:
        return ImpactScopeBuilder(db, tenant_id).for_risk(db.get(Risk, risk_id))


# ── B1：直接影响完整 ──────────────────────────────────────────────────────────


def test_b1_direct_impact_covers_inventory_supplier_and_orders() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    assert payload["available"] is True
    # 三条库存行、两个仓库、一个供应商、一张未关闭订单——全部是真实实体行数
    assert _group(payload, "inventory")["total"] == 3
    assert _group(payload, "supplier")["total"] == 1
    assert _group(payload, "order")["total"] == 1
    assert keys["supplier"] in _ids(payload, "supplier")
    assert keys["order"] in _ids(payload, "order")
    for entity_type in ("inventory", "supplier", "order"):
        for item in _group(payload, entity_type)["items"]:
            assert item["degree"] == "direct"


def test_b1b_every_group_is_present_even_when_empty() -> None:
    """空分组必须显式出现并说明原因，不能靠分组消失来暗示"暂无数据"。"""
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix, with_order=False)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    assert [g["entityType"] for g in payload["groups"]] == [
        "material", "inventory", "warehouse", "supplier", "order", "customer", "task",
    ]
    assert _group(payload, "order")["total"] == 0
    assert _group(payload, "order")["emptyReason"]
    assert _group(payload, "customer")["emptyReason"]


# ── B2 / B3：间接影响 ─────────────────────────────────────────────────────────


def test_b2_customer_is_indirect_via_the_order() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    customer = _item(payload, "customer", keys["customer"])
    assert customer["degree"] == "indirect"
    assert customer["relation"]["code"] == "order_customer"
    assert customer["relation"]["via"] == "sales_orders"
    # 关系路径必须真的经过那张订单，而不是"反正它是个客户"
    assert f"order:{keys['order']}" in customer["relation"]["path"]


def test_b3_sibling_material_is_indirect_via_shared_supplier() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    sibling = _item(payload, "material", keys["sibling"])
    assert sibling["degree"] == "indirect"
    assert sibling["relation"]["code"] == "shared_supplier"
    assert sibling["relation"]["via"] == "supplier_materials"
    assert f"supplier:{keys['supplier']}" in sibling["relation"]["path"]
    # 起点物料自身仍是 direct，没有被第二跳降级
    assert _item(payload, "material", keys["material"])["degree"] == "direct"


# ── B4 / B5：去重与 degree 归属 ───────────────────────────────────────────────


def test_b4_one_supplier_serving_two_materials_appears_once() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        # 起点同时指向两个物料，它们共用同一个供应商
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
        db.add(SalesOrderLine(id=f"sol2-{tenant_id}-{suffix}", tenant_id=tenant_id,
                              sales_order_line_id=f"SOL2-A04-{suffix}",
                              sales_order_id=keys["order"], line_no=2,
                              material_id=keys["sibling"], ordered_qty=500,
                              unit_price=20, extra={}))
        db.commit()
    payload = _scope(tenant_id, risk_id)

    assert payload["summary"]["byType"]["supplier"] == 1
    assert payload["summary"]["byType"]["order"] == 1   # 同一张订单两行 → 订单去重成 1


def test_b5_direct_wins_over_indirect_for_the_same_entity() -> None:
    """同时被直接与间接命中的实体，degree 必须是 direct——只降不升。"""
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        # 起点同时给出主物料与兄弟物料：兄弟物料既是起点(direct)，又能经共用供应商被间接命中
        risk_id = _risk(db, tenant_id, suffix, {
            "material_id": keys["material"], "affected_material_id": keys["sibling"],
        })
    payload = _scope(tenant_id, risk_id)

    assert _item(payload, "material", keys["sibling"])["degree"] == "direct"
    assert _group(payload, "material")["total"] == 2   # 仍然只有两条，没有重复


# ── B6：仓库聚合 ──────────────────────────────────────────────────────────────


def test_b6_warehouses_are_deduped_and_declared_as_aggregated() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    # 三条库存行 → 两个仓库（一仓有两行）
    assert _group(payload, "warehouse")["total"] == 2
    assert _ids(payload, "warehouse") == {keys["warehouse1"], keys["warehouse2"]}
    # 系统没有仓库主数据这件事必须说出来，不能让人以为仓库是一等实体
    assert "CG-A042" in _codes(payload)
    assert _item(payload, "warehouse", keys["warehouse1"])["source"]["table"] == "inventory"


def test_b6b_single_warehouse_inventory_dedupes_to_one() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix, second_warehouse=False)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    assert _group(payload, "inventory")["total"] == 2
    assert _group(payload, "warehouse")["total"] == 1


# ── B7：任务 ──────────────────────────────────────────────────────────────────


def test_b7_incident_scope_includes_its_tasks() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    incident_id = f"inc-a04-{suffix}"
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]},
                        incident_id=incident_id)
        db.add(Incident(id=incident_id, tenant_id=tenant_id, code=f"INC-A04-{suffix}",
                        title="A04 影响范围事件", type="supplier_shutdown", level="high",
                        status="pending", owner="scm", source_risk_ids=[risk_id],
                        loss=0, cost=0, notes=[]))
        db.add(Task(id=f"task-a04-{suffix}", tenant_id=tenant_id, title="锁定替代供应商订单",
                    source=f"INC-A04-{suffix}", incident_id=incident_id, assignee="u-buyer",
                    role_code="buyer", status="pending", due_at="", priority="高", checklist=[]))
        db.commit()
        payload = ImpactScopeBuilder(db, tenant_id).for_incident(db.get(Incident, incident_id))

    task = _item(payload, "task", f"task-a04-{suffix}")
    assert task["degree"] == "direct"
    assert task["relation"]["via"] == "tasks"
    assert task["status"]["value"] == "pending"


# ── B8：已关闭订单排除 ────────────────────────────────────────────────────────


def test_b8_closed_orders_are_excluded_and_the_exclusion_is_disclosed() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    assert keys["closedOrder"] not in _ids(payload, "order")
    excluded = next(item for item in payload["limitations"] if item["code"] == "CG-A045")
    assert excluded["excludedOrders"] == 1   # 排除多少条要说清楚，不静默丢弃


# ── B9 / B10 / B11：空数据降级 ────────────────────────────────────────────────


def test_b9_no_seed_returns_a_renderable_limitation_without_any_numbers() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {})   # 既无物料也无供应商
    payload = _scope(tenant_id, risk_id)

    assert payload["available"] is False
    assert payload["code"] == "CG-2511"
    assert payload["groups"] == []
    assert payload["summary"]["total"] == 0
    # 不得夹带任何实体名——降级就是降级，不能顺手泄一点
    body = json.dumps(payload, ensure_ascii=False)
    for value in (keys["material"], keys["supplier"], keys["customer"], keys["order"]):
        assert value not in body


def test_b10_resolved_seed_with_zero_neighbours_says_scope_is_limited() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        _tenant(db, tenant_id)
        db.add(Material(id=f"mat-lonely-{suffix}", tenant_id=tenant_id,
                        material_id=f"MAT-A04-LONELY-{suffix}", material_name="孤立物料",
                        category="芯片", unit="件", daily_consumption=100, unit_cost=1,
                        is_critical=False, extra={}))
        db.commit()
        risk_id = _risk(db, tenant_id, suffix, {"material_id": f"MAT-A04-LONELY-{suffix}"})
    payload = _scope(tenant_id, risk_id)

    # 起点解析成功，所以 available 仍为 true——"范围有限"和"算不出来"是两回事
    assert payload["available"] is True
    assert "CG-A041" in _codes(payload)
    assert _group(payload, "inventory")["total"] == 0
    assert _group(payload, "supplier")["emptyReason"]
    assert payload["summary"]["byType"]["material"] == 1


def test_b11_incident_without_valid_source_risks_is_declared_not_guessed() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    incident_id = f"inc-a04-empty-{suffix}"
    with SessionLocal() as db:
        _tenant(db, tenant_id)
        db.add(Incident(id=incident_id, tenant_id=tenant_id, code=f"INC-A04-E-{suffix}",
                        title="无来源风险事件", type="supplier_shutdown", level="medium",
                        status="pending", owner="scm", source_risk_ids=[], loss=0, cost=0, notes=[]))
        db.commit()
        payload = ImpactScopeBuilder(db, tenant_id).for_incident(db.get(Incident, incident_id))

    assert payload["available"] is False
    assert payload["code"] == "CG-A043"


# ── B12 / B13：跨租户隔离 ─────────────────────────────────────────────────────


def test_b12_cross_tenant_request_is_404_and_leaks_nothing() -> None:
    suffix_a, suffix_b = uuid.uuid4().hex[:8], uuid.uuid4().hex[:8]
    tenant_a, tenant_b = f"tenant-a04-a-{suffix_a}", f"tenant-a04-b-{suffix_b}"
    with SessionLocal() as db:
        keys_a = _graph(db, tenant_a, suffix_a)
        risk_a = _risk(db, tenant_a, suffix_a, {"material_id": keys_a["material"]})
        _tenant(db, tenant_b)
        user_b = _account(db, tenant_b, suffix_b, FULL_PERMISSIONS)
        db.commit()

    response = client.get(f"/api/v1/risks/{risk_a}/impact-scope", headers=_headers(user_b))
    assert response.status_code == 404
    body = response.text
    # 连"存在性"都不能泄露，更别提物料名/仓库名/供应商名/客户名
    for value in (keys_a["material"], keys_a["supplier"], keys_a["customer"],
                  keys_a["warehouse1"], keys_a["order"]):
        assert value not in body


def test_b13_traversal_never_crosses_into_another_tenant() -> None:
    """两个租户放同名同 id 的实体，A 的影响范围只能命中 A 自己的行。"""
    suffix = uuid.uuid4().hex[:8]
    tenant_a, tenant_b = f"tenant-a04-a-{suffix}", f"tenant-a04-b-{suffix}"
    with SessionLocal() as db:
        keys = _graph(db, tenant_a, suffix)
        _tenant(db, tenant_b)
        # 租户 B 用完全相同的业务键，但挂不同的仓库与客户
        db.add(Material(id=f"mat-b-{suffix}", tenant_id=tenant_b, material_id=keys["material"],
                        material_name="B租户同名物料", category="芯片", unit="件",
                        daily_consumption=480, unit_cost=10, is_critical=True, extra={}))
        db.flush()
        db.add(InventoryEntity(id=f"inv-b-{suffix}", tenant_id=tenant_b,
                               inventory_id=f"INV-B-{suffix}", material_id=keys["material"],
                               warehouse_id=f"WH-B-{suffix}", warehouse_name="B租户仓",
                               on_hand_qty=1, available_qty=1, safety_stock_qty=1,
                               in_transit_qty=0, extra={}))
        db.commit()
        risk_id = _risk(db, tenant_a, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_a, risk_id)

    assert f"WH-B-{suffix}" not in _ids(payload, "warehouse")
    assert f"INV-B-{suffix}" not in _ids(payload, "inventory")
    assert "B租户同名物料" not in json.dumps(payload, ensure_ascii=False)


# ── B14：事件端点就地替换 ────────────────────────────────────────────────────


def test_b14_incident_impact_endpoint_now_returns_the_entity_graph() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    incident_id = f"inc-a04-api-{suffix}"
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]},
                        incident_id=incident_id)
        db.add(Incident(id=incident_id, tenant_id=tenant_id, code=f"INC-A04-API-{suffix}",
                        title="A04 事件", type="supplier_shutdown", level="high", status="pending",
                        owner="scm", source_risk_ids=[risk_id], loss=0, cost=0, notes=[]))
        user_id = _account(db, tenant_id, suffix, FULL_PERMISSIONS)
        db.commit()

    response = client.get(f"/api/v1/incidents/{incident_id}/impact", headers=_headers(user_id))
    assert response.status_code == 200
    payload = response.json()
    assert "groups" in payload and "summary" in payload
    assert payload["scopeOf"]["kind"] == "incident"
    # 旧尽力版的契约（dataMissing/materials 顶层数组）已经不复存在
    assert "dataMissing" not in payload
    assert keys["supplier"] in _ids(payload, "supplier")


# ── B15 / B16：脱敏与权限 ────────────────────────────────────────────────────


def test_b15_requester_without_field_permissions_sees_masked_money_and_tier() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
        buyer = _account(db, tenant_id, f"buyer-{suffix}", BUYER_PERMISSIONS)
        lead = _account(db, tenant_id, f"lead-{suffix}", FULL_PERMISSIONS)
        db.commit()

    masked = client.get(f"/api/v1/risks/{risk_id}/impact-scope",
                        headers=_headers(buyer)).json()
    order = _item(masked, "order", keys["order"])
    supplier = _item(masked, "supplier", keys["supplier"])
    assert order["fields"]["orderAmount"] == "***"
    assert order["fields"]["penaltyCost"] == "***"
    assert order["fields"]["grossProfit"] == "***"
    assert supplier["fields"]["supplierPrice"] == "***"
    assert _item(masked, "customer", keys["customer"])["fields"]["customerLevel"] == "***"

    full = client.get(f"/api/v1/risks/{risk_id}/impact-scope", headers=_headers(lead)).json()
    assert _item(full, "order", keys["order"])["fields"]["orderAmount"] == 1_800_000
    assert _item(full, "customer", keys["customer"])["fields"]["customerLevel"] == "A"


@pytest.mark.parametrize(
    "permissions,path_kind",
    [(["dashboard:view"], "risk"), (["dashboard:view"], "incident")],
)
def test_b16_missing_permission_is_403(permissions: list[str], path_kind: str) -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    incident_id = f"inc-a04-perm-{suffix}"
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
        db.add(Incident(id=incident_id, tenant_id=tenant_id, code=f"INC-A04-P-{suffix}",
                        title="权限事件", type="supplier_shutdown", level="high", status="pending",
                        owner="scm", source_risk_ids=[risk_id], loss=0, cost=0, notes=[]))
        user_id = _account(db, tenant_id, suffix, permissions)
        db.commit()

    url = (f"/api/v1/risks/{risk_id}/impact-scope" if path_kind == "risk"
           else f"/api/v1/incidents/{incident_id}/impact")
    assert client.get(url, headers=_headers(user_id)).status_code == 403


# ── B19 / B20 / B21：跳数、截断、关系可追溯 ─────────────────────────────────


def test_b19_traversal_stops_at_two_hops() -> None:
    """客户的其他订单不得出现——它在第三跳，因果关系已经太弱。"""
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    other_order = f"SO-A04-OTHER-{suffix}"
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        # 同一客户的另一张订单，但它不含受影响物料
        db.add(SalesOrder(id=f"so-other-{suffix}", tenant_id=tenant_id,
                          sales_order_id=other_order, customer_id=keys["customer"],
                          order_status="confirmed",
                          promised_delivery_at=datetime.now(timezone.utc) + timedelta(days=9),
                          order_amount=500_000, gross_profit=100_000, penalty_cost=0, extra={}))
        db.commit()
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    assert other_order not in _ids(payload, "order")
    assert payload["traversal"]["maxHops"] == 2


def test_b20_oversized_group_is_truncated_with_the_real_total_disclosed() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    overflow = 3
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix, second_warehouse=False)
        rows = [
            InventoryEntity(
                id=f"inv-bulk-{suffix}-{index}", tenant_id=tenant_id,
                inventory_id=f"INV-BULK-{suffix}-{index}", material_id=keys["material"],
                warehouse_id=f"WH-A04-1-{suffix}", warehouse_name="A04上海一仓",
                on_hand_qty=1, available_qty=1, safety_stock_qty=1, in_transit_qty=0, extra={})
            for index in range(MAX_ITEMS_PER_TYPE + overflow - 2)   # 夹具已有 2 条库存行
        ]
        db.add_all(rows)
        db.commit()
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    assert _group(payload, "inventory")["total"] == MAX_ITEMS_PER_TYPE
    truncated = next(item for item in payload["limitations"] if item["code"] == "CG-A044")
    assert truncated["truncated"] == overflow
    assert truncated["total"] == MAX_ITEMS_PER_TYPE + overflow


def test_b21_every_relation_names_a_real_table_and_starts_at_a_seed() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    real_tables = {
        "materials", "inventory", "suppliers", "supplier_materials",
        "sales_orders", "sales_order_lines", "customers", "tasks",
    }
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    seed_tokens = {f"{s['entityType']}:{s['id']}" for s in payload["seeds"]}
    for group in payload["groups"]:
        for item in group["items"]:
            assert item["relation"]["via"] in real_tables, item
            assert item["relation"]["label"]
            assert item["source"]["table"] in real_tables
            assert item["relation"]["path"][0] in seed_tokens, item
            # 更新时间必须是实体行的真实时间戳，不是"现在"
            assert item["updatedAt"] is not None


def test_b21b_links_point_at_the_real_business_object_pages() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"material_id": keys["material"]})
    payload = _scope(tenant_id, risk_id)

    assert _item(payload, "supplier", keys["supplier"])["link"] == f"/data/supplier?id={keys['supplier']}"
    assert _item(payload, "customer", keys["customer"])["link"] == f"/data/customer?id={keys['customer']}"
    assert _item(payload, "order", keys["order"])["link"] == f"/data/order?id={keys['order']}"
    # 仓库没有资料页（无主数据），link 必须是 null 而不是一个会 404 的假链接
    assert _item(payload, "warehouse", keys["warehouse1"])["link"] is None


# ── 起点为供应商（外部录入型风险）──────────────────────────────────────────


def test_supplier_seeded_risk_expands_through_its_materials() -> None:
    tenant_id, suffix = f"tenant-a04-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        keys = _graph(db, tenant_id, suffix)
        risk_id = _risk(db, tenant_id, suffix, {"supplier_id": keys["supplier"]})
    payload = _scope(tenant_id, risk_id)

    assert _item(payload, "supplier", keys["supplier"])["degree"] == "direct"
    # 该供应商供货的物料是直接影响；这些物料带出的库存/订单则记为间接
    assert _item(payload, "material", keys["material"])["degree"] == "direct"
    assert _item(payload, "material", keys["sibling"])["degree"] == "direct"
    assert _item(payload, "order", keys["order"])["degree"] == "indirect"
