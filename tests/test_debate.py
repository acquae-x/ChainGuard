from src.agents import generate_all_proposals
from src.config_loader import load_risk_weights
from src.data_loader import load_demo_context
from src.debate import generate_rebuttal
from src.scoring import attach_total_scores, rank_proposals


def _proposal_by_agent(proposals, keyword):
    for proposal in proposals:
        if keyword in proposal["agent_name"]:
            return proposal
    raise AssertionError(f"missing proposal: {keyword}")


def test_fixed_case_finance_rebuts_logistics_full_air_freight():
    context = load_demo_context()
    proposals = attach_total_scores(
        generate_all_proposals(context),
        load_risk_weights()["decision_score_weights"],
    )
    logistics = _proposal_by_agent(proposals, "物流")
    finance = _proposal_by_agent(proposals, "财务")

    rebuttal = generate_rebuttal(logistics, finance, context)

    assert rebuttal["debater"] == "财务 Agent"
    assert rebuttal["target"] == "物流 Agent"
    assert "空运成本过高" in rebuttal["rebuttal_points"][0]
    assert any("利润转负" in point for point in rebuttal["rebuttal_points"])
    assert any("A类关键客户订单空运" in point for point in rebuttal["rebuttal_points"])
    assert any("非关键订单应延期沟通" in point for point in rebuttal["rebuttal_points"])
    assert "分级保障" in rebuttal["suggested_revision"]


def test_default_lowest_rebuts_highest_when_no_special_rule():
    context = load_demo_context()
    highest = {
        "agent_name": "高分 Agent",
        "proposal": "综合方案",
        "scores": {"timeliness": 90},
    }
    lowest = {
        "agent_name": "低分 Agent",
        "proposal": "补充意见",
        "scores": {"timeliness": 80},
    }

    rebuttal = generate_rebuttal(lowest, highest, context)

    assert rebuttal["debater"] == "低分 Agent"
    assert rebuttal["target"] == "高分 Agent"
    assert rebuttal["rebuttal_points"]


def test_procurement_rebuts_when_backup_supplier_is_ignored():
    context = load_demo_context()
    procurement = {
        "agent_name": "采购 Agent",
        "proposal": "建议补充采购约束。",
        "scores": {"timeliness": 80},
    }
    target = {
        "agent_name": "运营 Agent",
        "proposal": "只调整库存分配，不考虑其他货源。",
        "scores": {"timeliness": 85},
    }

    rebuttal = generate_rebuttal(procurement, target, context)

    assert rebuttal["debater"] == "采购 Agent"
    assert any("备用供应商" in point for point in rebuttal["rebuttal_points"])


def test_logistics_rebuts_overly_conservative_plan():
    context = load_demo_context()
    logistics = {
        "agent_name": "物流 Agent",
        "proposal": "建议提高运输时效。",
        "scores": {"timeliness": 90},
    }
    target = {
        "agent_name": "财务 Agent",
        "proposal": "建议延期沟通并分批交付。",
        "scores": {"timeliness": 70},
    }

    rebuttal = generate_rebuttal(logistics, target, context)

    assert rebuttal["debater"] == "物流 Agent"
    assert any("违约风险" in point for point in rebuttal["rebuttal_points"])
