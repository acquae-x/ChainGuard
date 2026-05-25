import pytest

from src.agents import generate_all_proposals
from src.config_loader import load_risk_weights, load_thresholds
from src.data_loader import load_demo_context
from src.scoring import (
    attach_total_scores,
    calculate_total_score,
    detect_low_score,
    rank_proposals,
)


def test_calculate_total_score_uses_config_weights():
    scores = {
        "timeliness": 96,
        "cost": 32,
        "risk_reduction": 92,
        "feasibility": 76,
        "service_level": 94,
    }
    weights = load_risk_weights()["decision_score_weights"]

    assert calculate_total_score(scores, weights) == pytest.approx(78.0)


def test_attach_total_scores_and_rank_proposals():
    proposals = generate_all_proposals(load_demo_context())
    weights = load_risk_weights()["decision_score_weights"]
    scored = attach_total_scores(proposals, weights)
    ranked = rank_proposals(scored)

    assert all("total_score" in proposal for proposal in scored)
    assert ranked[0]["total_score"] >= ranked[1]["total_score"] >= ranked[2]["total_score"]
    assert ranked[0]["agent_name"] == "采购 Agent"
    assert ranked[-1]["agent_name"] == "物流 Agent"


def test_detect_low_score_uses_learning_threshold():
    threshold = load_thresholds()["learning"]["low_score_threshold"]
    proposal = {
        "agent_name": "测试 Agent",
        "total_score": 68.5,
    }

    assert detect_low_score(proposal, threshold) is True


def test_detect_low_score_false_when_above_threshold():
    threshold = load_thresholds()["learning"]["low_score_threshold"]
    proposal = {
        "agent_name": "测试 Agent",
        "total_score": 70,
    }

    assert detect_low_score(proposal, threshold) is False


def test_calculate_total_score_raises_for_missing_score_key():
    scores = {
        "timeliness": 90,
        "cost": 70,
    }

    with pytest.raises(ValueError, match="risk_reduction"):
        calculate_total_score(scores, load_risk_weights()["decision_score_weights"])
