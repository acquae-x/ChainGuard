from typing import Any


def _linear_score(value: float, low: float, high: float) -> float:
    if value <= low:
        return 100.0
    if value >= high:
        return 0.0
    return (high - value) / (high - low) * 100.0


def _require_fields(payload: dict[str, Any], fields: set[str], name: str) -> None:
    missing = sorted(fields - set(payload))
    if missing:
        raise ValueError(f"{name} 缺少字段：{', '.join(missing)}")


def calculate_inventory_risk(
    inventory: dict[str, Any],
    risk_weights: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    required_inventory_fields = {
        "current_stock",
        "hourly_consumption",
        "safety_stock",
        "planned_arrival_hours",
        "estimated_arrival_hours",
        "critical_order_demand",
        "external_risk_score",
    }
    _require_fields(inventory, required_inventory_fields, "inventory")
    _require_fields(risk_weights, {"inventory_risk_weights"}, "risk_weights")
    _require_fields(thresholds, {"inventory_warning"}, "thresholds")

    weights = risk_weights["inventory_risk_weights"]
    warning_thresholds = thresholds["inventory_warning"]

    _require_fields(
        weights,
        {"shortage_urgency", "order_importance", "transit_delay", "external_event"},
        "inventory_risk_weights",
    )
    _require_fields(
        warning_thresholds,
        {"yellow_support_hours", "red_support_hours", "inventory_risk_trigger"},
        "inventory_warning",
    )

    current_stock = float(inventory["current_stock"])
    hourly_consumption = float(inventory["hourly_consumption"])
    safety_stock = float(inventory["safety_stock"])
    planned_arrival_hours = float(inventory["planned_arrival_hours"])
    estimated_arrival_hours = float(inventory["estimated_arrival_hours"])
    critical_order_demand = float(inventory["critical_order_demand"])
    external_risk_score = float(inventory["external_risk_score"])

    if hourly_consumption <= 0:
        raise ValueError("hourly_consumption 必须大于 0。")
    if safety_stock <= 0:
        raise ValueError("safety_stock 必须大于 0。")
    if critical_order_demand < 0:
        raise ValueError("critical_order_demand 不能小于 0。")

    support_hours = current_stock / hourly_consumption
    safety_stock_gap = max(safety_stock - current_stock, 0)
    safety_stock_gap_rate = safety_stock_gap / safety_stock
    transit_delay_hours = estimated_arrival_hours - planned_arrival_hours
    critical_order_coverage_rate = (
        min(current_stock / critical_order_demand, 1)
        if critical_order_demand > 0
        else 1.0
    )

    shortage_urgency_score = _linear_score(support_hours, low=24, high=72)
    order_importance_score = (1 - critical_order_coverage_rate) * 100
    transit_delay_score = min(max(transit_delay_hours / 72 * 100, 0), 100)

    inventory_risk_index = (
        float(weights["shortage_urgency"]) * shortage_urgency_score
        + float(weights["order_importance"]) * order_importance_score
        + float(weights["transit_delay"]) * transit_delay_score
        + float(weights["external_event"]) * external_risk_score
    )

    if support_hours < float(warning_thresholds["red_support_hours"]):
        warning_level = "红色预警"
    elif support_hours < float(warning_thresholds["yellow_support_hours"]):
        warning_level = "黄色预警"
    else:
        warning_level = "正常"

    should_trigger_response = inventory_risk_index > float(warning_thresholds["inventory_risk_trigger"])

    explanation = [
        f"当前库存 {current_stock:.0f}，小时消耗 {hourly_consumption:.0f}，可支撑 {support_hours:.0f} 小时。",
        f"安全库存缺口 {safety_stock_gap:.0f}，缺口率 {safety_stock_gap_rate:.2%}。",
        f"在途到货预计延误 {transit_delay_hours:.0f} 小时。",
        f"关键订单覆盖率 {critical_order_coverage_rate:.2%}。",
        f"库存风险指数 {inventory_risk_index:.1f}，触发阈值 {warning_thresholds['inventory_risk_trigger']}。",
    ]
    if should_trigger_response:
        explanation.append("风险指数超过触发阈值，建议启动应急决策。")

    return {
        "support_hours": round(support_hours, 2),
        "safety_stock_gap": round(safety_stock_gap, 2),
        "safety_stock_gap_rate": round(safety_stock_gap_rate, 4),
        "transit_delay_hours": round(transit_delay_hours, 2),
        "critical_order_coverage_rate": round(critical_order_coverage_rate, 4),
        "shortage_urgency_score": round(shortage_urgency_score, 2),
        "order_importance_score": round(order_importance_score, 2),
        "transit_delay_score": round(transit_delay_score, 2),
        "external_risk_score": round(external_risk_score, 2),
        "inventory_risk_index": round(inventory_risk_index, 2),
        "warning_level": warning_level,
        "should_trigger_response": should_trigger_response,
        "explanation": explanation,
    }
