from copy import deepcopy
from typing import Any


REQUIRED_SCORE_KEYS = {
    "timeliness",
    "cost",
    "risk_reduction",
    "feasibility",
    "service_level",
}


def _require_score_keys(scores: dict[str, float], label: str) -> None:
    missing = sorted(REQUIRED_SCORE_KEYS - set(scores))
    if missing:
        raise ValueError(f"{label} 缺少评分字段：{', '.join(missing)}")


def calculate_total_score(
    scores: dict[str, float],
    decision_score_weights: dict[str, float],
) -> float:
    _require_score_keys(scores, "scores")
    _require_score_keys(decision_score_weights, "decision_score_weights")

    total_score = (
        float(decision_score_weights["timeliness"]) * float(scores["timeliness"])
        + float(decision_score_weights["cost"]) * float(scores["cost"])
        + float(decision_score_weights["risk_reduction"]) * float(scores["risk_reduction"])
        + float(decision_score_weights["feasibility"]) * float(scores["feasibility"])
        + float(decision_score_weights["service_level"]) * float(scores["service_level"])
    )
    return round(total_score, 2)


def attach_total_scores(
    proposals: list[dict[str, Any]],
    decision_score_weights: dict[str, float],
) -> list[dict[str, Any]]:
    scored_proposals = deepcopy(proposals)
    for proposal in scored_proposals:
        if "scores" not in proposal:
            raise ValueError(f"{proposal.get('agent_name', 'proposal')} 缺少 scores 字段。")
        proposal["total_score"] = calculate_total_score(
            proposal["scores"],
            decision_score_weights,
        )
    return scored_proposals


def rank_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for proposal in proposals:
        if "total_score" not in proposal:
            raise ValueError(f"{proposal.get('agent_name', 'proposal')} 缺少 total_score 字段。")
    return sorted(proposals, key=lambda proposal: proposal["total_score"], reverse=True)


def detect_low_score(proposal: dict[str, Any], threshold: float) -> bool:
    if "total_score" not in proposal:
        raise ValueError(f"{proposal.get('agent_name', 'proposal')} 缺少 total_score 字段。")
    return float(proposal["total_score"]) < float(threshold)
