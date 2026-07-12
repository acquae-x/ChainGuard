from __future__ import annotations

from typing import Any

from src.domain_models import DecisionResult


TAGS = ("recommended", "alternative", "invalid")


def map_decision_result(result: DecisionResult | dict[str, Any], incident_id: str) -> list[dict[str, Any]]:
    """把决策引擎结果稳定映射为前端三方案契约。"""
    data = result.to_dict() if hasattr(result, "to_dict") else result
    raw = list(data.get("proposals") or [])
    explanation = data.get("explanation") or {}
    constraints = data.get("constraint_analysis") or {}
    mapped: list[dict[str, Any]] = []
    for index in range(3):
        source = raw[index] if index < len(raw) else {}
        cost = source.get("total_cost", source.get("cost", source.get("economic_cost", 0)))
        score = float(source.get("total_score", source.get("score", 0)) or 0)
        agent = str(source.get("agent_name", source.get("name", f"方案{index + 1}")))
        # 决策引擎当前没有稳定输出以下前端字段；按方案序位填充的是兼容占位值，
        # 待 Incident 上下文直连引擎后应改为真实约束与影响评估结果。
        mapped.append({
            "incident_id": incident_id,
            "name": str(source.get("proposal_name", source.get("title", agent))),
            "tag": TAGS[index],
            "total_cost": float(cost or 0),
            "lead_time_impact": int(source.get("lead_time_impact", source.get("delay_days", index + 1)) or 0),
            "residual_risk": "low" if index == 0 else "medium" if index == 1 else "high",
            "customer_impact": int(source.get("customer_impact", index * 4 + 2) or 0),
            "high_value_customers": int(source.get("high_value_customers", min(index + 1, 4)) or 0),
            "reason": str(source.get("reason", source.get("description", f"综合评分 {score:.2f}"))),
            "views": {"采购": str(source.get("procurement_view", agent)), "物流": str(source.get("logistics_view", agent)), "财务": str(source.get("finance_view", agent)), "销售": str(source.get("sales_view", agent)), "生产": str(source.get("production_view", agent))},
            "constraints": constraints if isinstance(constraints, list) else [constraints],
            "explanation": explanation if isinstance(explanation, dict) else {"summary": str(explanation)},
        })
    return mapped
