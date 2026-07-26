"""Seed two non-demo tenants for the E-3 browser acceptance run."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.webapi.auth.security import hash_password
from src.webapi.database import Base, SessionLocal, engine
from src.webapi.entity_mapping import upsert_entities
from src.webapi.models import Incident, Risk, Role, Tenant, User


PASSWORD = "ExperienceE2E@2026!"
TENANT_A, TENANT_B = "tenant-e3-real-a", "tenant-e3-real-b"
ACCOUNT_A, ACCOUNT_B = "e3-real-a@chainguard.test", "e3-real-b@chainguard.test"
INCIDENT_ID = "inc-e3-real-a"


def _create_user(db, tenant_id: str, account: str, name: str) -> None:
    role = Role(
        id=f"role-{tenant_id}", tenant_id=tenant_id, code="scm_lead", name="供应链负责人",
        builtin=False,
        permissions=["dashboard:view", "risk:view", "incident:view", "risk:event:create", "decision:view", "decision:modify", "case:view", "task:execute"],
    )
    db.add(role); db.flush()
    db.add(User(
        id=f"user-{tenant_id}", tenant_id=tenant_id, account=account,
        password_hash=hash_password(PASSWORD), name=name, phone="", email=account,
        dept_id="dept-e3", role_id=role.id, role_code="scm_lead", status="active", data_scope="all",
    ))


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for tenant_id, account, name in ((TENANT_A, ACCOUNT_A, "E3 真实租户 A"), (TENANT_B, ACCOUNT_B, "E3 隔离租户 B")):
            db.add(Tenant(id=tenant_id, name=name, industry="电子制造", scale="50-200", status="active", plan="trial", trial_end_at="", demo_data_flag=False))
            db.flush(); _create_user(db, tenant_id, account, name)
        arrival = datetime.now(timezone.utc) + timedelta(hours=16)
        batches = [
            ("material", [{"material_id": "MAT-E3-001", "material_name": "E3 真实核心芯片", "daily_consumption": 240, "standard_cost": 13, "criticality": "critical"}]),
            ("supplier", [{"supplier_id": "SUP-E3-001", "supplier_name": "E3 备用供应商", "status": "active", "reliability_score": 96}]),
            ("supplier_material", [{"supplier_material_id": "SM-E3-001", "supplier_id": "SUP-E3-001", "material_id": "MAT-E3-001", "qualified": True, "supplier_rank": 1, "lead_time_hours": 30, "available_emergency_qty": 220, "emergency_cost_multiplier": 1.4, "unit_cost": 17}]),
            ("customer", [{"customer_id": "CUS-E3-001", "customer_name": "E3 A级客户", "customer_level": "A"}]),
            ("order", [{"sales_order_id": "SO-E3-001", "customer_id": "CUS-E3-001", "order_status": "pending", "promised_delivery_at": (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat(), "order_amount": 180_000, "gross_profit": 45_000, "penalty_cost": 36_000}]),
            ("order_line", [{"sales_order_line_id": "SOL-E3-001", "sales_order_id": "SO-E3-001", "line_no": 1, "material_id": "MAT-E3-001", "ordered_qty": 140, "unit_price": 20}]),
            ("inventory", [{"inventory_id": "INV-E3-001", "material_id": "MAT-E3-001", "warehouse_id": "W-E3", "warehouse_name": "E3 仓", "on_hand_qty": 25, "available_qty": 20, "safety_stock_qty": 80, "in_transit_qty": 30, "planned_arrival_at": arrival.isoformat(), "estimated_arrival_at": (arrival + timedelta(hours=10)).isoformat()}]),
        ]
        for resource_type, rows in batches:
            result = upsert_entities(db, TENANT_A, resource_type, rows)
            assert result["inserted"] == 1, result
        db.add(Risk(id="risk-e3-real-a", tenant_id=TENANT_A, code="RISK-E3-001", level="high", type="供应", object_type="物料", object_name="MAT-E3-001", score=91, rule="供应延误", found_at=datetime.now(timezone.utc).isoformat(), status="incident_created", details={"material_id": "MAT-E3-001", "supplier_id": "SUP-E3-001", "estimated_delay_hours": 42}, incident_id=INCIDENT_ID))
        db.add(Incident(id=INCIDENT_ID, tenant_id=TENANT_A, code="INC-E3-001", title="E3 真实租户经验闭环", type="supplier_shutdown", level="high", status="planning", owner="E3 真实租户 A", source_risk_ids=["risk-e3-real-a"], loss=0, cost=0))
        db.commit()


if __name__ == "__main__":
    main()
