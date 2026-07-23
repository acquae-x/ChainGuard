"""C02/C03 供应链节点健康视图验收。

贯穿全篇的纪律：
- 物料节点的健康必须与既有引擎 (calculate_inventory_risk → measure_material) **逐值一致**，
  而不是"看起来差不多"；
- 非物料节点的每条结论都必须能指回一条真实实体行字段或一个真实物料节点；
- 数据不足必须是 unknown，绝不允许被算作 healthy。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api import app
from src.inventory_monitor import calculate_inventory_risk
from src.webapi.auth.security import create_tokens
from src.webapi.context_builder import TenantContextBuilder
from src.webapi.database import SessionLocal
from src.webapi.models import (
    CustomerEntity,
    InventoryEntity,
    Material,
    Role,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    Tenant,
    User,
)
from src.webapi.node_health import (
    MAX_NODES_PER_TYPE,
    scope_for,
)
from src.webapi.risk_recompute import measure_material
from src.webapi.seed import BASE, ROLE_PERMISSIONS, seed

seed()
client = TestClient(app)

OVERVIEW = "/api/v1/dashboard/node-health"
MINE = "/api/v1/dashboard/my-nodes"


# ── 夹具 ──────────────────────────────────────────────────────────────────────


def _tenant(db, tenant_id: str) -> None:
    db.merge(Tenant(id=tenant_id, name=tenant_id, industry="制造", scale="small",
                    status="active", plan="trial", trial_end_at="", demo_data_flag=False))
    db.flush()


def _account(db, tenant_id: str, suffix: str, permissions: list[str]) -> str:
    role_id, user_id = f"role-c02-{suffix}", f"user-c02-{suffix}"
    db.add(Role(id=role_id, tenant_id=tenant_id, code=f"c02_{suffix}", name="C02测试角色",
                builtin=False, permissions=permissions))
    db.flush()
    db.add(User(id=user_id, tenant_id=tenant_id, account=f"c02-{suffix}@test",
                password_hash="x", name="C02测试用户", phone="", email="", dept_id="dept-1",
                role_id=role_id, role_code=f"c02_{suffix}", status="active", data_scope="all",
                must_change_password=False))
    db.flush()
    return user_id


def _role_account(db, tenant_id: str, role_code: str) -> str:
    """用 seed 里**真实的**内置角色权限建账号——角色差异断言必须打在真权限上。"""
    return _account(db, tenant_id, role_code, [*BASE, *ROLE_PERMISSIONS[role_code]])


def _headers(user_id: str) -> dict[str, str]:
    with SessionLocal() as db:
        return {"Authorization": f"Bearer {create_tokens(db.get(User, user_id))['token']}"}


def _graph(db, tenant_id: str, suffix: str) -> None:
    """一张可控的真实实体图谱，四类节点的每种健康状态各有代表。

    数值取向（与 seed 演示租户同款推导，保证物料节点确实落到红色预警）：
    CRIT 日消耗 480 → 小时消耗 20，库存 300 → 支撑 15 小时 < 红线 24。
    OK 日消耗 24 → 小时消耗 1，库存 10005 → 支撑 10005 小时，远高于黄线 48。
    """
    now = datetime.now(timezone.utc)
    p = suffix.upper()
    db.add_all([
        # 引擎判定为红色预警的物料
        Material(id=f"m-crit-{suffix}", tenant_id=tenant_id, material_id=f"MAT-CRIT-{p}",
                 material_name=f"关键芯片{p}", category="电子", unit="片",
                 daily_consumption=480, unit_cost=45, is_critical=True),
        # 引擎判定为正常的物料
        Material(id=f"m-ok-{suffix}", tenant_id=tenant_id, material_id=f"MAT-OK-{p}",
                 material_name=f"通用外壳{p}", category="结构件", unit="个",
                 daily_consumption=24, unit_cost=3, is_critical=False),
        # 日消耗缺失 → 引擎算不了 → unknown（CG-2512）
        Material(id=f"m-bare-{suffix}", tenant_id=tenant_id, material_id=f"MAT-BARE-{p}",
                 material_name=f"未维护物料{p}", category="其他", unit="个",
                 daily_consumption=None, unit_cost=None, is_critical=False),
    ])
    db.flush()
    db.add_all([
        InventoryEntity(id=f"inv-crit-{suffix}", tenant_id=tenant_id,
                        inventory_id=f"INV-CRIT-{p}", material_id=f"MAT-CRIT-{p}",
                        warehouse_id=f"WH-A-{p}", warehouse_name=f"{p}一号仓",
                        on_hand_qty=300, available_qty=300, safety_stock_qty=960,
                        in_transit_qty=2000, planned_arrival_at=now + timedelta(days=30),
                        estimated_arrival_at=now + timedelta(days=30, hours=72)),
        # OK 物料的主仓：可用量远高于安全库存
        InventoryEntity(id=f"inv-ok-a-{suffix}", tenant_id=tenant_id,
                        inventory_id=f"INV-OK-A-{p}", material_id=f"MAT-OK-{p}",
                        warehouse_id=f"WH-A-{p}", warehouse_name=f"{p}一号仓",
                        on_hand_qty=10000, available_qty=10000, safety_stock_qty=10,
                        in_transit_qty=0),
        # OK 物料在 B 仓的分仓：单仓可用量低于安全库存，但全局合计无缺口
        InventoryEntity(id=f"inv-ok-b-{suffix}", tenant_id=tenant_id,
                        inventory_id=f"INV-OK-B-{p}", material_id=f"MAT-OK-{p}",
                        warehouse_id=f"WH-B-{p}", warehouse_name=f"{p}二号仓",
                        on_hand_qty=5, available_qty=5, safety_stock_qty=100,
                        in_transit_qty=0),
        # 无仓库标识的库存行 → 归不进任何仓库节点（CG-C027）
        InventoryEntity(id=f"inv-nowh-{suffix}", tenant_id=tenant_id,
                        inventory_id=f"INV-NOWH-{p}", material_id=f"MAT-OK-{p}",
                        warehouse_id=None, warehouse_name=None,
                        on_hand_qty=1, available_qty=1, safety_stock_qty=0, in_transit_qty=0),
    ])
    db.add_all([
        SupplierEntity(id=f"sup-stop-{suffix}", tenant_id=tenant_id,
                       supplier_id=f"SUP-STOP-{p}", supplier_name=f"{p}停产封测厂",
                       region="江苏", status="停产", reliability_score=92),
        SupplierEntity(id=f"sup-ok-{suffix}", tenant_id=tenant_id,
                       supplier_id=f"SUP-OK-{p}", supplier_name=f"{p}在产微电子",
                       region="浙江", status="可用", reliability_score=85),
        SupplierEntity(id=f"sup-bare-{suffix}", tenant_id=tenant_id,
                       supplier_id=f"SUP-BARE-{p}", supplier_name=f"{p}未维护供应商",
                       region=None, status=None, reliability_score=None),
        CustomerEntity(id=f"cus-{suffix}", tenant_id=tenant_id, customer_id=f"CUS-{p}",
                       customer_name=f"{p}智能装备", customer_level="A", region="江苏",
                       contract="年度框架", owner="销售"),
    ])
    db.flush()
    db.add_all([
        # SUP-OK 供的是异常物料 → 传播为 warning（不是 critical）
        SupplierMaterial(id=f"sm-ok-{suffix}", tenant_id=tenant_id,
                         supplier_material_id=f"SM-OK-{p}", supplier_id=f"SUP-OK-{p}",
                         material_id=f"MAT-CRIT-{p}", qualified=True, supplier_rank=1,
                         available_emergency_qty=4000, lead_time_hours=96,
                         emergency_cost_multiplier=1.35, supplier_price=48),
        SupplierMaterial(id=f"sm-stop-{suffix}", tenant_id=tenant_id,
                         supplier_material_id=f"SM-STOP-{p}", supplier_id=f"SUP-STOP-{p}",
                         material_id=f"MAT-CRIT-{p}", qualified=True, supplier_rank=2,
                         available_emergency_qty=100, lead_time_hours=200,
                         emergency_cost_multiplier=2.0, supplier_price=60),
    ])
    db.add_all([
        # 承诺交期已过 → critical（纯事实）
        SalesOrder(id=f"so-late-{suffix}", tenant_id=tenant_id,
                   sales_order_id=f"SO-LATE-{p}", customer_id=f"CUS-{p}",
                   order_status="confirmed", promised_delivery_at=now - timedelta(days=2),
                   order_amount=1800000, gross_profit=450000, penalty_cost=180000),
        # 交期未到 + 只需健康物料 → healthy
        SalesOrder(id=f"so-ok-{suffix}", tenant_id=tenant_id,
                   sales_order_id=f"SO-OK-{p}", customer_id=f"CUS-{p}",
                   order_status="confirmed", promised_delivery_at=now + timedelta(days=30),
                   order_amount=90000, gross_profit=18000, penalty_cost=9000),
        # 已交付 → 整个不计入（CG-C026）
        SalesOrder(id=f"so-done-{suffix}", tenant_id=tenant_id,
                   sales_order_id=f"SO-DONE-{p}", customer_id=f"CUS-{p}",
                   order_status="delivered", promised_delivery_at=now - timedelta(days=20),
                   order_amount=50000, gross_profit=10000, penalty_cost=5000),
    ])
    db.flush()
    db.add_all([
        SalesOrderLine(id=f"sol-late-{suffix}", tenant_id=tenant_id,
                       sales_order_line_id=f"SOL-LATE-{p}", sales_order_id=f"SO-LATE-{p}",
                       line_no=1, material_id=f"MAT-CRIT-{p}", ordered_qty=6000, unit_price=300),
        SalesOrderLine(id=f"sol-ok-{suffix}", tenant_id=tenant_id,
                       sales_order_line_id=f"SOL-OK-{p}", sales_order_id=f"SO-OK-{p}",
                       line_no=1, material_id=f"MAT-OK-{p}", ordered_qty=100, unit_price=900),
        SalesOrderLine(id=f"sol-done-{suffix}", tenant_id=tenant_id,
                       sales_order_line_id=f"SOL-DONE-{p}", sales_order_id=f"SO-DONE-{p}",
                       line_no=1, material_id=f"MAT-OK-{p}", ordered_qty=50, unit_price=900),
    ])
    db.flush()


@pytest.fixture(scope="module")
def graph() -> dict[str, str]:
    """两个隔离租户（同构图谱）+ 一个空租户 + 各角色账号。"""
    with SessionLocal() as db:
        for tenant_id, suffix in (("tenant-c02-a", "a"), ("tenant-c02-b", "b")):
            _tenant(db, tenant_id)
            _graph(db, tenant_id, suffix)
        _tenant(db, "tenant-c02-empty")
        ids = {
            "full": _account(db, "tenant-c02-a", "full", [
                "dashboard:view", "data:manage", "field:cost:view", "field:profit:view",
                "field:customerLevel:view", "field:supplierPrice:view", "field:contract:view",
            ]),
            "masked": _account(db, "tenant-c02-a", "masked", ["dashboard:view", "data:manage"]),
            "b_full": _account(db, "tenant-c02-b", "bfull", ["dashboard:view", "data:manage"]),
            "empty": _account(db, "tenant-c02-empty", "empty", ["dashboard:view", "data:manage"]),
        }
        for role_code in ("warehouse", "buyer", "planner", "sales", "boss", "finance",
                          "scm_lead", "auditor"):
            ids[role_code] = _role_account(db, "tenant-c02-a", role_code)
        ids["empty_warehouse"] = _account(
            db, "tenant-c02-empty", "empty-wh",
            [*BASE, *ROLE_PERMISSIONS["warehouse"]],
        )
        db.commit()
    return ids


def _overview(graph: dict[str, str], who: str = "full", **params) -> dict:
    response = client.get(OVERVIEW, headers=_headers(graph[who]), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _mine(graph: dict[str, str], who: str, **params) -> dict:
    response = client.get(MINE, headers=_headers(graph[who]), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _node(payload: dict, node_type: str, node_id: str) -> dict:
    matches = [n for n in payload["nodes"] if n["nodeType"] == node_type and n["id"] == node_id]
    assert matches, f"{node_type}:{node_id} 不在节点列表中：{[n['id'] for n in payload['nodes']]}"
    return matches[0]


def _codes(node: dict) -> list[str]:
    return [reason["code"] for reason in node["reasons"]]


def _all(graph: dict[str, str], who: str = "full", **params) -> dict:
    """取全量（不分页），供计数类断言使用。"""
    return _overview(graph, who, pageSize=500, **params)


# ── N1–N3 物料节点：唯一由引擎算出的一类 ──────────────────────────────────────


def test_n1_material_health_matches_engine_verbatim(graph):
    """N1：物料节点的健康与原因，必须与既有引擎输出逐值一致。"""
    payload = _all(graph)
    node = _node(payload, "material", "MAT-CRIT-A")
    assert node["health"] == "critical"

    with SessionLocal() as db:
        builder = TenantContextBuilder(db, "tenant-c02-a")
        snapshot = builder.snapshot_for_material_id("MAT-CRIT-A")
        measurement = measure_material(
            calculate_inventory_risk(snapshot.inventory, snapshot.risk_weights, snapshot.thresholds),
            snapshot,
        )
    assert measurement["warningLevel"] == "红色预警"
    assert node["metrics"]["riskIndex"] == measurement["riskIndex"]
    assert node["metrics"]["warningLevel"] == measurement["warningLevel"]

    red = [r for r in node["reasons"] if r["code"] == "support_hours_below_red"]
    assert red, _codes(node)
    assert red[0]["observed"]["value"] == round(float(measurement["supportHours"]), 2)
    assert red[0]["threshold"]["value"] == measurement["thresholds"]["redSupportHours"]
    # 阈值来源必须写明，用户看得见用的是专家默认值还是本租户校准值
    assert red[0]["threshold"]["source"] in {"expert_default", "tenant_config"}


def test_n2_healthy_material_maps_from_engine(graph):
    """N2：引擎判「正常」→ healthy，不是靠本模块另判一次。"""
    node = _node(_all(graph), "material", "MAT-OK-A")
    assert node["metrics"]["warningLevel"] == "正常"
    assert node["health"] == "healthy"
    assert "support_hours_below_red" not in _codes(node)


def test_n3_uncomputable_material_is_unknown_not_healthy(graph):
    """N3：算不了就是算不了——绝不能被计为健康。"""
    node = _node(_all(graph), "material", "MAT-BARE-A")
    assert node["health"] == "unknown"
    assert node["healthLabel"] == "数据不足"
    reason = node["reasons"][0]
    assert reason["code"] == "material_not_computable"
    assert "CG-2512" in reason["detail"]

    payload = _all(graph)
    limitation = next(l for l in payload["limitations"] if l["code"] == "CG-C022")
    assert limitation["affectedCount"] >= 1
    # unknown 单独计数，不并入 healthy
    material_row = next(x for x in payload["byType"] if x["nodeType"] == "material")
    assert material_row["unknown"] >= 1


# ── N4–N6 仓库节点 ────────────────────────────────────────────────────────────


def test_n4_warehouse_is_aggregated_and_has_no_detail_page(graph):
    """N4：仓库由库存行聚合而来；没有主数据就不给假链接。"""
    payload = _all(graph)
    warehouses = [n for n in payload["nodes"] if n["nodeType"] == "warehouse"]
    ids = sorted(n["id"] for n in warehouses)
    assert ids == ["WH-A-A", "WH-B-A"]
    # WH-A 有两条库存行，聚合成一个节点
    assert _node(payload, "warehouse", "WH-A-A")["metrics"]["inventoryRowCount"] == 2
    assert all(n["link"] is None for n in warehouses)
    assert any(l["code"] == "CG-C023" for l in payload["limitations"])
    # 无仓库标识的库存行如实披露，不静默丢弃
    unassigned = next(l for l in payload["limitations"] if l["code"] == "CG-C027")
    assert unassigned["affectedRows"] == 1


def test_n5_warehouse_below_safety_stock_is_critical(graph):
    """N5：可用量低于安全库存是事实判据，与引擎 safety_stock_gap 同判据。"""
    node = _node(_all(graph), "warehouse", "WH-B-A")
    assert node["health"] == "critical"
    reason = next(r for r in node["reasons"] if r["code"] == "inventory_below_safety_stock")
    assert reason["observed"]["value"] == 5
    assert reason["threshold"]["value"] == 100
    assert reason["via"] == "inventory"
    # 该仓存放的物料本身是健康的 → 这条 critical 只可能来自库存行事实
    assert "hosts_critical_material" not in _codes(node)


def test_n6_warehouse_propagation_names_the_source_material(graph):
    """N6：传播型结论必须指得回具体那个物料节点。"""
    node = _node(_all(graph), "warehouse", "WH-A-A")
    assert node["health"] == "critical"
    reason = next(r for r in node["reasons"] if r["code"] == "hosts_critical_material")
    assert reason["derivedFrom"]["id"] == "MAT-CRIT-A"
    assert reason["derivedFrom"]["health"] == "critical"
    assert reason["derivedFrom"]["link"] == "/data/material?id=MAT-CRIT-A"


# ── N7–N9 供应商节点 ──────────────────────────────────────────────────────────


def test_n7_supplier_status_word_list(graph):
    """N7：中断判定回显 status 原值与词表依据，可逐字核对。"""
    node = _node(_all(graph), "supplier", "SUP-STOP-A")
    assert node["health"] == "critical"
    reason = next(r for r in node["reasons"] if r["code"] == "supplier_status_disrupted")
    assert reason["observed"]["value"] == "停产"
    assert "停产" in reason["threshold"]["value"]


def test_n8_supplier_propagation_caps_at_warning(graph):
    """N8：供的料出问题 ≠ 这家供应商自己出事，最多到 warning。"""
    node = _node(_all(graph), "supplier", "SUP-OK-A")
    assert node["metrics"]["status"] == "可用"
    assert node["health"] == "warning"
    reason = next(r for r in node["reasons"] if r["code"] == "supplies_critical_material")
    assert reason["derivedFrom"]["id"] == "MAT-CRIT-A"


def test_n9_supplier_without_status_or_relation_is_unknown(graph):
    node = _node(_all(graph), "supplier", "SUP-BARE-A")
    assert node["health"] == "unknown"
    assert _codes(node) == ["insufficient_supplier_fields"]
    # reliability_score 只展示、不参与判定（本例它本来就是 None）
    assert node["metrics"]["reliabilityScore"] is None


def test_n9b_reliability_score_never_drives_health(graph):
    """可靠性评分没有阈值配置，因此不得出现在任何 reason 里。"""
    payload = _all(graph)
    for node in payload["nodes"]:
        for reason in node["reasons"]:
            assert "reliability" not in reason["code"].lower()


# ── N10–N12 订单节点 ──────────────────────────────────────────────────────────


def test_n10_overdue_order_is_fact_not_threshold(graph):
    node = _node(_all(graph), "order", "SO-LATE-A")
    assert node["health"] == "critical"
    reason = next(r for r in node["reasons"] if r["code"] == "delivery_overdue")
    assert reason["threshold"]["source"] == "当前时间（事实比较）"


def test_n11_order_propagation_from_material(graph):
    node = _node(_all(graph), "order", "SO-LATE-A")
    reason = next(r for r in node["reasons"] if r["code"] == "requires_critical_material")
    assert reason["derivedFrom"]["id"] == "MAT-CRIT-A"
    # 只需健康物料且交期未到 → healthy
    ok = _node(_all(graph), "order", "SO-OK-A")
    assert ok["health"] == "healthy"
    assert ok["reasons"] == []


def test_n12_closed_orders_excluded_and_disclosed(graph):
    payload = _all(graph)
    assert not [n for n in payload["nodes"] if n["id"] == "SO-DONE-A"]
    limitation = next(l for l in payload["limitations"] if l["code"] == "CG-C026")
    assert limitation["excludedCount"] == 1


# ── N13–N18 概览、筛选、降级 ──────────────────────────────────────────────────


def test_n13_summary_matches_actual_node_distribution(graph):
    payload = _all(graph)
    for level in ("critical", "warning", "healthy", "unknown"):
        assert payload["summary"][level] == len(
            [n for n in payload["nodes"] if n["health"] == level]
        ), level
    assert payload["summary"]["total"] == len(payload["nodes"])
    assert sum(row["total"] for row in payload["byType"]) == payload["summary"]["total"]
    for row in payload["byType"]:
        assert row["total"] == sum(row[level] for level in
                                   ("critical", "warning", "healthy", "unknown"))


def test_n14_empty_node_type_is_explicit(graph):
    """N14：没有节点的类型仍然出现，且带 emptyReason——不靠类型消失来暗示。"""
    payload = _all(graph, "b_full")
    assert [row["nodeType"] for row in payload["byType"]] == [
        "material", "warehouse", "supplier", "order",
    ]
    with SessionLocal() as db:
        _tenant(db, "tenant-c02-noSupplier")
        db.add(Material(id="m-ns", tenant_id="tenant-c02-noSupplier", material_id="MAT-NS",
                        material_name="孤立物料", category="其他", unit="个",
                        daily_consumption=10, unit_cost=1, is_critical=False))
        db.flush()
        db.add(InventoryEntity(id="inv-ns", tenant_id="tenant-c02-noSupplier",
                               inventory_id="INV-NS", material_id="MAT-NS",
                               warehouse_id="WH-NS", warehouse_name="孤立仓",
                               on_hand_qty=1000, available_qty=1000, safety_stock_qty=1,
                               in_transit_qty=0))
        user_id = _account(db, "tenant-c02-noSupplier", "ns", ["dashboard:view", "data:manage"])
        db.commit()
    response = client.get(OVERVIEW, headers=_headers(user_id), params={"pageSize": 500})
    body = response.json()
    supplier_row = next(x for x in body["byType"] if x["nodeType"] == "supplier")
    assert supplier_row["total"] == 0
    assert supplier_row["emptyReason"]


def test_n15_empty_tenant_degrades_without_any_number(graph):
    """N15：空租户不返回任何统计数字，只返回可渲染的说明。"""
    payload = _overview(graph, "empty")
    assert payload["available"] is False
    assert payload["code"] == "CG-C021"
    assert payload["summary"] is None
    assert payload["byType"] == []
    assert payload["nodes"] == []
    assert any(l["code"] == "CG-C021" for l in payload["limitations"])


def test_n16_filters(graph):
    only_supplier = _all(graph, nodeType="supplier")
    assert {n["nodeType"] for n in only_supplier["nodes"]} == {"supplier"}
    # 概览计数随筛选范围收敛，且与列表自洽
    assert only_supplier["summary"]["total"] == len(only_supplier["nodes"])

    only_critical = _all(graph, health="critical")
    assert {n["health"] for n in only_critical["nodes"]} == {"critical"}
    # summary 是全量概览，filtered 才是筛选结果——两者不得混为一谈
    assert only_critical["filtered"]["total"] == len(only_critical["nodes"])
    assert only_critical["summary"]["total"] > only_critical["filtered"]["total"]

    by_keyword = _all(graph, keyword="MAT-CRIT")
    assert [n["id"] for n in by_keyword["nodes"]] == ["MAT-CRIT-A"]


def test_n17_links_point_at_real_pages(graph):
    payload = _all(graph)
    expected = {
        "material": "/data/material?id=",
        "supplier": "/data/supplier?id=",
        "order": "/data/order?id=",
    }
    for node in payload["nodes"]:
        if node["nodeType"] == "warehouse":
            assert node["link"] is None
            continue
        assert node["link"] == f"{expected[node['nodeType']]}{node['id']}"


def test_n18_propagation_disclosure_is_always_present(graph):
    payload = _all(graph)
    limitation = next(l for l in payload["limitations"] if l["code"] == "CG-C024")
    assert "不是独立评分模型" in limitation["message"]
    # 只筛物料时不涉及传播，该声明不应再出现
    assert not any(
        l["code"] == "CG-C024" for l in _all(graph, nodeType="material")["limitations"]
    )


# ── N19–N21 隔离与脱敏 ────────────────────────────────────────────────────────


def test_n19_cross_tenant_zero_leak(graph):
    """N19：整份 JSON 子串断言——租户 B 的响应里不得出现租户 A 的任何实体名。"""
    body = json.dumps(_all(graph, "b_full"), ensure_ascii=False)
    for leaked in ("MAT-CRIT-A", "MAT-OK-A", "WH-A-A", "SUP-STOP-A", "SO-LATE-A",
                   "关键芯片A", "A停产封测厂", "A智能装备", "tenant-c02-a"):
        assert leaked not in body, leaked


def test_n20_same_id_entities_do_not_bleed(graph):
    """N20：两租户存在同 id 物料时，各自只看到自己的行。"""
    with SessionLocal() as db:
        for tenant_id, name, consumption in (
            ("tenant-c02-a", "A侧同名物料", 480), ("tenant-c02-b", "B侧同名物料", 24),
        ):
            db.merge(Material(id=f"m-dup-{tenant_id}", tenant_id=tenant_id,
                              material_id="MAT-DUP", material_name=name, category="其他",
                              unit="个", daily_consumption=consumption, unit_cost=1,
                              is_critical=False))
            db.flush()
            db.merge(InventoryEntity(id=f"inv-dup-{tenant_id}", tenant_id=tenant_id,
                                     inventory_id="INV-DUP", material_id="MAT-DUP",
                                     warehouse_id="WH-DUP", warehouse_name="同名仓",
                                     on_hand_qty=100, available_qty=100,
                                     safety_stock_qty=10, in_transit_qty=0))
        db.commit()
    assert _node(_all(graph), "material", "MAT-DUP")["name"] == "A侧同名物料"
    assert _node(_all(graph, "b_full"), "material", "MAT-DUP")["name"] == "B侧同名物料"


def test_n21_masking_reuses_existing_field_permissions(graph):
    """N21：出口走 mask_for_requester 同一条路径，不新增脱敏机制。"""
    masked = _node(_all(graph, "masked"), "order", "SO-LATE-A")["metrics"]
    assert masked["orderAmount"] == "***"
    assert masked["penaltyCost"] == "***"
    assert masked["grossProfit"] == "***"
    assert masked["customerLevel"] == "***"
    assert _node(_all(graph, "masked"), "supplier", "SUP-OK-A")["metrics"]["supplierPrice"] == "***"

    full = _node(_all(graph, "full"), "order", "SO-LATE-A")["metrics"]
    assert full["orderAmount"] == 1800000
    assert full["customerLevel"] == "A"
    assert _node(_all(graph, "full"), "supplier", "SUP-OK-A")["metrics"]["supplierPrice"] == 48


# ── N22–N28 角色范围（不新增权限码） ──────────────────────────────────────────


@pytest.mark.parametrize(
    "role_code,expected",
    [
        ("warehouse", ["warehouse"]),
        ("buyer", ["supplier"]),
        ("planner", ["material"]),
        ("sales", ["order"]),
    ],
)
def test_n22_n24_frontline_scope_from_existing_permission_codes(graph, role_code, expected):
    payload = _mine(graph, role_code, pageSize=500)
    assert payload["available"] is True
    assert payload["scope"]["nodeTypes"] == expected
    assert payload["scope"]["isGlobal"] is False
    assert [row["nodeType"] for row in payload["byType"]] == expected
    assert {n["nodeType"] for n in payload["nodes"]} == set(expected)


@pytest.mark.parametrize("role_code", ["boss", "finance"])
def test_n25_role_without_owned_node_type(graph, role_code):
    """N25：没有对口类型就明说，而不是返回空列表让人以为「都健康」。"""
    payload = _mine(graph, role_code)
    assert payload["available"] is False
    assert payload["code"] == "CG-C031"
    assert payload["nodes"] == []
    assert payload["summary"] is None


@pytest.mark.parametrize("role_code", ["scm_lead", "auditor"])
def test_n26_global_scope_roles_see_all_four(graph, role_code):
    payload = _mine(graph, role_code, pageSize=500)
    assert payload["scope"]["isGlobal"] is True
    assert [row["nodeType"] for row in payload["byType"]] == [
        "material", "warehouse", "supplier", "order",
    ]


def test_n27_role_scope_with_no_data(graph):
    payload = _mine(graph, "empty_warehouse")
    # 空租户优先落 CG-C021（连实体都没有），而不是假装「你的类型下没有数据」
    assert payload["available"] is False
    assert payload["code"] == "CG-C021"


def test_n27b_scope_helper_is_pure_and_uses_no_new_codes():
    assert scope_for(("dashboard:view", "data:inventory:manage")) == (["warehouse"], False)
    assert scope_for(("dashboard:view", "data:supplier:manage")) == (["supplier"], False)
    assert scope_for(("dashboard:view", "data:manage"))[1] is True
    assert scope_for(("dashboard:view",)) == ([], False)


def test_n28_unauthenticated_requests_leak_nothing():
    for url in (OVERVIEW, MINE):
        response = client.get(url)
        assert response.status_code == 401
        assert "MAT-CRIT-A" not in response.text


# ── N29–N30 截断与新鲜度 ──────────────────────────────────────────────────────


def test_n29_truncation_discloses_real_total(graph):
    with SessionLocal() as db:
        _tenant(db, "tenant-c02-many")
        db.add_all([
            SupplierEntity(id=f"sup-many-{i}", tenant_id="tenant-c02-many",
                           supplier_id=f"SUP-{i:04d}", supplier_name=f"供应商{i}",
                           region="X", status="可用", reliability_score=80)
            for i in range(MAX_NODES_PER_TYPE + 7)
        ])
        user_id = _account(db, "tenant-c02-many", "many", ["dashboard:view", "data:manage"])
        db.commit()
    body = client.get(OVERVIEW, headers=_headers(user_id),
                      params={"nodeType": "supplier", "pageSize": 1}).json()
    supplier_row = next(x for x in body["byType"] if x["nodeType"] == "supplier")
    assert supplier_row["total"] == MAX_NODES_PER_TYPE
    limitation = next(l for l in body["limitations"] if l["code"] == "CG-C025")
    assert limitation["truncated"]["supplier"]["actualTotal"] == MAX_NODES_PER_TYPE + 7
    assert limitation["truncated"]["supplier"]["shown"] == MAX_NODES_PER_TYPE


def test_n30_updated_at_is_the_real_entity_row_timestamp(graph):
    payload = _all(graph)
    with SessionLocal() as db:
        rows = db.scalars(
            select(InventoryEntity).where(
                InventoryEntity.tenant_id == "tenant-c02-a",
                InventoryEntity.warehouse_id == "WH-A-A",
            )
        ).all()
        newest = max(row.updated_at for row in rows)
        material = db.scalar(
            select(Material).where(
                Material.tenant_id == "tenant-c02-a", Material.material_id == "MAT-CRIT-A"
            )
        )
    assert _node(payload, "material", "MAT-CRIT-A")["updatedAt"].startswith(
        material.updated_at.strftime("%Y-%m-%dT%H:%M")
    )
    assert _node(payload, "warehouse", "WH-A-A")["updatedAt"].startswith(
        newest.strftime("%Y-%m-%dT%H:%M")
    )
    assert payload["dataFreshness"]["scope"] == "resource_type"


# ── N31 零回归的守卫（结构层面） ──────────────────────────────────────────────


def test_n31_module_does_not_touch_decision_pipeline():
    """本模块不得引用演示数据源或决策编排——那是红线。"""
    import pathlib
    source = pathlib.Path("src/webapi/node_health.py").read_text(encoding="utf-8")
    for forbidden in ("scan_supply_chain", "run_demo", "orchestrator", "data_source"):
        assert forbidden not in source, forbidden
