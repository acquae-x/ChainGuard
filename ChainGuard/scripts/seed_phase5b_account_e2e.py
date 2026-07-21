"""Seed isolated tenants for the Phase 5B「账户完善」Chromium acceptance scenario.

两个租户验证隔离：
  A —— 管理员 + 一个会被锁定的成员 + 一个无管理权限的成员；SSO 由 E2E 用例自己配置。
  B —— 另一家企业的管理员，用来证明邀请码/SSO/重置待办都看不见也管不着 A 家的。
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.webapi.auth.security import hash_password
from src.webapi.database import Base, SessionLocal, engine
from src.webapi.models import Role, Tenant, User


PASSWORD = "AcctE2E@2026!"
TENANT_A, TENANT_B = "tenant-acct-e2e-a", "tenant-acct-e2e-b"
ADMIN_A = "acct-admin-a@chainguard.test"
MEMBER_A = "acct-member-a@chainguard.test"
LOCKME_A = "acct-lockme-a@chainguard.test"
ADMIN_B = "acct-admin-b@chainguard.test"

# 与 seed.py 的内置 admin 对齐：集成页同时读 ERP 同步历史（需 data:import），
# 权限给少了页面会弹一条与本模块无关的"没有操作权限"，污染验收证据。
ADMIN_PERMISSIONS = [
    "dashboard:view", "risk:view", "incident:view",
    "settings:manage", "data:manage", "data:view", "data:import", "data:export",
    "decision:view", "task:view", "report:view", "audit:view", "user:manage", "role:manage",
]
MEMBER_PERMISSIONS = ["dashboard:view", "risk:view", "incident:view", "decision:view"]


def _role(db, tenant_id: str, code: str, permissions: list[str]) -> Role:
    role = Role(id=f"role-{tenant_id}-{code}", tenant_id=tenant_id, code=code, name=code,
                builtin=False, permissions=permissions)
    db.add(role)
    db.flush()
    return role


def _user(db, tenant_id: str, account: str, role: Role) -> None:
    db.add(User(id=f"user-{tenant_id}-{role.code}-{account.split('@')[0]}", tenant_id=tenant_id,
                account=account, password_hash=hash_password(PASSWORD), name=account.split("@")[0],
                phone="", email=account, dept_id="dept-1", role_id=role.id, role_code=role.code,
                status="active", data_scope="all"))


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(Tenant(id=TENANT_A, name="账户完善验收企业 A", industry="电子制造", scale="50-200",
                      status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        admin_a = _role(db, TENANT_A, "admin", ADMIN_PERMISSIONS)
        buyer_a = _role(db, TENANT_A, "buyer", MEMBER_PERMISSIONS)
        _role(db, TENANT_A, "auditor", MEMBER_PERMISSIONS)
        _user(db, TENANT_A, ADMIN_A, admin_a)
        _user(db, TENANT_A, MEMBER_A, buyer_a)
        _user(db, TENANT_A, LOCKME_A, buyer_a)

        db.add(Tenant(id=TENANT_B, name="账户完善隔离企业 B", industry="电子制造", scale="50-200",
                      status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        admin_b = _role(db, TENANT_B, "admin", ADMIN_PERMISSIONS)
        _role(db, TENANT_B, "buyer", MEMBER_PERMISSIONS)
        _user(db, TENANT_B, ADMIN_B, admin_b)
        db.commit()
    print(f"seeded {TENANT_A} / {TENANT_B}", flush=True)


if __name__ == "__main__":
    main()
