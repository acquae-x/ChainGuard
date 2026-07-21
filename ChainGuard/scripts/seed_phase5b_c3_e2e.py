"""Seed isolated tenants for the C3 Chromium acceptance scenario."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.webapi.auth.security import hash_password
from src.webapi.database import Base, SessionLocal, engine
from src.webapi.models import Risk, Role, Tenant, User


PASSWORD = "C3E2E@2026!"
TENANT_A, TENANT_B = "tenant-c3-e2e-a", "tenant-c3-e2e-b"
ADMIN_A, FINANCE_A, ADMIN_B = "c3-admin-a@chainguard.test", "c3-finance-a@chainguard.test", "c3-admin-b@chainguard.test"
RISK_ID = "risk-c3-e2e-a"


def _user(db, tenant_id: str, account: str, role_code: str, permissions: list[str]) -> None:
    role = Role(id=f"role-{tenant_id}-{role_code}", tenant_id=tenant_id, code=role_code, name=role_code, builtin=False, permissions=permissions)
    db.add(role); db.flush()
    db.add(User(id=f"user-{tenant_id}-{role_code}", tenant_id=tenant_id, account=account, password_hash=hash_password(PASSWORD), name=account, phone="", email=account, dept_id="dept-c3", role_id=role.id, role_code=role_code, status="active", data_scope="all"))


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(Tenant(id=TENANT_A, name="C3 空租户 A", industry="电子制造", scale="50-200", status="initializing", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        _user(db, TENANT_A, ADMIN_A, "scm_lead", ["dashboard:view", "risk:view", "incident:view", "risk:event:create", "decision:view", "decision:modify", "data:import", "data:view", "task:execute"])
        _user(db, TENANT_A, FINANCE_A, "finance", ["dashboard:view", "risk:view", "incident:view", "decision:view"])
        db.add(Tenant(id=TENANT_B, name="C3 隔离租户 B", industry="电子制造", scale="50-200", status="initializing", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        _user(db, TENANT_B, ADMIN_B, "scm_lead", ["dashboard:view", "risk:view", "incident:view", "risk:event:create", "decision:view", "decision:modify", "data:import", "data:view"])
        db.add(Risk(id=RISK_ID, tenant_id=TENANT_A, code="RISK-C3-001", level="high", type="供应", object_type="物料", object_name="C3 真实 MCU", score=91, rule="供应延误", found_at=datetime.now(timezone.utc).isoformat(), status="new", details={"material_id": "C3-MAT-001", "supplier_id": "C3-SUP-001", "estimated_delay_hours": 36}))
        db.commit()


if __name__ == "__main__":
    main()
