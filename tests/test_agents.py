from src.agents import FinanceAgent, LogisticsAgent, ProcurementAgent, generate_all_proposals
from src.data_loader import load_demo_context


REQUIRED_KEYS = {
    "agent_name",
    "role",
    "proposal_title",
    "proposal",
    "reasoning",
    "risks",
    "actions",
    "scores",
}

SCORE_KEYS = {
    "timeliness",
    "cost",
    "risk_reduction",
    "feasibility",
    "service_level",
}


def test_generate_all_proposals_returns_three_stable_proposals():
    proposals = generate_all_proposals(load_demo_context())

    assert [proposal["agent_name"] for proposal in proposals] == [
        "采购 Agent",
        "物流 Agent",
        "财务 Agent",
    ]
    assert [proposal["proposal_title"] for proposal in proposals] == [
        "启用B备用供应商进行紧急补货",
        "对受影响订单执行紧急空运",
        "反对全量空运，建议客户分级保障",
    ]


def test_agent_proposal_schema_and_scores():
    proposals = generate_all_proposals(load_demo_context())

    for proposal in proposals:
        assert REQUIRED_KEYS <= set(proposal)
        assert SCORE_KEYS == set(proposal["scores"])
        assert proposal["reasoning"]
        assert proposal["risks"]
        assert proposal["actions"]
        for score in proposal["scores"].values():
            assert 0 <= score <= 100


def test_individual_agents_generate_expected_focus():
    context = load_demo_context()

    procurement = ProcurementAgent().generate_proposal(context)
    logistics = LogisticsAgent().generate_proposal(context)
    finance = FinanceAgent().generate_proposal(context)

    assert "B备用供应商" in procurement["proposal"]
    assert "全量紧急空运" in logistics["proposal"]
    assert "利润转负" in " ".join(finance["risks"])
