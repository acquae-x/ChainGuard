import json
from dataclasses import asdict

from src.constraint_solver import ConstraintAnalysis, ConstraintSolver
from src.data_loader import load_demo_context
from src.game_model import AgentPayoff, PayoffModel, StrategyOption
from src.orchestrator import DecisionOrchestrator
from src.scenario_loader import ScenarioLoader


def _demo_payoffs(context=None):
    context = context or load_demo_context()
    model = PayoffModel()
    return {
        "procurement": model.evaluate_procurement(context),
        "logistics": model.evaluate_logistics(context),
        "finance": model.evaluate_finance(context),
    }


def _synthetic_payoff(agent_name, selected_index=0):
    options = [
        StrategyOption(
            label=f"{agent_name}-selected",
            parameters={
                "coverage_rate": 1.0,
                "estimated_hours": 10.0,
                "cost_multiplier": 1.0,
            },
            own_utility=90.0,
            system_utility=90.0,
        ),
        StrategyOption(
            label=f"{agent_name}-other-1",
            parameters={
                "coverage_rate": 1.0,
                "estimated_hours": 12.0,
                "cost_multiplier": 1.0,
            },
            own_utility=50.0,
            system_utility=50.0,
        ),
        StrategyOption(
            label=f"{agent_name}-other-2",
            parameters={
                "coverage_rate": 1.0,
                "estimated_hours": 14.0,
                "cost_multiplier": 1.0,
            },
            own_utility=40.0,
            system_utility=40.0,
        ),
    ]
    return AgentPayoff(
        agent_name=agent_name,
        options=options,
        selected_index=selected_index,
        selected_label=options[selected_index].label,
    )


def test_fixed_demo_returns_valid_constraint_analysis():
    analysis = ConstraintSolver().solve(_demo_payoffs(), load_demo_context())

    assert isinstance(analysis, ConstraintAnalysis)
    assert analysis.feasible is True
    assert analysis.feasible_count >= 1
    assert set(analysis.optimal_combo) == {
        "procurement",
        "logistics",
        "finance",
    }


def test_constraint_analysis_to_dict_is_json_serializable():
    analysis = ConstraintSolver().solve(_demo_payoffs(), load_demo_context())
    payload = analysis.to_dict()

    assert payload == asdict(analysis)
    assert json.dumps(payload, ensure_ascii=False)


def test_tightening_cost_constraint_reduces_feasible_count():
    solver = ConstraintSolver()
    context = load_demo_context()
    payoffs = _demo_payoffs(context)
    default = solver.solve(payoffs, context)
    tight = solver.solve(
        payoffs,
        context,
        {"MAX_COMBINED_COST_MULT": 1.0},
    )

    assert tight.feasible_count < default.feasible_count


def test_no_feasible_combo_returns_fallback_with_violations():
    analysis = ConstraintSolver().solve(
        _demo_payoffs(),
        load_demo_context(),
        {
            "MIN_SUPPLY_COVERAGE": 1.1,
            "MAX_DELIVERY_HOURS": 1.0,
            "MAX_COMBINED_COST_MULT": 1.0,
        },
    )

    assert analysis.feasible is False
    assert analysis.feasible_count == 0
    assert analysis.optimal_combo
    assert analysis.constraint_violations


def test_recommended_changes_empty_when_individual_selection_is_optimal():
    payoffs = {
        "procurement": _synthetic_payoff("采购 Agent"),
        "logistics": _synthetic_payoff("物流 Agent"),
        "finance": _synthetic_payoff("财务 Agent"),
    }

    analysis = ConstraintSolver().solve(payoffs, load_demo_context())

    assert analysis.feasible is True
    assert analysis.recommended_changes == []
    assert analysis.optimal_system_utility == analysis.individual_system_utility


def test_recommended_changes_identify_agents_to_switch():
    analysis = ConstraintSolver().solve(_demo_payoffs(), load_demo_context())

    assert analysis.recommended_changes
    assert any("物流" in change for change in analysis.recommended_changes)
    assert any("采购" in change for change in analysis.recommended_changes)


def test_optimal_system_utility_not_below_individual_when_feasible():
    analysis = ConstraintSolver().solve(_demo_payoffs(), load_demo_context())

    assert analysis.feasible is True
    assert analysis.optimal_system_utility >= analysis.individual_system_utility


def test_enterprise_event_constraint_solver_runs():
    context = ScenarioLoader().load_context("EVT-000006")
    analysis = ConstraintSolver().solve(_demo_payoffs(context), context)

    assert analysis.optimal_combo
    assert analysis.feasible_count >= 0


def test_different_enterprise_events_have_different_individual_utility():
    loader = ScenarioLoader()
    solver = ConstraintSolver()
    first_context = loader.load_context("EVT-000006")
    second_context = loader.load_context("EVT-000016")

    first = solver.solve(_demo_payoffs(first_context), first_context)
    second = solver.solve(_demo_payoffs(second_context), second_context)

    assert first.individual_system_utility != second.individual_system_utility


def test_constraint_parameters_change_feasible_count_tight_and_loose():
    context = ScenarioLoader().load_context("EVT-000006")
    payoffs = _demo_payoffs(context)
    solver = ConstraintSolver()

    default = solver.solve(payoffs, context)
    tight = solver.solve(payoffs, context, {"MAX_COMBINED_COST_MULT": 1.0})
    loose = solver.solve(
        payoffs,
        context,
        {
            "MAX_COMBINED_COST_MULT": 10.0,
            "MAX_DELIVERY_HOURS": 10_000.0,
        },
    )

    assert tight.feasible_count < default.feasible_count
    assert loose.feasible_count > default.feasible_count


def test_orchestrator_result_contains_constraint_analysis():
    result = DecisionOrchestrator().run_demo()
    payload = result.to_dict()

    assert "constraint_analysis" in payload
    assert result.inventory_risk["inventory_risk_index"] == 70.25
    assert result.constraint_analysis["feasible"] is True


def test_all_combos_has_27_entries():
    """solve() should expose all 27 strategy combinations."""
    result = ConstraintSolver().solve(
        payoffs=_demo_payoffs(),
        context=load_demo_context(),
    )

    assert len(result.all_combos) == 27


def test_all_combos_each_has_required_keys():
    """Every combo point must carry chart fields."""
    result = ConstraintSolver().solve(
        payoffs=_demo_payoffs(),
        context=load_demo_context(),
    )
    required_keys = {
        "cost_multiplier",
        "system_utility",
        "feasible",
        "is_optimal",
        "label",
    }

    for combo in result.all_combos:
        assert required_keys.issubset(combo.keys()), f"Missing keys in {combo}"


def test_exactly_one_optimal_in_all_combos():
    """Exactly one combo should be marked is_optimal=True, and it must be feasible."""
    result = ConstraintSolver().solve(
        payoffs=_demo_payoffs(),
        context=load_demo_context(),
    )
    optimal_points = [combo for combo in result.all_combos if combo["is_optimal"]]

    assert len(optimal_points) == 1
    assert optimal_points[0]["feasible"] is True
    assert abs(optimal_points[0]["system_utility"] - result.optimal_system_utility) < 0.1
