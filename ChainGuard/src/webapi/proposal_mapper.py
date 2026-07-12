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
        cost = source.get("total_cost", source.get("cost", source.get("economic_cost", source.get("estimated_cost"))))
        score = float(source.get("total_score", source.get("score", 0)) or 0)
        agent = str(source.get("agent_name", source.get("name", "数据缺失")))
        mapped.append({
            "incident_id": incident_id,
            "name": str(source.get("proposal_name", source.get("proposal_title", source.get("name", source.get("title", "数据缺失"))))),
            "tag": TAGS[index],
            "total_cost": float(cost) if cost is not None else 0.0,
            "lead_time_impact": int(source.get("lead_time_impact", source.get("delay_days", 0)) or 0),
            "residual_risk": str(source.get("residual_risk", "数据缺失")),
            "customer_impact": int(source.get("customer_impact", 0) or 0),
            "high_value_customers": int(source.get("high_value_customers", 0) or 0),
            "reason": str(source.get("reason", source.get("description", source.get("proposal", "；".join(map(str, source.get("reasoning", []))) or (f"综合评分 {score:.2f}" if score else "数据缺失"))))),
            "views": {"采购": str(source.get("procurement_view", agent)), "物流": str(source.get("logistics_view", agent)), "财务": str(source.get("finance_view", agent)), "销售": str(source.get("sales_view", agent)), "生产": str(source.get("production_view", agent))},
            "constraints": constraints if isinstance(constraints, list) else [constraints],
            "explanation": {**(explanation if isinstance(explanation, dict) else {"summary": str(explanation)}), "dataMissing": [field for field, value in {"totalCost": cost, "customerImpact": source.get("customer_impact"), "highValueCustomers": source.get("high_value_customers")}.items() if value is None]},
        })
    return mapped
