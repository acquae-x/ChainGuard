import json

import pytest

import src.orchestrator as orchestrator_module
from src.domain_models import DecisionResult
from src.orchestrator import DecisionOrchestrator


def _proposal_scores(result: DecisionResult) -> dict[str, float]:
    return {
        proposal["agent_name"]: proposal["total_score"]
        for proposal in result.proposals
    }


def test_run_demo_returns_complete_decision_result():
    result = DecisionOrchestrator().run_demo()

    assert isinstance(result, DecisionResult)
    assert all(
        value is not None
        for value in (
            result.risk_weights,
            result.thresholds,
            result.context,
            result.inventory_risk,
            result.proposals,
            result.conflict,
            result.rebuttal,
            result.arbitration,
            result.experience_card,
        )
    )


def test_run_demo_preserves_fixed_case_risk_and_scores():
    result = DecisionOrchestrator().run_demo()
    scores = _proposal_scores(result)

    assert result.inventory_risk["inventory_risk_index"] == pytest.approx(70.25)
    for agent_name in ("采购 Agent", "物流 Agent", "财务 Agent"):
        assert 0 <= scores[agent_name] <= 100


def test_run_demo_preserves_fixed_case_arbitration():
    result = DecisionOrchestrator().run_demo()

    assert "核心控制芯片" in result.arbitration["final_decision_title"]
    assert "空运" in result.arbitration["final_decision_title"]
    assert isinstance(result.arbitration["final_score"], float)
    assert 0 < result.arbitration["final_score"] <= 100


def test_decision_result_to_dict_is_json_serializable_and_independent():
    result = DecisionOrchestrator().run_demo()
    payload = result.to_dict()

    serialized = json.dumps(payload, ensure_ascii=False)
    payload["context"]["inventory"]["current_stock"] = -1

    assert "关键订单空运" in serialized
    assert result.context["inventory"]["current_stock"] == 3600


def test_proposals_have_experience_hints_field():
    result = DecisionOrchestrator().run_demo()

    for proposal in result.proposals:
        assert "experience_hints" in proposal
        assert isinstance(proposal["experience_hints"], list)


def test_proposals_have_experience_confidence_field():
    result = DecisionOrchestrator().run_demo()

    for proposal in result.proposals:
        assert "experience_confidence" in proposal
        assert isinstance(proposal["experience_confidence"], float)


def test_experience_confidence_in_unit_interval():
    result = DecisionOrchestrator().run_demo()

    for proposal in result.proposals:
        confidence = proposal["experience_confidence"]
        assert 0.0 <= confidence <= 1.0


@pytest.mark.parametrize("missing_role", ["物流", "财务"])
def test_run_demo_raises_clear_error_when_required_agent_is_missing(
    monkeypatch,
    missing_role,
):
    original_generate = orchestrator_module.generate_all_proposals

    def generate_without_required_agent(context):
        return [
            proposal
            for proposal in original_generate(context)
            if missing_role not in proposal["agent_name"]
        ]

    monkeypatch.setattr(
        orchestrator_module,
        "generate_all_proposals",
        generate_without_required_agent,
    )

    with pytest.raises(ValueError, match=rf"{missing_role} Agent"):
        DecisionOrchestrator().run_demo()
