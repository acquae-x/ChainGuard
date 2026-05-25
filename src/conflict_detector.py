from typing import Any

from src.scoring import rank_proposals


CONFLICT_KEYWORDS = [
    "全量空运",
    "成本过高",
    "利润转负",
    "违约风险",
    "供应商不可用",
]


def _proposal_text(proposal: dict[str, Any]) -> str:
    text_parts: list[str] = []
    for key in ("agent_name", "role", "proposal_title", "proposal"):
        text_parts.append(str(proposal.get(key, "")))
    for key in ("reasoning", "risks", "actions"):
        values = proposal.get(key, [])
        if isinstance(values, list):
            text_parts.extend(str(value) for value in values)
        else:
            text_parts.append(str(values))
    return " ".join(text_parts)


def _find_agent(proposals: list[dict[str, Any]], keyword: str) -> dict[str, Any] | None:
    for proposal in proposals:
        if keyword in str(proposal.get("agent_name", "")):
            return proposal
    return None


def detect_conflict(proposals: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
    if not proposals:
        raise ValueError("proposals 不能为空。")
    for proposal in proposals:
        if "total_score" not in proposal:
            raise ValueError(f"{proposal.get('agent_name', 'proposal')} 缺少 total_score 字段。")
        if "scores" not in proposal:
            raise ValueError(f"{proposal.get('agent_name', 'proposal')} 缺少 scores 字段。")

    score_gap_trigger = float(thresholds.get("debate", {}).get("score_gap_trigger", 15))
    ranked = rank_proposals(proposals)
    highest = ranked[0]
    lowest = ranked[-1]
    score_gap = round(float(highest["total_score"]) - float(lowest["total_score"]), 2)

    reasons: list[str] = []
    if score_gap >= score_gap_trigger:
        reasons.append(f"最高分与最低分差距 {score_gap:.1f}，达到辩论触发阈值 {score_gap_trigger:.1f}。")

    combined_text = " ".join(_proposal_text(proposal) for proposal in proposals)
    matched_keywords = [keyword for keyword in CONFLICT_KEYWORDS if keyword in combined_text]
    if matched_keywords:
        reasons.append(f"方案文本出现冲突关键词：{', '.join(matched_keywords)}。")

    logistics = _find_agent(proposals, "物流")
    finance = _find_agent(proposals, "财务")
    has_objective_conflict = False
    if logistics and finance:
        logistics_scores = logistics["scores"]
        finance_scores = finance["scores"]
        has_objective_conflict = (
            float(logistics_scores.get("timeliness", 0)) >= 85
            and float(logistics_scores.get("cost", 100)) <= 50
            and float(finance_scores.get("cost", 0)) >= 80
            and float(finance_scores.get("timeliness", 100)) <= 80
        )
        if has_objective_conflict:
            reasons.append("物流方案偏向时效优先，财务方案偏向成本控制，存在目标冲突。")

    has_conflict = bool(reasons)
    conflict_type = "成本-时效冲突" if has_conflict else "无明显冲突"

    if has_objective_conflict or matched_keywords:
        conflict_summary = "物流主张全量空运，财务反对高成本方案"
    elif score_gap >= score_gap_trigger:
        conflict_summary = "方案评分差距达到阈值，需要辩论仲裁"
    else:
        conflict_summary = "当前方案未触发辩论仲裁"

    return {
        "has_conflict": has_conflict,
        "conflict_type": conflict_type,
        "conflict_summary": conflict_summary,
        "highest_agent": highest["agent_name"],
        "lowest_agent": lowest["agent_name"],
        "score_gap": score_gap,
        "reasons": reasons,
    }
