"""Seed isolated tenants for the Phase 5B C02/C03 node-health browser acceptance run.

租户 A（有真实数据）：
  - MAT-C02-CRIT：库存支撑 15 小时 → 引擎判红色预警 → 物料节点 critical
  - MAT-C02-OK  ：库存充裕 → 正常；在 B 仓的分仓可用量低于安全库存 → B 仓 critical（事实判据）
  - MAT-C02-BARE：日消耗缺失 → 引擎算不了 → unknown（不得被计为健康）
  - SUP-C02-STOP（停产）→ critical；SUP-C02-OK（可用，供 critical 物料）→ warning
  - SO-C02-LATE（承诺交期已过）→ critical；SO-C02-OK → healthy；SO-C02-DONE（已交付）→ 排除
  - 一线四角色账号（warehouse/buyer/planner/sales）+ 管理者 + boss（无对口节点类型）
租户 B：自有同构数据，实体名刻意全部不同，用于跨租户隔离的页面文本断言。
租户 EMPTY：零实体，用于 CG-C021 空数据降级。

三个租户都不是 tenant-demo，避免与演示数据链互相污染。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.webapi.auth.security import hash_password
from src.webapi.database import Base, SessionLocal, engine
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
from src.webapi.seed import BASE, ROLE_PERMISSIONS

PASSWORD = "NodeHealthE2E@2026!"
TENANT_A, TENANT_B, TENANT_EMPTY = "tenant-c02-real-a", "tenant-c02-real-b", "tenant-c02-real-empty"

ACCOUNT_MANAGER = "c02-manager-a@chainguard.test"
ACCOUNT_WAREHOUSE = "c02-warehouse-a@chainguard.test"
ACCOUNT_BUYER = "c02-buyer-a@chainguard.test"
ACCOUNT_PLANNER = "c02-planner-a@chainguard.test"
ACCOUNT_SALES = "c02-sales-a@chainguard.test"
ACCOUNT_BOSS = "c02-boss-a@chainguard.test"
ACCOUNT_B = "c02-manager-b@chainguard.test"
ACCOUNT_EMPTY = "c02-manager-empty@chainguard.test"

# 管理者用真实的 scm_lead 内置角色：它自带 data:manage（全域范围）与全部 field:*:view。
# 角色码必须是前端 dashboardConfig 认识的内置码，否则工作台取不到分卡配置。
MANAGER_ROLE = "scm_lead"
MANAGER_PERMISSIONS = [*BASE, *ROLE_PERMISSIONS[MANAGER_ROLE]]


def _user(db, tenant_id: str, account: str, name: str, code: str, permissions: list[str]) -> None:
    role = Role(id=f"role-{tenant_id}-{code}", tenant_id=tenant_id, code=code,
                name=name, builtin=False, permissions=permissions)
    db.add(role)
    db.flush()
    db.add(User(
        id=f"user-{tenant_id}-{code}", tenant_id=tenant_id, account=account,
        password_hash=hash_password(PASSWORD), name=name, phone="", email=account,
        dept_id="dept-c02", role_id=role.id, role_code=code, status="active", data_scope="all",
    ))


def _network(db, tenant_id: str, key: str, label: str) -> None:
    """四类节点的每种健康状态各有代表，全部由真实实体行承载。"""
    now = datetime.now(timezone.utc)
    crit, ok, bare = f"MAT-{key}-CRIT", f"MAT-{key}-OK", f"MAT-{key}-BARE"

    db.add_all([
        # 日消耗 480 → 小时消耗 20；库存 300 → 支撑 15 小时 < 红线 24 → 红色预警
        Material(id=f"mat-{tenant_id}-crit", tenant_id=tenant_id, material_id=crit,
                 material_name=f"{label}主控芯片", category="电子元器件", unit="片",
                 daily_consumption=480, unit_cost=45, is_critical=True),
        Material(id=f"mat-{tenant_id}-ok", tenant_id=tenant_id, material_id=ok,
                 material_name=f"{label}通用外壳", category="结构件", unit="个",
                 daily_consumption=24, unit_cost=3, is_critical=False),
        # 日消耗缺失 → CG-2512 → unknown
        Material(id=f"mat-{tenant_id}-bare", tenant_id=tenant_id, material_id=bare,
                 material_name=f"{label}未维护物料", category="其他", unit="个",
                 daily_consumption=None, unit_cost=None, is_critical=False),
    ])
    db.flush()

    arrival = now + timedelta(days=30)
    db.add_all([
        InventoryEntity(
            id=f"inv-{tenant_id}-crit", tenant_id=tenant_id, inventory_id=f"INV-{key}-CRIT",
            material_id=crit, warehouse_id=f"WH-{key}-A", warehouse_name=f"{label}一号仓",
            on_hand_qty=300, available_qty=300, safety_stock_qty=960, in_transit_qty=2000,
            planned_arrival_at=arrival, estimated_arrival_at=arrival + timedelta(hours=72)),
        InventoryEntity(
            id=f"inv-{tenant_id}-ok-a", tenant_id=tenant_id, inventory_id=f"INV-{key}-OK-A",
            material_id=ok, warehouse_id=f"WH-{key}-A", warehouse_name=f"{label}一号仓",
            on_hand_qty=10000, available_qty=10000, safety_stock_qty=10, in_transit_qty=0),
        # 分仓可用量低于安全库存，但全局合计无缺口 → 二号仓 critical 只可能来自库存行事实
        InventoryEntity(
            id=f"inv-{tenant_id}-ok-b", tenant_id=tenant_id, inventory_id=f"INV-{key}-OK-B",
            material_id=ok, warehouse_id=f"WH-{key}-B", warehouse_name=f"{label}二号仓",
            on_hand_qty=5, available_qty=5, safety_stock_qty=100, in_transit_qty=0),
    ])
    db.add_all([
        SupplierEntity(id=f"sup-{tenant_id}-stop", tenant_id=tenant_id,
                       supplier_id=f"SUP-{key}-STOP", supplier_name=f"{label}停产封测厂",
                       region="江苏", status="停产", reliability_score=62),
        SupplierEntity(id=f"sup-{tenant_id}-ok", tenant_id=tenant_id,
                       supplier_id=f"SUP-{key}-OK", supplier_name=f"{label}在产微电子",
                       region="浙江", status="可用", reliability_score=85),
        CustomerEntity(id=f"cus-{tenant_id}", tenant_id=tenant_id, customer_id=f"CUS-{key}",
                       customer_name=f"{label}整机客户", customer_level="A", region="华东",
                       contract="年度框架", owner="销售一部"),
    ])
    db.flush()
    db.add_all([
        SupplierMaterial(
            id=f"sm-{tenant_id}-ok", tenant_id=tenant_id, supplier_material_id=f"SM-{key}-OK",
            supplier_id=f"SUP-{key}-OK", material_id=crit, qualified=True, supplier_rank=1,
            available_emergency_qty=4000, lead_time_hours=96, emergency_cost_multiplier=1.35,
            supplier_price=48),
        SupplierMaterial(
            id=f"sm-{tenant_id}-stop", tenant_id=tenant_id, supplier_material_id=f"SM-{key}-STOP",
            supplier_id=f"SUP-{key}-STOP", material_id=crit, qualified=True, supplier_rank=2,
            available_emergency_qty=100, lead_time_hours=200, emergency_cost_multiplier=2.0,
            supplier_price=60),
    ])
    db.add_all([
        SalesOrder(id=f"so-{tenant_id}-late", tenant_id=tenant_id, sales_order_id=f"SO-{key}-LATE",
                   customer_id=f"CUS-{key}", order_status="confirmed",
                   promised_delivery_at=now - timedelta(days=2),
                   order_amount=1_800_000, gross_profit=420_000, penalty_cost=180_000),
        SalesOrder(id=f"so-{tenant_id}-ok", tenant_id=tenant_id, sales_order_id=f"SO-{key}-OK",
                   customer_id=f"CUS-{key}", order_status="confirmed",
                   promised_delivery_at=now + timedelta(days=30),
                   order_amount=90_000, gross_profit=18_000, penalty_cost=9_000),
        # 已交付 → 整个不计入节点健康，并在限制里明示排除条数
        SalesOrder(id=f"so-{tenant_id}-done", tenant_id=tenant_id, sales_order_id=f"SO-{key}-DONE",
                   customer_id=f"CUS-{key}", order_status="delivered",
                   promised_delivery_at=now - timedelta(days=20),
                   order_amount=50_000, gross_profit=10_000, penalty_cost=5_000),
    ])
    db.flush()
    db.add_all([
        SalesOrderLine(id=f"sol-{tenant_id}-late", tenant_id=tenant_id,
                       sales_order_line_id=f"SOL-{key}-LATE", sales_order_id=f"SO-{key}-LATE",
                       line_no=1, material_id=crit, ordered_qty=6000, unit_price=300),
        SalesOrderLine(id=f"sol-{tenant_id}-ok", tenant_id=tenant_id,
                       sales_order_line_id=f"SOL-{key}-OK", sales_order_id=f"SO-{key}-OK",
                       line_no=1, material_id=ok, ordered_qty=100, unit_price=900),
        SalesOrderLine(id=f"sol-{tenant_id}-done", tenant_id=tenant_id,
                       sales_order_line_id=f"SOL-{key}-DONE", sales_order_id=f"SO-{key}-DONE",
                       line_no=1, material_id=ok, ordered_qty=50, unit_price=900),
    ])
    db.flush()


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for tenant_id, name in (
            (TENANT_A, "C02 真实租户 A"), (TENANT_B, "C02 隔离租户 B"), (TENANT_EMPTY, "C02 空数据租户"),
        ):
            db.add(Tenant(id=tenant_id, name=name, industry="电子制造", scale="50-200",
                          status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()

        _user(db, TENANT_A, ACCOUNT_MANAGER, "C02 供应链负责人", MANAGER_ROLE, MANAGER_PERMISSIONS)
        # 一线四角色用 seed 里**真实的**内置角色权限，范围断言必须打在真权限上
        for account, role_code, name in (
            (ACCOUNT_WAREHOUSE, "warehouse", "C02 仓库人员"),
            (ACCOUNT_BUYER, "buyer", "C02 采购人员"),
            (ACCOUNT_PLANNER, "planner", "C02 生产计划人员"),
            (ACCOUNT_SALES, "sales", "C02 销售人员"),
            (ACCOUNT_BOSS, "boss", "C02 老板"),
        ):
            _user(db, TENANT_A, account, name, role_code, [*BASE, *ROLE_PERMISSIONS[role_code]])
        _user(db, TENANT_B, ACCOUNT_B, "C02 隔离租户负责人", MANAGER_ROLE, MANAGER_PERMISSIONS)
        _user(db, TENANT_EMPTY, ACCOUNT_EMPTY, "C02 空租户负责人", MANAGER_ROLE, MANAGER_PERMISSIONS)

        _network(db, TENANT_A, "C02A", "A租户")
        # 租户 B：实体名刻意全部不同，跨租户断言直接做页面文本比对
        _network(db, TENANT_B, "C02B", "B租户专属")
        # 租户 EMPTY 刻意不灌任何实体 → CG-C021
        db.commit()
    print(f"已生成 C02/C03 验收租户：{TENANT_A} / {TENANT_B} / {TENANT_EMPTY}")


if __name__ == "__main__":
    main()
