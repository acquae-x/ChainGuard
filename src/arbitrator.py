from typing import Any


def arbitrate(
    proposals: list[dict[str, Any]],
    conflict_result: dict[str, Any],
    rebuttal: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Create the final deterministic arbitration result for the MVP."""
    inventory = context["inventory"]
    orders = context["orders"]
    critical_orders = [order for order in orders if order.get("priority") == "A"]

    best_score = max(float(proposal.get("total_score", 0)) for proposal in proposals)
    conflict_penalty = 2 if conflict_result.get("has_conflict") else 0
    rebuttal_bonus = 4 if rebuttal.get("suggested_revision") else 0
    final_score = min(100, round(best_score + rebuttal_bonus - conflict_penalty, 1))

    return {
        "final_decision_title": "关键订单空运 + 备用供应商补货 + 非关键订单延期沟通",
        "final_strategy": (
            f"围绕 {inventory['material_name']} 的断供风险，采用分级保障策略："
            "A类关键客户订单优先空运，B备用供应商紧急补货补齐库存缺口，"
            "B/C类非关键订单延期24-48小时并提前通知客户。"
        ),
        "adopted_opinions": [
            "采纳采购 Agent 的备用供应商建议：优先联系B备用供应商确认可供量。",
            "采纳物流 Agent 的关键订单空运建议：仅对A类关键客户订单使用空运。",
            "采纳财务 Agent 的客户分级保障建议：避免全量空运造成利润转负。",
        ],
        "rejected_opinions": [
            "拒绝全量空运，因为成本过高且可能利润转负。",
        ],
        "execution_plan": [
            "2小时内联系B备用供应商确认可供量。",
            f"对{len(critical_orders)}个A类关键客户订单采用空运。",
            "非关键订单延期24-48小时并通知客户。",
            "如果台风影响超过96小时，启动C第二备用供应商。",
        ],
        "manual_confirmation_points": [
            "是否接受空运成本。",
            "是否启用备用供应商。",
            "是否通知客户延期。",
        ],
        "expected_effect": {
            "support_hours_after_action": "预计由36小时提升至66小时以上，具体取决于B供应商确认量。",
            "delivery_risk": "A类关键客户交付风险显著下降。",
            "cost_risk": "成本风险中等，避免全量空运导致利润转负。",
            "customer_impact": "关键客户优先保障，非关键客户需沟通延期24-48小时。",
        },
        "final_score": final_score,
    }
