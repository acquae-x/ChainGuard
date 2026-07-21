"""Seed two isolated tenants plus a no-settings user for ERP mapping acceptance."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.webapi.auth.security import hash_password
from src.webapi.database import Base, SessionLocal, engine
from src.webapi.models import Role, Tenant, User


PASSWORD = "MapE2E@2026!"
ADMIN_PERMISSIONS = ["dashboard:view", "risk:view", "decision:view", "data:import", "data:view", "settings:manage", "task:view"]
# 只导入、不能管理设置：用于验证映射读写受 settings:manage 收敛。
IMPORTER_PERMISSIONS = ["dashboard:view", "risk:view", "data:import", "data:view"]


def add_tenant(db, suffix: str, with_importer: bool) -> None:
    tenant_id = f"tenant-map-e2e-{suffix}"
    db.add(Tenant(id=tenant_id, name=f"Mapping E2E tenant {suffix}", industry="electronics", scale="50-200", status="initializing", plan="trial", trial_end_at="", demo_data_flag=False))
    db.flush()
    admin_role = Role(id=f"role-map-admin-{suffix}", tenant_id=tenant_id, code="admin", name="实施管理员", builtin=False, permissions=ADMIN_PERMISSIONS)
    db.add(admin_role)
    db.flush()
    db.add(User(id=f"user-map-admin-{suffix}", tenant_id=tenant_id, account=f"map-admin-{suffix}@chainguard.test", password_hash=hash_password(PASSWORD), name=f"实施管理员 {suffix.upper()}", phone="", email=f"map-admin-{suffix}@chainguard.test", dept_id="dept-erp", role_id=admin_role.id, role_code="admin", status="active", data_scope="all"))
    if with_importer:
        importer_role = Role(id=f"role-map-importer-{suffix}", tenant_id=tenant_id, code="operator", name="数据导入员", builtin=False, permissions=IMPORTER_PERMISSIONS)
        db.add(importer_role)
        db.flush()
        db.add(User(id=f"user-map-importer-{suffix}", tenant_id=tenant_id, account=f"map-importer-{suffix}@chainguard.test", password_hash=hash_password(PASSWORD), name=f"数据导入员 {suffix.upper()}", phone="", email=f"map-importer-{suffix}@chainguard.test", dept_id="dept-erp", role_id=importer_role.id, role_code="operator", status="active", data_scope="all"))


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        add_tenant(db, "a", True)
        add_tenant(db, "b", False)
        db.commit()


if __name__ == "__main__":
    main()
