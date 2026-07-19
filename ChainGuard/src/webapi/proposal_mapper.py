from __future__ import annotations

import math
from typing import Any

from src.domain_models import DecisionResult


TAGS = ("recommended", "alternative", "invalid")

# P0-2 口径（方案列表/审批摘要/方案对比共用）：
# - 引擎 proposals 自身不带 ¥ 成本、交期天数、客户数等结构化字段；
#   这些信息可信的来源是 DecisionResult 的 context（orders/suppliers/inventory）与 scores。
# - 能从可信字段映射的必须映射；不能推导的返回 None，由前端显示"数据缺失"。
# - 禁止把未知值伪装成 0。


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _first_number(source: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _number(source.get(key))
        if value is not None:
            return value
    return None


def _affected_orders(context: dict[str, Any]) -> list[dict[str, Any]] | None:
    """事件影响面来自 context.orders（可信）；context 无订单段时返回 None（缺失≠0）。"""
    if "orders" not in context:
        return None
    orders = [item for item in (context.get("orders") or []) if isinstance(item, dict)]
    material_id = (context.get("inventory") or {}).get("material_id")
    if material_id:
        scoped = [item for item in orders if not item.get("required_material") or item.get("required_material") == material_id]
        return scoped
    return orders


def _supplier_lead_days(source: dict[str, Any], context: dict[str, Any]) -> int | None:
    """交期影响：方案标题/正文点名了具体供应商时，取该供应商 context 交期（多家取瓶颈）。"""
    text = f"{source.get('proposal_title') or ''}\n{source.get('proposal') or ''}"
    hours: list[float] = []
    for supplier in context.get("suppliers") or []:
        if not isinstance(supplier, dict):
            continue
        name = str(supplier.get("supplier_name") or "").strip()
        lead = _number(supplier.get("lead_time_hours"))
        if name and lead is not None and name in text:
            hours.append(lead)
    if not hours:
        return None
    return int(math.ceil(max(hours) / 24.0))


def _residual_risk(source: dict[str, Any]) -> str | None:
    """剩余风险来自引擎 scores.risk_reduction（0-100，越高风险越低）；无评分则缺失。"""
    value = _number((source.get("scores") or {}).get("risk_reduction"))
    if value is None:
        return None
    return "low" if value >= 70 else "medium" if value >= 40 else "high"


def map_decision_result(result: DecisionResult | dict[str, Any], incident_id: str) -> list[dict[str, Any]]:
    """把决策引擎结果稳定映射为前端三方案契约。"""
    data = result.to_dict() if hasattr(result, "to_dict") else result
    raw = list(data.get("proposals") or [])
    explanation = data.get("explanation") or {}
    constraints = data.get("constraint_analysis") or {}
    context = data.get("context") or {}
    orders = _affected_orders(context)
    customer_impact = len(orders) if orders is not None else None
    high_value_customers = sum(1 for item in orders if str(item.get("priority")) == "A") if orders is not None else None
    mapped: list[dict[str, Any]] = []
    for index in range(3):
        source = raw[index] if index < len(raw) else {}
        cost = _first_number(source, ("total_cost", "cost", "economic_cost", "estimated_cost"))
        score = _number(source.get("total_score")) or _number(source.get("score")) or 0.0
        agent = str(source.get("agent_name", source.get("name", "数据缺失")))
        lead_time = _first_number(source, ("lead_time_impact", "delay_days"))
        lead_time_days = int(math.ceil(lead_time)) if lead_time is not None else _supplier_lead_days(source, context)
        row_customer_impact = _first_number(source, ("customer_impact",))
        row_high_value = _first_number(source, ("high_value_customers",))
        residual = source.get("residual_risk") if isinstance(source.get("residual_risk"), str) else _residual_risk(source)
        values = {
            "total_cost": cost,
            "lead_time_impact": lead_time_days,
            "residual_risk": residual,
            "customer_impact": int(row_customer_impact) if row_customer_impact is not None else customer_impact,
            "high_value_customers": int(row_high_value) if row_high_value is not None else high_value_customers,
        }
        mapped.append({
            "incident_id": incident_id,
            "name": str(source.get("proposal_name", source.get("proposal_title", source.get("name", source.get("title", "数据缺失"))))),
            "tag": TAGS[index],
            **values,
            "reason": str(source.get("reason", source.get("description", source.get("proposal", "；".join(map(str, source.get("reasoning", []))) or (f"综合评分 {score:.2f}" if score else "数据缺失"))))),
            "views": {"采购": str(source.get("procurement_view", agent)), "物流": str(source.get("logistics_view", agent)), "财务": str(source.get("finance_view", agent)), "销售": str(source.get("sales_view", agent)), "生产": str(source.get("production_view", agent))},
            "constraints": constraints if isinstance(constraints, list) else [constraints],
            "explanation": {
                **(explanation if isinstance(explanation, dict) else {"summary": str(explanation)}),
                "dataMissing": [
                    field
                    for field, value in {
                        "totalCost": values["total_cost"],
                        "leadTimeImpact": values["lead_time_impact"],
                        "residualRisk": values["residual_risk"],
                        "customerImpact": values["customer_impact"],
                        "highValueCustomers": values["high_value_customers"],
                    }.items()
                    if value is None
                ],
            },
        })
    return mapped
