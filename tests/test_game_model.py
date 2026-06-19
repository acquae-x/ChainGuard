from src.data_loader import load_demo_context
from src.game_model import AgentPayoff, PayoffModel
from src.scenario_loader import ScenarioLoader


def _assert_valid_payoff(payoff):
    assert isinstance(payoff, AgentPayoff)
    assert len(payoff.options) == 3
    assert payoff.selected_label == payoff.selected.label
    for option in payoff.options:
        assert 0 <= option.own_utility <= 100
        assert 0 <= option.system_utility <= 100


def test_evaluate_procurement_returns_three_valid_options():
    payoff = PayoffModel().evaluate_procurement(load_demo_context())

    _assert_valid_payoff(payoff)
    assert [option.label for option in payoff.options] == [
        "主供应商紧急补货",
        "多源联合补货",
        "应急最大化供给",
    ]


def test_evaluate_logistics_returns_three_valid_options():
    payoff = PayoffModel().evaluate_logistics(load_demo_context())

    _assert_valid_payoff(payoff)
    assert [option.label for option in payoff.options] == [
        "最快运输优先",
        "均衡运输组合",
        "最低成本路线",
    ]


def test_evaluate_finance_returns_three_valid_options():
    payoff = PayoffModel().evaluate_finance(load_demo_context())

    _assert_valid_payoff(payoff)
    assert [option.label for option in payoff.options] == [
        "A类优先分级保障",
        "全量高成本保障",
        "盈亏平衡截止",
    ]


def test_selected_index_points_to_highest_own_utility():
    model = PayoffModel()
    payoffs = [
        model.evaluate_procurement(load_demo_context()),
        model.evaluate_logistics(load_demo_context()),
        model.evaluate_finance(load_demo_context()),
    ]

    for payoff in payoffs:
        maximum = max(option.own_utility for option in payoff.options)
        assert payoff.selected.own_utility == maximum
        assert payoff.selected_index == next(
            index
            for index, option in enumerate(payoff.options)
            if option.own_utility == maximum
        )


def test_finance_full_high_cost_is_worse_than_tiered_protection():
    payoff = PayoffModel().evaluate_finance(load_demo_context())

    assert payoff.options[1].own_utility < payoff.options[0].own_utility


def test_procurement_without_suppliers_returns_zero_utilities():
    context = load_demo_context()
    context["suppliers"] = []

    payoff = PayoffModel().evaluate_procurement(context)

    assert payoff.selected_index == 0
    assert all(option.own_utility == 0 for option in payoff.options)


def test_logistics_without_available_modes_returns_zero_utilities():
    context = load_demo_context()
    for option in context["transport_options"]:
        option["available"] = False

    payoff = PayoffModel().evaluate_logistics(context)

    assert payoff.selected_index == 0
    assert all(option.own_utility == 0 for option in payoff.options)


def test_finance_without_orders_returns_zero_utilities():
    context = load_demo_context()
    context["orders"] = []

    payoff = PayoffModel().evaluate_finance(context)

    assert payoff.selected_index == 0
    assert all(option.own_utility == 0 for option in payoff.options)


def test_enterprise_events_produce_different_procurement_payoffs():
    loader = ScenarioLoader()
    model = PayoffModel()

    first = model.evaluate_procurement(loader.load_context("EVT-000006"))
    second = model.evaluate_procurement(loader.load_context("EVT-000016"))

    first_utilities = [option.own_utility for option in first.options]
    second_utilities = [option.own_utility for option in second.options]
    assert (
        first.selected_label != second.selected_label
        or first_utilities != second_utilities
    )


def test_payoff_model_is_deterministic():
    context = load_demo_context()
    model = PayoffModel()

    assert model.evaluate_procurement(context) == model.evaluate_procurement(context)
    assert model.evaluate_logistics(context) == model.evaluate_logistics(context)
    assert model.evaluate_finance(context) == model.evaluate_finance(context)
