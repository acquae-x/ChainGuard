"""Seed two isolated tenants and a C1-ready risk for ERP Chromium acceptance."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.webapi.auth.security import hash_password
from src.webapi.database import Base, SessionLocal, engine
from src.webapi.models import Risk, Role, Tenant, User


PASSWORD = "ErpE2E@2026!"
PERMISSIONS = ["dashboard:view", "risk:view", "incident:view", "risk:event:create", "risk:manage", "decision:view", "decision:modify", "data:import", "data:view", "settings:manage", "task:view"]


def add_tenant(db, suffix: str, with_risk: bool) -> None:
    tenant_id = f"tenant-erp-e2e-{suffix}"
    tenant = Tenant(id=tenant_id, name=f"ERP E2E tenant {suffix}", industry="electronics", scale="50-200", status="initializing", plan="trial", trial_end_at="", demo_data_flag=False)
    db.add(tenant); db.flush()
    role = Role(id=f"role-erp-e2e-{suffix}", tenant_id=tenant_id, code="admin", name="ERP admin", builtin=False, permissions=PERMISSIONS)
    user = User(id=f"user-erp-e2e-{suffix}", tenant_id=tenant_id, account=f"erp-admin-{suffix}@chainguard.test", password_hash=hash_password(PASSWORD), name=f"ERP admin {suffix}", phone="", email=f"erp-admin-{suffix}@chainguard.test", dept_id="dept-erp", role_id=role.id, role_code="admin", status="active", data_scope="all")
    db.add(role); db.flush(); db.add(user)
    if with_risk:
        db.add(Risk(id="risk-erp-e2e-a", tenant_id=tenant_id, code="RISK-ERP-E2E-A", level="high", type="inventory", object_type="material", object_name="MAT-0001", score=92, rule="ERP material below safety stock", found_at="2026-07-19T00:00:00+00:00", status="new", details={"material_id": "MAT-0001", "supplier_id": "SUP-043", "estimated_delay_hours": 36}))


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        add_tenant(db, "a", True); add_tenant(db, "b", False); db.commit()


if __name__ == "__main__":
    main()
