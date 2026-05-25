from typing import Any


def _proposal_text(proposal: dict[str, Any]) -> str:
    parts = [
        str(proposal.get("agent_name", "")),
        str(proposal.get("role", "")),
        str(proposal.get("proposal_title", "")),
        str(proposal.get("proposal", "")),
    ]
    for key in ("reasoning", "risks", "actions"):
        value = proposal.get(key, [])
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return " ".join(parts)


def _is_agent(proposal: dict[str, Any], keyword: str) -> bool:
    return keyword in str(proposal.get("agent_name", ""))


def generate_rebuttal(
    lowest_proposal: dict[str, Any],
    highest_proposal: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Generate a deterministic debate rebuttal for the MVP.

    By default, the lower-scored proposal rebuts the higher-scored proposal.
    For the fixed demo scenario, a stronger special rule is used: when the
    logistics proposal advocates full air freight and the finance proposal is
    present, Finance rebuts Logistics to make the cost-vs-timeliness conflict
    clear for presentation.
    """
    first_text = _proposal_text(lowest_proposal)
    second_text = _proposal_text(highest_proposal)
    orders = context.get("orders", [])
    critical_orders = [order for order in orders if order.get("priority") == "A"]

    if _is_agent(lowest_proposal, "物流") and "全量空运" in first_text and _is_agent(highest_proposal, "财务"):
        return {
            "debater": highest_proposal["agent_name"],
            "target": lowest_proposal["agent_name"],
            "rebuttal_points": [
                "空运成本过高，不能直接覆盖所有受影响订单。",
                "全量空运可能导致部分低毛利订单利润转负。",
                "建议只对A类关键客户订单空运，优先保障高违约损失订单。",
                "非关键订单应延期沟通，采用铁路、陆运或分批交付方案。",
            ],
            "suggested_revision": (
                f"将全量空运修订为分级保障：{len(critical_orders)} 个A类关键客户订单优先空运，"
                "B/C类订单通过客户沟通、分批交付和低成本运输组合降低总成本。"
            ),
            "accepted_tradeoff": "接受部分非关键订单延期沟通，以换取关键客户履约和总体利润可控。",
        }

    if _is_agent(highest_proposal, "物流") and "全量空运" in second_text and _is_agent(lowest_proposal, "财务"):
        return {
            "debater": lowest_proposal["agent_name"],
            "target": highest_proposal["agent_name"],
            "rebuttal_points": [
                "空运成本过高，不能直接覆盖所有受影响订单。",
                "全量空运可能导致部分低毛利订单利润转负。",
                "建议只对A类关键客户订单空运，优先保障高违约损失订单。",
                "非关键订单应延期沟通，采用铁路、陆运或分批交付方案。",
            ],
            "suggested_revision": (
                f"将全量空运修订为分级保障：{len(critical_orders)} 个A类关键客户订单优先空运，"
                "B/C类订单通过客户沟通、分批交付和低成本运输组合降低总成本。"
            ),
            "accepted_tradeoff": "接受部分非关键订单延期沟通，以换取关键客户履约和总体利润可控。",
        }

    if _is_agent(lowest_proposal, "采购") and "备用供应商" not in second_text:
        return {
            "debater": lowest_proposal["agent_name"],
            "target": highest_proposal["agent_name"],
            "rebuttal_points": [
                "目标方案缺少明确的备用供应商安排。",
                "A供应商受台风影响延误，不能继续依赖单一供应来源。",
                "若不提前锁定B/C供应商，可用库存可能在关键订单交付前耗尽。",
            ],
            "suggested_revision": "补充B备用供应商紧急采购，并保留C供应商作为小批量兜底。",
            "accepted_tradeoff": "接受一定采购溢价，以换取供应连续性和订单覆盖率。",
        }

    target_scores = highest_proposal.get("scores", {})
    target_is_conservative = (
        float(target_scores.get("timeliness", 100)) < 75
        or "延期" in second_text
        or "分批" in second_text
    )
    if _is_agent(lowest_proposal, "物流") and target_is_conservative:
        return {
            "debater": lowest_proposal["agent_name"],
            "target": highest_proposal["agent_name"],
            "rebuttal_points": [
                "目标方案过于保守，可能无法覆盖48小时交付窗口。",
                "若不使用高时效运输，A类关键客户存在违约风险。",
                "应至少为关键订单保留空运或最快替代路线。",
            ],
            "suggested_revision": "对关键订单启用空运，对非关键订单采用铁路或陆运组合。",
            "accepted_tradeoff": "接受关键订单运输成本上升，以降低违约风险和客户服务风险。",
        }

    return {
        "debater": lowest_proposal["agent_name"],
        "target": highest_proposal["agent_name"],
        "rebuttal_points": [
            "当前最高分方案仍存在未充分解释的执行约束。",
            "需要进一步校验成本、时效、风险降低和客户服务之间的取舍。",
        ],
        "suggested_revision": "将高分方案拆分为关键订单优先和非关键订单分级处理两部分。",
        "accepted_tradeoff": "接受局部成本或时效让步，以获得更稳健的综合方案。",
    }
