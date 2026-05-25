from src.agents import generate_all_proposals
from src.arbitrator import arbitrate
from src.config_loader import load_risk_weights, load_thresholds
from src.conflict_detector import detect_conflict
from src.data_loader import load_demo_context
from src.debate import generate_rebuttal
from src.scoring import attach_total_scores


def _proposal_by_agent(proposals, keyword):
    for proposal in proposals:
        if keyword in proposal["agent_name"]:
            return proposal
    raise AssertionError(f"missing proposal: {keyword}")


def _fixed_case_arbitration():
    context = load_demo_context()
    proposals = attach_total_scores(
        generate_all_proposals(context),
        load_risk_weights()["decision_score_weights"],
    )
    conflict = detect_conflict(proposals, load_thresholds())
    rebuttal = generate_rebuttal(
        _proposal_by_agent(proposals, "物流"),
        _proposal_by_agent(proposals, "财务"),
        context,
    )
    return arbitrate(proposals, conflict, rebuttal, context)


def test_fixed_case_final_decision_title():
    result = _fixed_case_arbitration()

    assert result["final_decision_title"] == "关键订单空运 + 备用供应商补货 + 非关键订单延期沟通"


def test_fixed_case_adopts_required_opinions():
    result = _fixed_case_arbitration()
    adopted = " ".join(result["adopted_opinions"])

    assert "采纳采购 Agent 的备用供应商建议" in adopted
    assert "采纳物流 Agent 的关键订单空运建议" in adopted
    assert "采纳财务 Agent 的客户分级保障建议" in adopted


def test_fixed_case_rejects_full_air_freight():
    result = _fixed_case_arbitration()

    assert "拒绝全量空运，因为成本过高且可能利润转负。" in result["rejected_opinions"]


def test_fixed_case_execution_plan_and_manual_confirmation_points():
    result = _fixed_case_arbitration()
    execution_plan = " ".join(result["execution_plan"])
    confirmation = " ".join(result["manual_confirmation_points"])

    assert "2小时内联系B备用供应商确认可供量" in execution_plan
    assert "A类关键客户订单采用空运" in execution_plan
    assert "非关键订单延期24-48小时并通知客户" in execution_plan
    assert "台风影响超过96小时" in execution_plan
    assert "是否接受空运成本" in confirmation
    assert "是否启用备用供应商" in confirmation
    assert "是否通知客户延期" in confirmation


def test_fixed_case_expected_effect_and_score():
    result = _fixed_case_arbitration()

    assert result["expected_effect"]["delivery_risk"]
    assert 0 <= result["final_score"] <= 100
