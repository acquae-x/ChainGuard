import sqlite3
from pathlib import Path

import pytest

from src.domain_models import DecisionResult
from src.orchestrator import DecisionOrchestrator
from src.scenario_loader import DEFAULT_SCENARIO_DB, ScenarioLoader


RECOMMENDED_EVENTS = [
    "EVT-000006",
    "EVT-000016",
    "EVT-000037",
    "EVT-000065",
    "EVT-000113",
]


def test_missing_database_raises_clear_error():
    missing_path = Path("tests/_runtime_tmp/missing_scenario_database.db")

    with pytest.raises(FileNotFoundError, match="missing_scenario_database.db"):
        ScenarioLoader(missing_path)


def test_list_scenarios_returns_lightweight_records():
    scenarios = ScenarioLoader(DEFAULT_SCENARIO_DB).list_scenarios(limit=5)

    assert scenarios
    assert len(scenarios) <= 5
    assert {
        "event_id",
        "event_title",
        "event_type",
        "severity",
        "risk_score",
        "event_status",
    } == set(scenarios[0])


def test_load_context_returns_complete_compatible_context():
    context = ScenarioLoader(DEFAULT_SCENARIO_DB).load_context("EVT-000006")

    assert {
        "inventory",
        "orders",
        "suppliers",
        "transport_options",
        "events",
    } == set(context)
    assert context["inventory"]["hourly_consumption"] > 0
    assert context["events"][0]["event_id"] == "EVT-000006"


def test_hourly_consumption_matches_database_daily_consumption():
    loader = ScenarioLoader(DEFAULT_SCENARIO_DB)
    context = loader.load_context("EVT-000006")

    with sqlite3.connect(DEFAULT_SCENARIO_DB) as connection:
        daily_consumption = connection.execute(
            "SELECT daily_consumption FROM materials WHERE material_id = ?",
            (context["inventory"]["material_id"],),
        ).fetchone()[0]

    assert context["inventory"]["hourly_consumption"] == pytest.approx(
        daily_consumption / 24
    )


def test_external_risk_score_matches_database():
    loader = ScenarioLoader(DEFAULT_SCENARIO_DB)
    context = loader.load_context("EVT-000006")

    with sqlite3.connect(DEFAULT_SCENARIO_DB) as connection:
        risk_score = connection.execute(
            "SELECT risk_score FROM disruption_events WHERE event_id = ?",
            ("EVT-000006",),
        ).fetchone()[0]

    assert context["events"][0]["external_risk_score"] == risk_score


def test_run_scenario_returns_decision_result():
    result = DecisionOrchestrator().run_scenario(
        "EVT-000006",
        ScenarioLoader(DEFAULT_SCENARIO_DB),
    )

    assert isinstance(result, DecisionResult)
    assert result.context["events"][0]["event_id"] == "EVT-000006"


def test_recommended_scenarios_produce_data_driven_risk_scores():
    loader = ScenarioLoader(DEFAULT_SCENARIO_DB)
    orchestrator = DecisionOrchestrator()

    risk_scores = [
        orchestrator.run_scenario(event_id, loader).inventory_risk[
            "inventory_risk_index"
        ]
        for event_id in RECOMMENDED_EVENTS
    ]

    assert len(set(risk_scores)) > 1
    assert all(score != pytest.approx(70.25) for score in risk_scores)


def test_unknown_event_raises_clear_error():
    loader = ScenarioLoader(DEFAULT_SCENARIO_DB)

    with pytest.raises(ValueError, match="DOES-NOT-EXIST"):
        loader.load_context("DOES-NOT-EXIST")


def test_route_blockage_disables_ground_alternatives():
    context = ScenarioLoader(DEFAULT_SCENARIO_DB).load_context("EVT-000006")
    availability = {
        option["mode"]: option["available"]
        for option in context["transport_options"]
    }

    assert availability["air"] is True
    assert availability["sea"] is True
    assert availability["truck"] is False
    assert availability["rail"] is False
