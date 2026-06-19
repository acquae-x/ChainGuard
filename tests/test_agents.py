from copy import deepcopy

from src.agents import (
    FinanceAgent,
    LogisticsAgent,
    ProcurementAgent,
    generate_all_proposals,
)
from src.data_loader import load_demo_context
from src.scenario_loader import ScenarioLoader


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


def _proposal_by_agent(proposals, agent_keyword):
    return next(
        proposal
        for proposal in proposals
        if agent_keyword in proposal["agent_name"]
    )


def test_generate_all_proposals_returns_three_stable_proposals():
    proposals = generate_all_proposals(load_demo_context())

    assert [proposal["agent_name"] for proposal in proposals] == [
        "采购 Agent",
        "物流 Agent",
        "财务 Agent",
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

    assert any(
        supplier["supplier_name"] in procurement["proposal_title"]
        for supplier in context["suppliers"]
    )
    assert "空运" in logistics["proposal"]
    assert "利润转负" in " ".join(finance["risks"])


def test_procurement_feasibility_decreases_when_supply_is_removed():
    original_context = load_demo_context()
    reduced_context = deepcopy(original_context)
    reduced_context["suppliers"][0]["available_qty"] = 0

    original = ProcurementAgent().generate_proposal(original_context)
    reduced = ProcurementAgent().generate_proposal(reduced_context)

    assert reduced["scores"]["feasibility"] < original["scores"]["feasibility"]


def test_logistics_timeliness_decreases_when_transport_slows():
    original_context = load_demo_context()
    slower_context = deepcopy(original_context)
    for option in slower_context["transport_options"]:
        if option["available"]:
            option["estimated_hours"] *= 2

    original = LogisticsAgent().generate_proposal(original_context)
    slower = LogisticsAgent().generate_proposal(slower_context)

    assert slower["scores"]["timeliness"] < original["scores"]["timeliness"]


def test_procurement_handles_no_suppliers():
    context = load_demo_context()
    context["suppliers"] = []

    proposal = ProcurementAgent().generate_proposal(context)

    assert REQUIRED_KEYS <= set(proposal)
    assert "无合格供应商" in proposal["proposal"]
    assert all(score <= 60 for score in proposal["scores"].values())


def test_logistics_handles_no_available_transport():
    context = load_demo_context()
    for option in context["transport_options"]:
        option["available"] = False

    proposal = LogisticsAgent().generate_proposal(context)

    assert "当前无可用运输方式" in proposal["proposal"]
    assert proposal["scores"]["timeliness"] == 0
    assert proposal["scores"]["feasibility"] == 0


def test_enterprise_scenarios_have_different_procurement_feasibility():
    loader = ScenarioLoader()
    event_ids = [
        "EVT-000006",
        "EVT-000016",
        "EVT-000037",
        "EVT-000065",
        "EVT-000113",
    ]

    feasibility_scores = [
        ProcurementAgent()
        .generate_proposal(loader.load_context(event_id))["scores"]["feasibility"]
        for event_id in event_ids
    ]

    assert len(set(feasibility_scores)) > 1


def test_generate_all_proposals_is_deterministic():
    context = load_demo_context()

    assert generate_all_proposals(context) == generate_all_proposals(context)


def test_proposal_text_does_not_hardcode_demo_names():
    proposals = generate_all_proposals(load_demo_context())
    procurement = _proposal_by_agent(proposals, "采购")
    logistics = _proposal_by_agent(proposals, "物流")

    assert "A供应商" not in procurement["proposal"]
    assert "B备用供应商" not in procurement["proposal"]
    assert "宁波港" not in logistics["proposal"]


def test_finance_handles_no_orders():
    context = load_demo_context()
    context["orders"] = []

    proposal = FinanceAgent().generate_proposal(context)

    assert REQUIRED_KEYS <= set(proposal)
    assert all(0 <= score <= 100 for score in proposal["scores"].values())


def test_all_proposals_include_three_strategy_options():
    proposals = generate_all_proposals(load_demo_context())

    for proposal in proposals:
        assert len(proposal["strategy_options"]) == 3
        for option in proposal["strategy_options"]:
            assert {
                "label",
                "own_utility",
                "system_utility",
                "selected",
            } == set(option)


def test_each_proposal_has_exactly_one_selected_strategy():
    proposals = generate_all_proposals(load_demo_context())

    for proposal in proposals:
        selected = [
            option
            for option in proposal["strategy_options"]
            if option["selected"]
        ]
        assert len(selected) == 1
        assert selected[0]["label"] in proposal["proposal_title"]


def test_procurement_strategy_payoff_changes_when_supply_is_removed():
    original_context = load_demo_context()
    reduced_context = deepcopy(original_context)
    reduced_context["suppliers"][0]["available_qty"] = 0

    original = ProcurementAgent().generate_proposal(original_context)
    reduced = ProcurementAgent().generate_proposal(reduced_context)
    original_options = [
        (option["label"], option["own_utility"])
        for option in original["strategy_options"]
    ]
    reduced_options = [
        (option["label"], option["own_utility"])
        for option in reduced["strategy_options"]
    ]

    assert original_options != reduced_options


def test_procurement_proposal_changes_when_best_strategy_switches():
    original_context = load_demo_context()
    constrained_context = deepcopy(original_context)
    supplier_c = next(
        supplier
        for supplier in constrained_context["suppliers"]
        if supplier["supplier_id"] == "SUP-C"
    )
    supplier_c["available_qty"] = 0

    original = ProcurementAgent().generate_proposal(original_context)
    constrained = ProcurementAgent().generate_proposal(constrained_context)
    original_selected = next(
        option for option in original["strategy_options"] if option["selected"]
    )
    constrained_selected = next(
        option for option in constrained["strategy_options"] if option["selected"]
    )

    assert original_selected["label"] == "多源联合补货"
    assert constrained_selected["label"] == "主供应商紧急补货"
    assert original["proposal_title"] != constrained["proposal_title"]
