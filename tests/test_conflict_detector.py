import pytest

from src.agents import generate_all_proposals
from src.config_loader import load_risk_weights, load_thresholds
from src.conflict_detector import detect_conflict
from src.data_loader import load_demo_context
from src.scoring import attach_total_scores


def _scored_demo_proposals():
    return attach_total_scores(
        generate_all_proposals(load_demo_context()),
        load_risk_weights()["decision_score_weights"],
    )


def test_fixed_demo_case_triggers_conflict():
    conflict = detect_conflict(_scored_demo_proposals(), load_thresholds())

    assert conflict["has_conflict"] is True
    assert conflict["conflict_type"] == "成本-时效冲突"
    assert conflict["conflict_summary"] == "物流主张全量空运，财务反对高成本方案"
    assert conflict["highest_agent"] == "采购 Agent"
    assert conflict["lowest_agent"] == "物流 Agent"
    assert conflict["score_gap"] == pytest.approx(3.6)
    assert conflict["reasons"]


def test_keyword_conflict_triggers_even_when_score_gap_is_small():
    proposals = _scored_demo_proposals()
    thresholds = {"debate": {"score_gap_trigger": 99}}

    conflict = detect_conflict(proposals, thresholds)

    assert conflict["has_conflict"] is True
    assert any("冲突关键词" in reason for reason in conflict["reasons"])


def test_objective_conflict_between_logistics_and_finance_triggers():
    proposals = [
        {
            "agent_name": "物流 Agent",
            "proposal_title": "快速运输",
            "proposal": "优先保障交付时效。",
            "scores": {
                "timeliness": 90,
                "cost": 40,
                "risk_reduction": 80,
                "feasibility": 80,
                "service_level": 90,
            },
            "total_score": 80,
        },
        {
            "agent_name": "财务 Agent",
            "proposal_title": "控制成本",
            "proposal": "优先控制成本。",
            "scores": {
                "timeliness": 70,
                "cost": 90,
                "risk_reduction": 75,
                "feasibility": 85,
                "service_level": 75,
            },
            "total_score": 80,
        },
    ]

    conflict = detect_conflict(proposals, {"debate": {"score_gap_trigger": 99}})

    assert conflict["has_conflict"] is True
    assert any("目标冲突" in reason for reason in conflict["reasons"])


def test_detect_conflict_requires_total_score():
    proposals = _scored_demo_proposals()
    proposals[0].pop("total_score")

    with pytest.raises(ValueError, match="total_score"):
        detect_conflict(proposals, load_thresholds())
