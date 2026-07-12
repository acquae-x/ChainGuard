from __future__ import annotations

import os
from datetime import datetime, timedelta

from .auth.security import hash_password
from .database import Base, SessionLocal, engine
from .models import Approval, ExperienceCard, Incident, NotificationMessage, Proposal, Risk, Role, Tenant, User


ROLE_NAMES = {"admin": "企业管理员", "boss": "老板/总经理", "scm_lead": "供应链负责人", "buyer": "采购人员", "warehouse": "仓库人员", "sales": "销售/客服", "finance": "财务人员", "planner": "生产计划人员", "auditor": "只读审计"}
BASE = ["dashboard:view", "risk:view", "incident:view"]
ROLE_PERMISSIONS = {
    # 管理员补齐业务只读码，但不添加 readonly，以免前端隐藏管理员写操作。
    "admin": ["settings:manage", "data:manage", "data:view", "data:import", "data:export", "decision:view", "task:view", "report:view", "audit:view", "user:manage", "role:manage"],
    "boss": ["risk:event:create", "decision:view", "approval:low", "approval:medium", "approval:high", "task:view", "case:view", "report:executive", "field:cost:view", "field:profit:view", "field:contract:view", "field:customerLevel:view", "field:supplierPrice:view", "data:export", "audit:view"],
    "scm_lead": ["risk:event:create", "risk:manage", "decision:view", "decision:modify", "approval:low", "approval:medium", "approval:submit_high", "task:execute", "task:manage", "data:manage", "data:import", "data:export", "case:view", "report:operation", "settings:approval", "field:cost:view", "field:profit:view", "field:contract:view", "field:customerLevel:view", "field:supplierPrice:view"],
    "buyer": ["risk:event:create", "risk:manage:own", "decision:view:purchase", "decision:modify:purchase", "task:execute", "data:supplier:manage", "data:import:own", "case:view", "report:purchase"],
    "warehouse": ["risk:event:create", "risk:manage:warehouse", "task:execute", "data:inventory:manage", "data:import:inventory"],
    "sales": ["risk:event:create", "risk:manage:order", "decision:view:sales", "task:execute", "data:customer:manage", "data:order:manage", "data:import:order", "case:view", "report:order", "field:customerLevel:view", "field:contract:view"],
    "finance": ["decision:view:finance", "approval:countersign", "task:execute", "report:cost", "field:cost:view", "field:profit:view", "field:customerLevel:view", "field:contract:view", "data:export"],
    "planner": ["risk:event:create", "risk:manage:material", "decision:view:production", "decision:modify:production", "task:execute", "data:material:manage", "data:import:material", "case:view", "report:planner"],
    "auditor": ["readonly", "decision:view", "task:view", "case:view", "report:view", "audit:view", "audit:export", "data:view"],
}


def seed() -> None:
    password = os.getenv("SEED_DEMO_PASSWORD")
    if not password:
        raise RuntimeError("请先通过环境变量 SEED_DEMO_PASSWORD 设置演示账号密码")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.get(Tenant, "tenant-demo"):
            # 升级既有演示库时同步内置角色权限，不影响租户自定义角色。
            for code, permissions in ROLE_PERMISSIONS.items():
                role = db.get(Role, f"role-{code}")
                if role is not None and role.builtin:
                    role.permissions = [*BASE, *permissions]
            db.commit()
            print("演示数据已存在，跳过 seed。")
            return
        tenant = Tenant(id="tenant-demo", name="华东精密制造有限公司", industry="电子制造", scale="200-1000", status="active", plan="trial", trial_end_at=(datetime.now() + timedelta(days=30)).date().isoformat(), demo_data_flag=True)
        db.add(tenant)
        # PostgreSQL 强制外键：先落库租户，再插角色/用户，固定语句顺序（SQLite 不校验外键掩盖了该问题）
        db.flush()
        password_hash = hash_password(password)
        for index, (code, name) in enumerate(ROLE_NAMES.items()):
            role = Role(id=f"role-{code}", tenant_id=tenant.id, code=code, name=name, builtin=True, permissions=[*BASE, *ROLE_PERMISSIONS[code]])
            db.add(role)
            db.flush()
            db.add(User(id=f"u-{code}", tenant_id=tenant.id, account=f"{code}@chainguard.demo", password_hash=password_hash, name=name, phone=f"1380000000{index + 1}", email=f"{code}@chainguard.demo", dept_id=f"dept-{index % 5 + 1}", role_id=role.id, role_code=code, status="active", data_scope="all" if code in {"admin", "boss", "scm_lead", "finance", "auditor"} else "custom"))
        db.add_all([
            Risk(id="risk-1", tenant_id=tenant.id, code="RISK-20260709-001", level="high", type="供应", object_type="供应商", object_name="苏州芯片封测厂", score=92, rule="核心供应商停产", found_at="2026-07-09 09:12", status="incident_created", details={"supplier": "苏州芯片封测厂", "material": "MCU-A9"}, incident_id="inc-supplier-shutdown"),
            Risk(id="risk-2", tenant_id=tenant.id, code="RISK-20260709-002", level="medium", type="库存", object_type="物料", object_name="MCU-A9", score=73, rule="安全库存低于 20%", found_at="2026-07-09 10:21", status="incident_created", details={"warehouse": "上海一仓", "material": "MCU-A9"}, incident_id="inc-supplier-shutdown"),
        ])
        incident = Incident(id="inc-supplier-shutdown", tenant_id=tenant.id, code="INC-20260709-001", title="苏州芯片封测厂突发停产影响 MCU-A9 供应", type="supplier_shutdown", level="high", status="approving", owner="供应链负责人", source_risk_ids=["risk-1", "risk-2"], loss=860000, cost=128000)
        db.add(incident)
        for pid, name, tag, cost, days, residual, customers in [("prop-1", "双供应商加急补货", "recommended", 128000, 2, "low", 3), ("prop-2", "全量替代供应商切换", "alternative", 196000, 1, "medium", 2), ("prop-3", "等待原供应商恢复", "invalid", 32000, 7, "high", 11)]:
            db.add(Proposal(id=pid, tenant_id=tenant.id, incident_id=incident.id, name=name, tag=tag, total_cost=cost, lead_time_impact=days, residual_risk=residual, customer_impact=customers, high_value_customers=1, reason="与 supplier_shutdown 演示数据链对齐", views={"采购": name}, constraints=[], explanation={"evidence": ["EXP-019", "安全库存阈值"]}))
        db.add(Approval(id="ap-1", tenant_id=tenant.id, proposal_id="prop-1", incident_id=incident.id, status="submitted", risk_level="high", summary="双供应商加急补货，预计延误 2 天", cost_impact=128000, submitter="供应链负责人", waiting_hours=1.2, cc_role_codes=["finance"], history=[]))
        db.add(ExperienceCard(id="EXP-019", tenant_id=tenant.id, title="核心芯片供应商停产 72 小时应急", content={"trigger": "核心供应商停产", "action": "双供应商加急+首批空运"}, status="verified"))
        db.add(NotificationMessage(id="notification-ap-1", tenant_id=tenant.id, kind="approval", title="双供应商加急补货待审批", target="/decision/approval/ap-1"))
        db.commit()
        print("已生成演示租户、9 个账号和 supplier_shutdown 完整数据链。")


if __name__ == "__main__":
    seed()
