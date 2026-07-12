from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MANUAL_DECISION_HOURS: float = 6.0
ANNUAL_INCIDENT_COUNT: int = 12
SYSTEM_DECISION_MINUTES: int = 10


@dataclass(frozen=True)
class EconomicImpact:
    manual_covered_orders: list[str]
    system_covered_orders: list[str]

    manual_penalty: float
    system_penalty: float
    penalty_savings: float

    manual_lost_profit: float
    system_lost_profit: float
    profit_protected: float

    net_benefit: float
    annual_benefit_estimate: float

    manual_decision_hours: float
    system_decision_minutes: int

    note: str


def calculate_economic_impact(context: dict[str, Any]) -> EconomicImpact:
    orders = context.get("orders", [])
    inventory = context.get("inventory", {})
    suppliers = context.get("suppliers", [])

    _ZERO = EconomicImpact(
        manual_covered_orders=[], system_covered_orders=[],
        manual_penalty=0, system_penalty=0, penalty_savings=0,
        manual_lost_profit=0, system_lost_profit=0, profit_protected=0,
        net_benefit=0, annual_benefit_estimate=0,
        manual_decision_hours=MANUAL_DECISION_HOURS,
        system_decision_minutes=SYSTEM_DECISION_MINUTES,
        note="无订单数据，无法计算经济影响",
    )
    if not orders or not inventory:
        return _ZERO

    _PRIORITY = {"A": 0, "B": 1, "C": 2}
    sorted_orders = sorted(
        orders, key=lambda o: _PRIORITY.get(o.get("priority", "C"), 3)
    )

    # ── 人工基准：仅使用当前库存，满足整单需求则覆盖，否则跳过 ──
    manual_pool = float(inventory.get("current_stock", 0))
    manual_covered: list[str] = []
    for o in sorted_orders:
        demand = float(o.get("demand_qty", 0))
        if manual_pool >= demand:
            manual_covered.append(o["order_id"])
            manual_pool -= demand

    # ── 系统结果：对人工未覆盖订单，先用剩余库存再按优先级找最优可行供应商补采 ──
    system_pool = manual_pool  # 继承人工基准剩余库存（人工已分配后的未消耗部分）
    supplier_remaining: dict[str, float] = {
        s["supplier_id"]: float(s.get("available_qty", 0)) for s in suppliers
    }
    system_covered: list[str] = list(manual_covered)  # 继承人工已覆盖

    for o in sorted_orders:
        if o["order_id"] in system_covered:
            continue  # 已覆盖，跳过
        demand = float(o.get("demand_qty", 0))
        due_hours = float(o.get("due_hours", 24))
        shortfall = demand

        # 先使用剩余库存（人工分配后未消耗部分，系统可统一调配）
        stock_contribution = min(system_pool, shortfall)
        system_pool -= stock_contribution
        shortfall -= stock_contribution

        if shortfall <= 0:
            system_covered.append(o["order_id"])
            continue

        # 再按可靠性降序尝试供应商
        for s in sorted(suppliers, key=lambda x: float(x.get("reliability_score", 0)), reverse=True):
            total_lead = float(s.get("lead_time_hours", 9999)) + float(s.get("delay_hours", 0))
            if total_lead > due_hours:
                continue  # 无法及时到货
            avail = supplier_remaining.get(s["supplier_id"], 0.0)
            can_supply = min(avail, shortfall)
            if can_supply <= 0:
                continue
            supplier_remaining[s["supplier_id"]] -= can_supply
            shortfall -= can_supply
            if shortfall <= 0:
                break

        if shortfall <= 0:
            system_covered.append(o["order_id"])

    # ── 计算各项金额 ──
    manual_uncovered = [o for o in orders if o["order_id"] not in manual_covered]
    system_uncovered = [o for o in orders if o["order_id"] not in system_covered]

    manual_penalty = float(sum(o.get("penalty_cost", 0) for o in manual_uncovered))
    system_penalty = float(sum(o.get("penalty_cost", 0) for o in system_uncovered))
    manual_lost_profit = float(sum(o.get("gross_profit", 0) for o in manual_uncovered))
    system_lost_profit = float(sum(o.get("gross_profit", 0) for o in system_uncovered))

    penalty_savings = manual_penalty - system_penalty
    profit_protected = manual_lost_profit - system_lost_profit
    net_benefit = penalty_savings + profit_protected
    annual_estimate = net_benefit * ANNUAL_INCIDENT_COUNT

    return EconomicImpact(
        manual_covered_orders=manual_covered,
        system_covered_orders=system_covered,
        manual_penalty=manual_penalty,
        system_penalty=system_penalty,
        penalty_savings=penalty_savings,
        manual_lost_profit=manual_lost_profit,
        system_lost_profit=system_lost_profit,
        profit_protected=profit_protected,
        net_benefit=net_benefit,
        annual_benefit_estimate=annual_estimate,
        manual_decision_hours=MANUAL_DECISION_HOURS,
        system_decision_minutes=SYSTEM_DECISION_MINUTES,
        note=(
            "人工基准：仅使用当前库存按优先级分配（整单覆盖），无跨供应商协同。"
            "系统方案：在当前库存基础上，按订单优先级从最优可行供应商追加采购（及时性 + 可靠性优先）。"
            "所有金额为业务情景模型估算，非实际发生成本。"
        ),
    )
