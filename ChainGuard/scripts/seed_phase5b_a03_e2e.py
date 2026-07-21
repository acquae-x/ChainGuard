"""Seed two isolated tenants for the Phase 5B A03 risk-explanation browser acceptance run.

租户 A：一个会触发的物料（可解释）+ 一个缺库存的物料（数据不足降级）+ 一个只读账号（无 risk:manage）。
租户 B：自有物料，用于跨租户隔离断言。
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
    InventoryEntity,
    Material,
    Risk,
    Role,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    Tenant,
    User,
)
from src.webapi.risk_recompute import EXTERNAL_ORIGIN

PASSWORD = "RiskExplainE2E@2026!"
TENANT_A, TENANT_B = "tenant-a03-real-a", "tenant-a03-real-b"
ACCOUNT_A = "a03-real-a@chainguard.test"
ACCOUNT_VIEWER = "a03-viewer-a@chainguard.test"
ACCOUNT_B = "a03-real-b@chainguard.test"

MANAGER_PERMISSIONS = [
    "dashboard:view", "risk:view", "incident:view", "risk:manage", "risk:event:create",
    "decision:view", "field:cost:view", "field:profit:view", "field:customerLevel:view",
    "field:supplierPrice:view",
]
# 只读账号：能看风险、能看解释，但没有 risk:manage，因此看不到「重新扫描风险」。
VIEWER_PERMISSIONS = ["dashboard:view", "risk:view", "incident:view"]


def _user(db, tenant_id: str, account: str, name: str, code: str, permissions: list[str]) -> None:
    role = Role(id=f"role-{tenant_id}-{code}", tenant_id=tenant_id, code=code,
                name=name, builtin=False, permissions=permissions)
    db.add(role)
    db.flush()
    db.add(User(
        id=f"user-{tenant_id}-{code}", tenant_id=tenant_id, account=account,
        password_hash=hash_password(PASSWORD), name=name, phone="", email=account,
        dept_id="dept-a03", role_id=role.id, role_code=code, status="active", data_scope="all",
    ))


def _material(
    db, tenant_id: str, key: str, name: str, *, stock: float | None, daily: float = 480
) -> None:
    """stock=None 表示不落库存行，用于验收"数据不足降级"。"""
    now = datetime.now(timezone.utc)
    db.add(Material(id=f"mat-{tenant_id}-{key}", tenant_id=tenant_id, material_id=key,
                    material_name=name, category="电子元器件", unit="片",
                    daily_consumption=daily, unit_cost=45, is_critical=True))
    db.flush()
    if stock is not None:
        arrival = now + timedelta(days=30)
        db.add(InventoryEntity(
            id=f"inv-{tenant_id}-{key}", tenant_id=tenant_id, inventory_id=f"INV-{key}",
            material_id=key, warehouse_id=f"WH-{key}", warehouse_name=f"{name}专用仓",
            on_hand_qty=stock, available_qty=stock, safety_stock_qty=960, in_transit_qty=2000,
            planned_arrival_at=arrival, estimated_arrival_at=arrival + timedelta(hours=72),
        ))
    supplier_id = f"SUP-{key}"
    db.add(SupplierEntity(id=f"sup-{tenant_id}-{key}", tenant_id=tenant_id,
                          supplier_id=supplier_id, supplier_name=f"{name}供应商",
                          region="华东", status="可用", reliability_score=90))
    customer_id = f"CUS-{key}"
    db.add(CustomerEntity(id=f"cus-{tenant_id}-{key}", tenant_id=tenant_id,
                          customer_id=customer_id, customer_name=f"{name}关键客户",
                          customer_level="A", region="华东", contract="年度", owner="销售"))
    db.flush()
    db.add(SupplierMaterial(
        id=f"sm-{tenant_id}-{key}", tenant_id=tenant_id, supplier_material_id=f"SM-{key}",
        supplier_id=supplier_id, material_id=key, qualified=True, supplier_rank=1,
        available_emergency_qty=4000, lead_time_hours=96, emergency_cost_multiplier=1.35,
        supplier_price=48,
    ))
    order_id = f"SO-{key}"
    db.add(SalesOrder(id=f"so-{tenant_id}-{key}", tenant_id=tenant_id, sales_order_id=order_id,
                      customer_id=customer_id, order_status="confirmed",
                      promised_delivery_at=datetime.now(timezone.utc) + timedelta(days=5),
                      order_amount=1_800_000, gross_profit=None, penalty_cost=None))
    db.flush()
    db.add(SalesOrderLine(id=f"sol-{tenant_id}-{key}", tenant_id=tenant_id,
                          sales_order_line_id=f"SOL-{key}", sales_order_id=order_id, line_no=1,
                          material_id=key, ordered_qty=6000, unit_price=300))


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for tenant_id, name in ((TENANT_A, "A03 真实租户 A"), (TENANT_B, "A03 隔离租户 B")):
            db.add(Tenant(id=tenant_id, name=name, industry="电子制造", scale="50-200",
                          status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        _user(db, TENANT_A, ACCOUNT_A, "A03 供应链负责人", "scm_lead", MANAGER_PERMISSIONS)
        _user(db, TENANT_A, ACCOUNT_VIEWER, "A03 只读观察员", "viewer", VIEWER_PERMISSIONS)
        _user(db, TENANT_B, ACCOUNT_B, "A03 隔离租户负责人", "scm_lead", MANAGER_PERMISSIONS)

        # 会触发的物料：库存 300 / 小时消耗 20 → 支撑 15 小时，低于红线 24。
        _material(db, TENANT_A, "MCU-A03", "A03主控芯片", stock=300)
        # 没有库存行 → 解释接口必须返回 CG-2513 的可渲染限制，而不是编一个分数。
        _material(db, TENANT_A, "MCU-NOSTOCK", "A03无库存物料", stock=None)
        # 租户 B 自有物料，名称刻意不同，便于隔离断言做字符串比对。
        _material(db, TENANT_B, "MCU-B03", "B租户专属芯片", stock=300)

        # 外部录入型风险（E9）：供应商停产只能由外部告知，任何内部数据都算不出来。
        # 它不参与重算状态机，解释接口对它走 declared 分支——标注来源，不伪造指标推导。
        db.add(Risk(
            id="risk-a03-external", tenant_id=TENANT_A, code="RISK-A03-EXT-001",
            level="high", type="供应", object_type="供应商", object_name="A03主控芯片供应商",
            score=92, rule="核心供应商停产", found_at="2026-07-19 09:12", status="new",
            details={
                "origin": EXTERNAL_ORIGIN,
                "scoreSource": "declared_by_reporter",
                "reportedChannel": "供应商电话通知",
                "reportedBy": "A03 采购人员",
                "reportedAt": "2026-07-19 09:12",
                "supplier_id": "SUP-MCU-A03",
                "material_id": "MCU-A03",
                "material": "MCU-A03",
            },
        ))
        db.commit()
    print(f"已生成 A03 验收租户：{TENANT_A} / {TENANT_B}")


if __name__ == "__main__":
    main()
