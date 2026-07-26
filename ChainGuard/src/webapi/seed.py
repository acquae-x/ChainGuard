from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .auth.security import hash_password
from .database import Base, SessionLocal, engine
from .models import (
    Approval,
    CustomerEntity,
    Department,
    ExperienceCard,
    Incident,
    InventoryEntity,
    Material,
    NotificationMessage,
    Proposal,
    Risk,
    Role,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    Tenant,
    User,
)
from .risk_recompute import EXTERNAL_ORIGIN, recompute_inventory_risks, risk_id_for_material


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


def _seed_demo_entities(db, tenant_id: str) -> None:
    """演示租户的结构化实体：风险分数由这些行算出，而不是写死在 Risk 上。

    数值取向：MCU-A9 库存 300、小时消耗 20 → 支撑 15 小时（低于 red 24 → 红色预警）；
    A 级订单需求 6000 → 关键订单覆盖率 5%；在途预计延误 72 小时。
    这三项经 config/risk_weights.yaml 加权后使风险指数高于 trigger 70 而触发。
    到货时间取"seed 之后 30 天"，避免演示库放置数日后延误项归零导致风险自动消除。
    """
    now = datetime.now(timezone.utc)
    db.add(Material(id="mat-mcu-a9", tenant_id=tenant_id, material_id="MCU-A9", material_name="MCU-A9 主控芯片", category="电子元器件", unit="片", daily_consumption=480, unit_cost=45, is_critical=True))
    # 复合外键指向 (tenant_id, material_id) 而非主键，SQLAlchemy 推不出插入顺序，必须显式 flush。
    db.flush()
    db.add(InventoryEntity(id="inv-mcu-a9-sh", tenant_id=tenant_id, inventory_id="INV-SH-001", material_id="MCU-A9", warehouse_id="WH-SH-01", warehouse_name="上海一仓", on_hand_qty=300, available_qty=300, safety_stock_qty=960, in_transit_qty=2000, planned_arrival_at=now + timedelta(days=30), estimated_arrival_at=now + timedelta(days=30, hours=72)))
    db.add_all([
        SupplierEntity(id="sup-sz-01", tenant_id=tenant_id, supplier_id="SUP-SZ-01", supplier_name="苏州芯片封测厂", region="江苏苏州", status="受事件影响", reliability_score=92),
        SupplierEntity(id="sup-hz-02", tenant_id=tenant_id, supplier_id="SUP-HZ-02", supplier_name="杭州微电子", region="浙江杭州", status="可用", reliability_score=85),
    ])
    db.add(CustomerEntity(id="cus-001", tenant_id=tenant_id, customer_id="CUST-001", customer_name="江苏智能装备", customer_level="A", region="江苏南京", contract="年度框架", owner="销售/客服"))
    db.flush()
    db.add_all([
        SupplierMaterial(id="sm-sz-01", tenant_id=tenant_id, supplier_material_id="SM-SZ-01", supplier_id="SUP-SZ-01", material_id="MCU-A9", qualified=True, supplier_rank=1, available_emergency_qty=4000, lead_time_hours=96, emergency_cost_multiplier=1.35, supplier_price=48),
        SupplierMaterial(id="sm-hz-02", tenant_id=tenant_id, supplier_material_id="SM-HZ-02", supplier_id="SUP-HZ-02", material_id="MCU-A9", qualified=True, supplier_rank=2, available_emergency_qty=2500, lead_time_hours=60, emergency_cost_multiplier=1.60, supplier_price=52),
    ])
    # 违约金与毛利取自合同条款而非估算：CUST-001 是 A 级年度框架客户，逾期违约金
    # 按合同额 20%（360000）、毛利按 25%（450000）。这两个字段留空时上下文构建器会用
    # A 类估算系数补齐并把决策标记为 degraded——演示租户没有理由缺这两个已知数字。
    db.add(SalesOrder(id="so-88019", tenant_id=tenant_id, sales_order_id="SO-88019", customer_id="CUST-001", order_status="confirmed", promised_delivery_at=now + timedelta(days=5), order_amount=1800000, gross_profit=450000, penalty_cost=360000))
    db.flush()
    db.add(SalesOrderLine(id="sol-88019-1", tenant_id=tenant_id, sales_order_line_id="SOL-88019-1", sales_order_id="SO-88019", line_no=1, material_id="MCU-A9", ordered_qty=6000, unit_price=300))


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
        tenant = Tenant(id="tenant-demo", name="华东精密制造有限公司", industry="电子制造", scale="200-1000", status="active", plan="trial", trial_end_at=(datetime.now() + timedelta(days=30)).date().isoformat(), demo_data_flag=True, timezone="Asia/Shanghai")
        db.add(tenant)
        # PostgreSQL 强制外键：先落库租户，再插角色/用户，固定语句顺序（SQLite 不校验外键掩盖了该问题）
        db.flush()
        # 部门树：一级为公司本部，五个业务部门挂在它下面。
        # 有了层级，「本部门及子部门」这一档数据范围才真正可求值（见 data_scope.py）。
        db.add(Department(id="dept-root", tenant_id=tenant.id, code="D0", name="公司本部", parent_id=None))
        db.flush()
        for index, dept_name in enumerate(["采购部", "仓储部", "销售部", "财务部", "生产部"], start=1):
            db.add(Department(id=f"dept-{index}", tenant_id=tenant.id, code=f"D{index}", name=dept_name, parent_id="dept-root"))
        db.flush()
        password_hash = hash_password(password)
        for index, (code, name) in enumerate(ROLE_NAMES.items()):
            role = Role(id=f"role-{code}", tenant_id=tenant.id, code=code, name=name, builtin=True, permissions=[*BASE, *ROLE_PERMISSIONS[code]])
            db.add(role)
            db.flush()
            db.add(User(id=f"u-{code}", tenant_id=tenant.id, account=f"{code}@chainguard.demo", password_hash=password_hash, name=name, phone=f"1380000000{index + 1}", email=f"{code}@chainguard.demo", dept_id=f"dept-{index % 5 + 1}", role_id=role.id, role_code=code, status="active", data_scope="all" if code in {"admin", "boss", "scm_lead", "finance", "auditor"} else "custom"))
        _seed_demo_entities(db, tenant.id)
        db.flush()

        # risk-1：供应商停产是**外部输入**，没有任何内部数据能算出"这家厂停产了"。
        # 因此它保留为录入型风险，但标注来源与录入信息，score 明示为申报值而非计算值——
        # A03 的解释区据此展示"来源=外部事件录入"，不伪造指标推导。
        db.add(Risk(
            id="risk-1", tenant_id=tenant.id, code="RISK-20260709-001", level="high", type="供应",
            object_type="供应商", object_name="苏州芯片封测厂", score=92, rule="核心供应商停产",
            found_at="2026-07-09 09:12", status="incident_created", incident_id="inc-supplier-shutdown",
            details={
                "origin": EXTERNAL_ORIGIN,
                "scoreSource": "declared_by_reporter",
                "reportedChannel": "供应商电话通知",
                "reportedBy": "采购人员",
                "reportedAt": "2026-07-09 09:12",
                # 停产时长同样是**申报值**（供应商电话告知"预计停产 72 小时"），不是系统推导。
                # 高风险事件必须有预计延误，否则 context_builder 按 CG-2514 阻断推演——
                # 缺了它演示租户根本生成不出方案，而这个 72 小时正是经验卡 EXP-019 的口径。
                "estimated_delay_hours": 72,
                "delaySource": "declared_by_reporter",
                "supplier_id": "SUP-SZ-01",
                "supplier": "苏州芯片封测厂",
                "material_id": "MCU-A9",
                "material": "MCU-A9",
            },
        ))
        # risk-2 的替代者：分数不再写死，由 recompute 用上面刚落库的实体算出来。
        recompute_inventory_risks(db, tenant.id, commit=False)
        computed_risk_id = risk_id_for_material(tenant.id, "MCU-A9")
        computed = db.get(Risk, computed_risk_id)
        if computed is not None:
            computed.status, computed.incident_id = "incident_created", "inc-supplier-shutdown"
        source_risk_ids = ["risk-1", *([computed_risk_id] if computed is not None else [])]

        # 演示事件归属供应链负责人；方案继承事件归属。没有这两列，
        # 一旦把某个账号的数据范围调成 dept/own，演示数据就会整片消失。
        scm_lead = db.get(User, "u-scm_lead")
        owner_id = scm_lead.id if scm_lead else None
        owner_dept = scm_lead.dept_id if scm_lead else None

        incident = Incident(id="inc-supplier-shutdown", tenant_id=tenant.id, code="INC-20260709-001", title="苏州芯片封测厂突发停产影响 MCU-A9 供应", type="supplier_shutdown", level="high", status="approving", owner="供应链负责人", owner_id=owner_id, dept_id=owner_dept, source_risk_ids=source_risk_ids, loss=860000, cost=128000)
        db.add(incident)
        for pid, name, tag, cost, days, residual, customers in [("prop-1", "双供应商加急补货", "recommended", 128000, 2, "low", 3), ("prop-2", "全量替代供应商切换", "alternative", 196000, 1, "medium", 2), ("prop-3", "等待原供应商恢复", "invalid", 32000, 7, "high", 11)]:
            db.add(Proposal(id=pid, tenant_id=tenant.id, incident_id=incident.id, name=name, tag=tag, total_cost=cost, lead_time_impact=days, residual_risk=residual, customer_impact=customers, high_value_customers=1, reason="与 supplier_shutdown 演示数据链对齐", views={"采购": name}, constraints=[], explanation={"evidence": ["EXP-019", "安全库存阈值"]}, owner_id=owner_id, dept_id=owner_dept))
        db.add(Approval(id="ap-1", tenant_id=tenant.id, proposal_id="prop-1", incident_id=incident.id, status="submitted", risk_level="high", summary="双供应商加急补货，预计延误 2 天", cost_impact=128000, submitter="供应链负责人", waiting_hours=1.2, cc_role_codes=["finance"], history=[]))
        db.add(ExperienceCard(id="EXP-019", tenant_id=tenant.id, title="核心芯片供应商停产 72 小时应急", content={"trigger": "核心供应商停产", "action": "双供应商加急+首批空运"}, status="verified"))
        db.add(NotificationMessage(id="notification-ap-1", tenant_id=tenant.id, kind="approval", title="双供应商加急补货待审批", target="/decision/approval/ap-1"))
        db.commit()
        print("已生成演示租户、9 个账号和 supplier_shutdown 完整数据链。")


if __name__ == "__main__":
    seed()
