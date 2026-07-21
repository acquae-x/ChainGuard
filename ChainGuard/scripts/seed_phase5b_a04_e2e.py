"""Seed two isolated tenants for the Phase 5B A04 impact-scope browser acceptance run.

租户 A：
  - 一个"有完整关系网"的物料：库存(两个仓库) + 供应商 + 兄弟物料(同供应商) + 订单 + 客户，
    并挂一条事件与一条任务 → 覆盖直接影响、间接影响、任务与跳转。
  - 一个"孤立"物料：只有物料行，两跳内零关联 → 覆盖 CG-A041 范围有限降级。
  - 一个 buyer 账号（无 field:*:view）→ 覆盖脱敏。
  - 一个无 incident:view 的账号 → 覆盖权限门槛。
租户 B：自有同构数据，实体名刻意不同，用于跨租户隔离的页面文本断言。

两个租户都不是 tenant-demo，避免与演示数据链互相污染。
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

PASSWORD = "ImpactScopeE2E@2026!"
TENANT_A, TENANT_B = "tenant-a04-real-a", "tenant-a04-real-b"
ACCOUNT_A = "a04-real-a@chainguard.test"
ACCOUNT_BUYER = "a04-buyer-a@chainguard.test"
ACCOUNT_NOINCIDENT = "a04-norisk-a@chainguard.test"
ACCOUNT_B = "a04-real-b@chainguard.test"

MANAGER_PERMISSIONS = [
    "dashboard:view", "risk:view", "incident:view", "risk:manage", "risk:event:create",
    "decision:view", "field:cost:view", "field:profit:view", "field:customerLevel:view",
    "field:supplierPrice:view",
]
# buyer：能看风险与事件，但没有任何 field:*:view → 金额与客户等级必须是 ***。
BUYER_PERMISSIONS = ["dashboard:view", "risk:view", "incident:view"]
# 无 incident:view → 事件影响范围端点必须 403。
NO_INCIDENT_PERMISSIONS = ["dashboard:view", "risk:view"]


def _user(db, tenant_id: str, account: str, name: str, code: str, permissions: list[str]) -> None:
    role = Role(id=f"role-{tenant_id}-{code}", tenant_id=tenant_id, code=code,
                name=name, builtin=False, permissions=permissions)
    db.add(role)
    db.flush()
    db.add(User(
        id=f"user-{tenant_id}-{code}", tenant_id=tenant_id, account=account,
        password_hash=hash_password(PASSWORD), name=name, phone="", email=account,
        dept_id="dept-a04", role_id=role.id, role_code=code, status="active", data_scope="all",
    ))


def _network(db, tenant_id: str, key: str, label: str) -> dict[str, str]:
    """一张完整的实体关系网，所有关系都由真实外键承载。"""
    now = datetime.now(timezone.utc)
    sibling, supplier_id = f"{key}-SIB", f"SUP-{key}"
    customer_id, order_id, closed_id = f"CUS-{key}", f"SO-{key}", f"SO-{key}-CLOSED"

    db.add(Material(id=f"mat-{tenant_id}-{key}", tenant_id=tenant_id, material_id=key,
                    material_name=f"{label}主控芯片", category="电子元器件", unit="片",
                    daily_consumption=480, unit_cost=45, is_critical=True))
    # 兄弟物料：与主物料共用供应商 → 第二跳的"间接影响"来源
    db.add(Material(id=f"mat-{tenant_id}-{key}-sib", tenant_id=tenant_id, material_id=sibling,
                    material_name=f"{label}电源模块", category="模块", unit="片",
                    daily_consumption=120, unit_cost=8, is_critical=False))
    db.flush()

    arrival = now + timedelta(days=30)
    # 两个仓库、三条库存行 → 仓库分组必须去重成 2 条
    db.add(InventoryEntity(
        id=f"inv1-{tenant_id}-{key}", tenant_id=tenant_id, inventory_id=f"INV-{key}-1",
        material_id=key, warehouse_id=f"WH-{key}-SH", warehouse_name=f"{label}上海一仓",
        on_hand_qty=300, available_qty=300, safety_stock_qty=960, in_transit_qty=2000,
        planned_arrival_at=arrival, estimated_arrival_at=arrival + timedelta(hours=72)))
    db.add(InventoryEntity(
        id=f"inv2-{tenant_id}-{key}", tenant_id=tenant_id, inventory_id=f"INV-{key}-2",
        material_id=key, warehouse_id=f"WH-{key}-SH", warehouse_name=f"{label}上海一仓",
        on_hand_qty=60, available_qty=60, safety_stock_qty=200, in_transit_qty=0))
    db.add(InventoryEntity(
        id=f"inv3-{tenant_id}-{key}", tenant_id=tenant_id, inventory_id=f"INV-{key}-3",
        material_id=key, warehouse_id=f"WH-{key}-SZ", warehouse_name=f"{label}苏州二仓",
        on_hand_qty=120, available_qty=120, safety_stock_qty=300, in_transit_qty=0))

    db.add(SupplierEntity(id=f"sup-{tenant_id}-{key}", tenant_id=tenant_id,
                          supplier_id=supplier_id, supplier_name=f"{label}封测厂",
                          region="江苏", status="停产", reliability_score=62))
    db.add(CustomerEntity(id=f"cus-{tenant_id}-{key}", tenant_id=tenant_id,
                          customer_id=customer_id, customer_name=f"{label}整机客户",
                          customer_level="A", region="华东", contract="年度框架", owner="销售一部"))
    db.flush()

    db.add(SupplierMaterial(
        id=f"sm-{tenant_id}-{key}", tenant_id=tenant_id, supplier_material_id=f"SM-{key}",
        supplier_id=supplier_id, material_id=key, qualified=True, supplier_rank=1,
        available_emergency_qty=4000, lead_time_hours=96, emergency_cost_multiplier=1.35,
        supplier_price=48))
    db.add(SupplierMaterial(
        id=f"sm-{tenant_id}-{key}-sib", tenant_id=tenant_id, supplier_material_id=f"SM-{key}-SIB",
        supplier_id=supplier_id, material_id=sibling, qualified=True, supplier_rank=2,
        available_emergency_qty=1000, lead_time_hours=120, emergency_cost_multiplier=1.2,
        supplier_price=15))

    db.add(SalesOrder(id=f"so-{tenant_id}-{key}", tenant_id=tenant_id, sales_order_id=order_id,
                      customer_id=customer_id, order_status="confirmed",
                      promised_delivery_at=now + timedelta(days=5),
                      order_amount=1_800_000, gross_profit=420_000, penalty_cost=180_000))
    # 已交付订单：必须被排除，并在限制里明示排除条数
    db.add(SalesOrder(id=f"soc-{tenant_id}-{key}", tenant_id=tenant_id, sales_order_id=closed_id,
                      customer_id=customer_id, order_status="delivered",
                      promised_delivery_at=now - timedelta(days=5),
                      order_amount=900_000, gross_profit=200_000, penalty_cost=0))
    db.flush()
    db.add(SalesOrderLine(id=f"sol-{tenant_id}-{key}", tenant_id=tenant_id,
                          sales_order_line_id=f"SOL-{key}", sales_order_id=order_id, line_no=1,
                          material_id=key, ordered_qty=6000, unit_price=300))
    db.add(SalesOrderLine(id=f"solc-{tenant_id}-{key}", tenant_id=tenant_id,
                          sales_order_line_id=f"SOLC-{key}", sales_order_id=closed_id, line_no=1,
                          material_id=key, ordered_qty=1000, unit_price=300))
    return {"material": key, "sibling": sibling, "supplier": supplier_id,
            "customer": customer_id, "order": order_id}


def _risk_and_incident(db, tenant_id: str, key: str, label: str) -> None:
    risk_id, incident_id = f"risk-a04-{key}", f"inc-a04-{key}"
    db.add(Risk(
        id=risk_id, tenant_id=tenant_id, code=f"RISK-A04-{key}", level="high", type="库存",
        object_type="物料", object_name=f"{label}主控芯片", score=78.75,
        rule="库存风险指数 78.75 超过触发阈值 70（主因：缺货紧迫度）",
        found_at="2026-07-19 09:12", status="incident_created", incident_id=incident_id,
        details={"origin": RECOMPUTE_ORIGIN, "riskType": "inventory",
                 "material_id": key, "material": key, "materialName": f"{label}主控芯片"}))
    db.add(Incident(
        id=incident_id, tenant_id=tenant_id, code=f"INC-A04-{key}",
        title=f"{label}供应中断应急事件", type="supplier_shutdown", level="high",
        status="pending", owner="供应链负责人", source_risk_ids=[risk_id],
        loss=0, cost=0, notes=[]))
    db.flush()
    db.add(Task(id=f"task-a04-{key}", tenant_id=tenant_id, title="锁定替代供应商订单",
                source=f"INC-A04-{key}", incident_id=incident_id,
                assignee=f"user-{tenant_id}-scm_lead", role_code="buyer", status="pending",
                due_at="", priority="高", checklist=[]))


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for tenant_id, name in ((TENANT_A, "A04 真实租户 A"), (TENANT_B, "A04 隔离租户 B")):
            db.add(Tenant(id=tenant_id, name=name, industry="电子制造", scale="50-200",
                          status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        _user(db, TENANT_A, ACCOUNT_A, "A04 供应链负责人", "scm_lead", MANAGER_PERMISSIONS)
        _user(db, TENANT_A, ACCOUNT_BUYER, "A04 采购员", "buyer", BUYER_PERMISSIONS)
        _user(db, TENANT_A, ACCOUNT_NOINCIDENT, "A04 无事件权限用户", "limited",
              NO_INCIDENT_PERMISSIONS)
        _user(db, TENANT_B, ACCOUNT_B, "A04 隔离租户负责人", "scm_lead", MANAGER_PERMISSIONS)

        _network(db, TENANT_A, "MCU-A04", "A04")
        _risk_and_incident(db, TENANT_A, "MCU-A04", "A04")

        # 孤立物料：只有物料行，两跳内零关联 → 界面必须说"范围有限"，不能编造
        db.add(Material(id=f"mat-{TENANT_A}-lonely", tenant_id=TENANT_A,
                        material_id="MCU-A04-LONELY", material_name="A04孤立物料",
                        category="电子元器件", unit="片", daily_consumption=100,
                        unit_cost=5, is_critical=False))
        db.flush()
        db.add(Risk(
            id="risk-a04-lonely", tenant_id=TENANT_A, code="RISK-A04-LONELY", level="medium",
            type="库存", object_type="物料", object_name="A04孤立物料", score=55.0,
            rule="孤立物料测试风险", found_at="2026-07-19 09:20", status="new",
            details={"origin": RECOMPUTE_ORIGIN, "riskType": "inventory",
                     "material_id": "MCU-A04-LONELY", "material": "MCU-A04-LONELY"}))

        # 租户 B：实体名刻意全部不同，跨租户断言直接做页面文本比对
        _network(db, TENANT_B, "MCU-B04", "B租户专属")
        _risk_and_incident(db, TENANT_B, "MCU-B04", "B租户专属")
        db.commit()
    print(f"已生成 A04 验收租户：{TENANT_A} / {TENANT_B}")


if __name__ == "__main__":
    main()
