import pytest

from src.data_loader import load_demo_context
from src.game_analysis import GameAnalyzer, GameAnalysisResult
from src.game_model import AgentPayoff, PayoffModel, StrategyOption
from src.orchestrator import DecisionOrchestrator


def _payoff(agent_name, selected_label, selected_own, selected_system, recommended_own, recommended_system):
    options = [
        StrategyOption(
            label=selected_label,
            parameters={},
            own_utility=selected_own,
            system_utility=selected_system,
        ),
        StrategyOption(
            label=f"{selected_label}-recommended",
            parameters={},
            own_utility=recommended_own,
            system_utility=recommended_system,
        ),
        StrategyOption(
            label=f"{selected_label}-unused",
            parameters={},
            own_utility=10.0,
            system_utility=10.0,
        ),
    ]
    return AgentPayoff(
        agent_name=agent_name,
        options=options,
        selected_index=0,
        selected_label=selected_label,
    )


def _mock_payoffs(recommended_system=90.0, recommended_own=90.0):
    return {
        "procurement": _payoff(
            "procurement",
            "procurement-selfish",
            100.0,
            50.0,
            recommended_own,
            recommended_system,
        ),
        "logistics": _payoff(
            "logistics",
            "logistics-selfish",
            100.0,
            50.0,
            100.0,
            50.0,
        ),
        "finance": _payoff(
            "finance",
            "finance-selfish",
            100.0,
            50.0,
            100.0,
            50.0,
        ),
    }


def _constraint_analysis(payoffs, optimal_procurement=None, individual=150.0, optimal=190.0):
    return {
        "optimal_combo": {
            "procurement": optimal_procurement
            or payoffs["procurement"].options[1].label,
            "logistics": payoffs["logistics"].selected_label,
            "finance": payoffs["finance"].selected_label,
        },
        "optimal_system_utility": optimal,
        "individual_system_utility": individual,
    }


def test_coordination_gain_positive_when_selfish_differs():
    ctx = load_demo_context()
    pm = PayoffModel()
    payoffs = {
        "procurement": pm.evaluate_procurement(ctx),
        "logistics": pm.evaluate_logistics(ctx),
        "finance": pm.evaluate_finance(ctx),
    }
    r = DecisionOrchestrator().run_demo()

    result = GameAnalyzer().analyze(payoffs, r.constraint_analysis, r.debate_result)

    print(f"demo coordination_gain={result.coordination_gain}")
    assert isinstance(result, GameAnalysisResult)
    if result.individual_choices != result.optimal_choices:
        assert result.coordination_gain > 0
    else:
        assert result.coordination_gain == pytest.approx(0.0, abs=0.01)


def test_coordination_gain_zero_when_selfish_equals_optimal():
    payoffs = _mock_payoffs()
    constraint_analysis = {
        "optimal_combo": {
            key: payoff.selected_label for key, payoff in payoffs.items()
        },
        "optimal_system_utility": 150.0,
        "individual_system_utility": 150.0,
    }

    result = GameAnalyzer().analyze(payoffs, constraint_analysis, {})

    assert result.coordination_gain == pytest.approx(0.0, abs=0.01)
    assert result.coordination_gain_pct == pytest.approx(0.0)


def test_all_agent_coordination_fields_present():
    payoffs = _mock_payoffs()

    result = GameAnalyzer().analyze(
        payoffs,
        _constraint_analysis(payoffs),
        {"strategies_updated": ["procurement"]},
    )

    assert len(result.agent_coordination) == 3
    assert result.strategy_space_size == 27
    for coordination in result.agent_coordination:
        assert coordination.selfish_strategy
        assert coordination.optimal_strategy
        assert isinstance(coordination.loss_ratio, float)
        assert isinstance(coordination.within_threshold, bool)
        assert isinstance(coordination.accepted, bool)


def test_is_not_nash_equilibrium():
    payoffs = _mock_payoffs()

    result = GameAnalyzer().analyze(payoffs, _constraint_analysis(payoffs), {})

    assert result.is_nash_equilibrium is False
    assert result.mechanism_type == "cooperative_mechanism_design"


def test_input_change_changes_coordination_gain():
    first_payoffs = _mock_payoffs(recommended_system=90.0)
    second_payoffs = _mock_payoffs(recommended_system=120.0)

    first = GameAnalyzer().analyze(
        first_payoffs,
        _constraint_analysis(first_payoffs, individual=150.0, optimal=190.0),
        {},
    )
    second = GameAnalyzer().analyze(
        second_payoffs,
        _constraint_analysis(second_payoffs, individual=150.0, optimal=220.0),
        {},
    )

    assert first.coordination_gain != second.coordination_gain


def test_zero_individual_utility_no_division_error():
    payoffs = _mock_payoffs()

    result = GameAnalyzer().analyze(
        payoffs,
        _constraint_analysis(payoffs, individual=0.0, optimal=10.0),
        {},
    )

    assert result.coordination_gain == pytest.approx(10.0)
    assert result.coordination_gain_pct == 0.0


def test_missing_optimal_label_falls_back_to_selfish_values():
    payoffs = _mock_payoffs()

    result = GameAnalyzer().analyze(
        payoffs,
        _constraint_analysis(
            payoffs,
            optimal_procurement="missing-strategy",
        ),
        {},
    )

    procurement = next(
        item for item in result.agent_coordination if item.agent == "procurement"
    )
    assert procurement.optimal_strategy == "missing-strategy"
    assert procurement.optimal_own_utility == procurement.selfish_own_utility
    assert procurement.optimal_system_utility == procurement.selfish_system_utility
    assert procurement.within_threshold is True
