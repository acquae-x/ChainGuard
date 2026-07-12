from typing import Any

from src.text_generator import TextGenerator


def arbitrate(
    proposals: list[dict[str, Any]],
    conflict_result: dict[str, Any],
    rebuttal: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    inventory = context.get("inventory", {})
    orders = context.get("orders", [])
    events = context.get("events") or []
    event = events[0] if events else {}
    event_type = str(event.get("event_type") or "")
    event_title = str(event.get("title") or "当前中断事件")
    material_name = inventory.get("material_name", "关键物料")
    critical_orders = [order for order in orders if order.get("priority") == "A"]

    action_phrase = _action_phrase(event_type)
    best_score = (
        max(float(proposal.get("total_score", 0)) for proposal in proposals)
        if proposals
        else 0
    )
    conflict_penalty = 2 if conflict_result.get("has_conflict") else 0
    rebuttal_bonus = 4 if rebuttal.get("suggested_revision") else 0
    final_score = (
        min(100, round(best_score + rebuttal_bonus - conflict_penalty, 1))
        if proposals
        else 0
    )
    top_proposals = [
        _sanitize_narrative_input(proposal)
        for proposal in sorted(
            proposals,
            key=lambda proposal: float(proposal.get("total_score", 0)),
            reverse=True,
        )
    ]
    arbitration_content = TextGenerator().generate_arbitration_content(
        action_phrase=action_phrase,
        material_name=str(material_name),
        event_title=event_title,
        critical_orders_count=len(critical_orders),
        top_proposals=top_proposals,
        final_score=final_score,
    )

    return {
        "final_decision_title": f"{action_phrase}：{material_name}应急响应",
        "final_strategy": arbitration_content["final_strategy"],
        "adopted_opinions": _rank_adopted_opinions(proposals),
        "rejected_opinions": arbitration_content["rejected_opinions"],
        "execution_plan": arbitration_content["execution_plan"],
        "manual_confirmation_points": arbitration_content["manual_confirmation_points"],
        "expected_effect": arbitration_content["expected_effect"],
        "final_score": final_score,
    }


def _action_phrase(event_type: str) -> str:
    et = event_type.lower()
    if "port_shutdown" in et or "typhoon" in et:
        return "空运 + 备用补货 + 低优先级延期"
    if "supplier_shutdown" in et or "power_shortage" in et:
        return "多源紧急采购 + 风险分散 + 紧急配送"
    if "route_blockage" in et or "customs_delay" in et:
        return "替代路线 + 库存调拨 + 交期重排"
    if "demand_surge" in et:
        return "弹性产能激活 + 优先级重排 + 快速补货"
    if "quality_recall" in et:
        return "隔离召回批次 + 替代供应 + 客户通知"
    return "应急供应保障 + 多渠道补货 + 订单优先分级"


def _sanitize_narrative_input(value: Any) -> Any:
    replacements = {
        "B备用供应商": "备用供应商",
        "36小时": "当前库存支撑时长",
        "66小时": "延长库存支撑时长",
    }
    if isinstance(value, str):
        sanitized = value
        for source, target in replacements.items():
            sanitized = sanitized.replace(source, target)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_narrative_input(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_narrative_input(item)
            for key, item in value.items()
        }
    return value


def _rank_adopted_opinions(proposals: list[dict[str, Any]]) -> list[str]:
    agent_labels = {
        "采购": "采购 Agent 的备用供应商建议：优先确认可供量与交期。",
        "物流": "物流 Agent 的运输方案建议：按关键程度选择运输方式。",
        "财务": "财务 Agent 的成本控制建议：避免全量高成本方案导致利润转负。",
    }
    ranked = sorted(
        proposals,
        key=lambda proposal: float(proposal.get("total_score", 0)),
        reverse=True,
    )
    adopted_opinions: list[str] = []
    for proposal in ranked[:3]:
        name = str(proposal.get("agent_name", ""))
        for key, text in agent_labels.items():
            if key in name:
                adopted_opinions.append(f"采纳{text}")
                break
    return adopted_opinions
