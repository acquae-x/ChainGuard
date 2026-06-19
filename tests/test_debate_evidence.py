import json

from src.constraint_solver import ConstraintAnalysis, ConstraintSolver
from src.debate import DebateEngine
from src.evidence import DebateResult
from src.game_model import AgentPayoff, PayoffModel, StrategyOption
from src.orchestrator import DecisionOrchestrator
from src.scenario_loader import ScenarioLoader
from src.data_loader import load_demo_context


def _fixed_payoffs(context=None):
    context = context or load_demo_context()
    model = PayoffModel()
    return {
        "procurement": model.evaluate_procurement(context),
        "logistics": model.evaluate_logistics(context),
        "finance": model.evaluate_finance(context),
    }


def _selected_payoff(agent_name, selected_label):
    options = [
        StrategyOption(
            label=selected_label,
            parameters={},
            own_utility=100.0,
            system_utility=50.0,
        ),
        StrategyOption(
            label=f"{selected_label}-alternative",
            parameters={},
            own_utility=80.0,
            system_utility=80.0,
        ),
        StrategyOption(
            label=f"{selected_label}-unused",
            parameters={},
            own_utility=60.0,
            system_utility=40.0,
        ),
    ]
    return AgentPayoff(
        agent_name=agent_name,
        options=options,
        selected_index=0,
        selected_label=selected_label,
    )


def _synthetic_payoffs(recommended_own_utility):
    procurement = AgentPayoff(
        agent_name="采购 Agent",
        options=[
            StrategyOption(
                label="采购当前策略",
                parameters={},
                own_utility=100.0,
                system_utility=50.0,
            ),
            StrategyOption(
                label="采购推荐策略",
                parameters={},
                own_utility=recommended_own_utility,
                system_utility=90.0,
            ),
            StrategyOption(
                label="采购备用策略",
                parameters={},
                own_utility=20.0,
                system_utility=20.0,
            ),
        ],
        selected_index=0,
        selected_label="采购当前策略",
    )
    return {
        "procurement": procurement,
        "logistics": _selected_payoff("物流 Agent", "物流当前策略"),
        "finance": _selected_payoff("财务 Agent", "财务当前策略"),
    }


def _constraint_analysis(payoffs, procurement_label=None):
    return ConstraintAnalysis(
        feasible_count=27,
        feasible=True,
        optimal_combo={
            "procurement": procurement_label or payoffs["procurement"].selected.label,
            "logistics": payoffs["logistics"].selected.label,
            "finance": payoffs["finance"].selected.label,
        },
        optimal_system_utility=0.0,
        individual_system_utility=round(
            sum(payoff.selected.system_utility for payoff in payoffs.values()),
            2,
        ),
        recommended_changes=[],
        constraint_violations=[],
    )


def test_no_rounds_when_optimal_combo_matches_individual_choices():
    payoffs = _fixed_payoffs()
    constraint_analysis = _constraint_analysis(payoffs)

    result = DebateEngine().run(payoffs, constraint_analysis)

    assert result.rounds == []
    assert result.strategies_updated == []
    assert result.converged is True


def test_accepts_change_when_own_utility_loss_is_within_threshold():
    payoffs = _synthetic_payoffs(recommended_own_utility=90.0)
    constraint_analysis = _constraint_analysis(payoffs, "采购推荐策略")

    result = DebateEngine().run(payoffs, constraint_analysis, acceptance_threshold=0.20)

    assert result.rounds[0].action == "accepted"
    assert result.strategies_updated == ["procurement"]
    assert result.final_strategies["procurement"] == "采购推荐策略"
    assert result.rounds[0].own_utility_delta == -10.0


def test_counters_change_when_own_utility_loss_exceeds_threshold():
    payoffs = _synthetic_payoffs(recommended_own_utility=50.0)
    constraint_analysis = _constraint_analysis(payoffs, "采购推荐策略")

    result = DebateEngine().run(payoffs, constraint_analysis, acceptance_threshold=0.20)

    assert result.rounds[0].action == "countered"
    assert result.strategies_updated == []
    assert result.final_strategies["procurement"] == "采购当前策略"
    assert result.rounds[0].own_utility_delta == 0.0


def test_fixed_demo_debate_engine_returns_result():
    context = load_demo_context()
    payoffs = _fixed_payoffs(context)
    constraint_analysis = ConstraintSolver().solve(payoffs, context)

    result = DebateEngine().run(payoffs, constraint_analysis)

    assert isinstance(result, DebateResult)
    assert result.total_rounds == 2
    assert result.rounds[0].evidence.metric == "system_utility"
    assert result.system_utility_after >= result.system_utility_before


def test_debate_result_to_dict_is_json_serializable():
    context = load_demo_context()
    payoffs = _fixed_payoffs(context)
    constraint_analysis = ConstraintSolver().solve(payoffs, context)

    payload = DebateEngine().run(payoffs, constraint_analysis).to_dict()

    assert json.dumps(payload, ensure_ascii=False)
    assert isinstance(payload["rounds"][0]["evidence"], dict)


def test_orchestrator_result_contains_debate_result():
    result = DecisionOrchestrator().run_demo()
    payload = result.to_dict()

    assert "debate_result" in payload
    assert isinstance(result.debate_result, dict)
    assert result.debate_result["system_utility_after"] >= result.debate_result[
        "system_utility_before"
    ]


def test_acceptance_threshold_changes_updated_strategy_count():
    context = load_demo_context()
    payoffs = _fixed_payoffs(context)
    constraint_analysis = ConstraintSolver().solve(payoffs, context)

    strict = DebateEngine().run(
        payoffs,
        constraint_analysis,
        acceptance_threshold=0.0,
    )
    permissive = DebateEngine().run(
        payoffs,
        constraint_analysis,
        acceptance_threshold=1.0,
    )

    assert len(permissive.strategies_updated) > len(strict.strategies_updated)
    assert strict.strategies_updated != permissive.strategies_updated


def test_system_utility_after_never_decreases():
    context = load_demo_context()
    payoffs = _fixed_payoffs(context)
    constraint_analysis = ConstraintSolver().solve(payoffs, context)

    result = DebateEngine().run(payoffs, constraint_analysis, acceptance_threshold=1.0)

    assert result.system_utility_after >= result.system_utility_before


def test_different_enterprise_events_produce_different_debate_results():
    loader = ScenarioLoader()
    first_context = loader.load_context("EVT-000006")
    second_context = loader.load_context("EVT-000016")
    first_payoffs = _fixed_payoffs(first_context)
    second_payoffs = _fixed_payoffs(second_context)
    solver = ConstraintSolver()

    first = DebateEngine().run(
        first_payoffs,
        solver.solve(first_payoffs, first_context),
    )
    second = DebateEngine().run(
        second_payoffs,
        solver.solve(second_payoffs, second_context),
    )

    assert (
        first.total_rounds != second.total_rounds
        or first.final_strategies != second.final_strategies
    )


def test_missing_recommended_option_is_skipped():
    payoffs = _fixed_payoffs()
    constraint_analysis = ConstraintAnalysis(
        feasible_count=27,
        feasible=True,
        optimal_combo={
            "procurement": "不存在的策略",
            "logistics": payoffs["logistics"].selected.label,
            "finance": payoffs["finance"].selected.label,
        },
        optimal_system_utility=0.0,
        individual_system_utility=100.0,
        recommended_changes=[],
        constraint_violations=[],
    )

    result = DebateEngine().run(payoffs, constraint_analysis)

    assert result.rounds == []
    assert result.strategies_updated == []
