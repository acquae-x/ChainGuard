from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import app
from src.domain_models import DecisionResult


client = TestClient(app)


def _mock_result() -> DecisionResult:
    return DecisionResult(
        risk_weights={},
        thresholds={},
        context={},
        inventory_risk={"risk_index": 75.0, "warning_level": "yellow"},
        proposals=[],
        conflict={},
        rebuttal={},
        arbitration={},
        experience_card={},
        constraint_analysis={},
        debate_result={},
        experience_references={},
        explanation={},
        audit_entry={"decision_status": "auto_approved"},
    )


def test_health_returns_ok():
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_scenarios_returns_list():
    scenarios = [
        {
            "event_id": "EVT-000001",
            "event_title": "Port delay",
            "event_type": "port_shutdown",
            "severity": "HIGH",
            "risk_score": 82.5,
            "event_status": "active",
        }
    ]
    with patch("src.api.ScenarioLoader") as mock_loader:
        mock_loader.return_value.list_scenarios.return_value = scenarios
        resp = client.get("/scenarios")

    assert resp.status_code == 200
    assert "scenarios" in resp.json()
    assert "count" in resp.json()
    assert isinstance(resp.json()["scenarios"], list)
    assert resp.json()["count"] == 1


def test_demo_decision_returns_200():
    with patch("src.api.DecisionOrchestrator") as mock_orch:
        mock_orch.return_value.run_demo.return_value = _mock_result()
        resp = client.post("/decisions/demo")

    assert resp.status_code == 200
    assert "audit_entry" in resp.json()


def test_demo_decision_response_has_required_keys():
    with patch("src.api.DecisionOrchestrator") as mock_orch:
        mock_orch.return_value.run_demo.return_value = _mock_result()
        resp = client.post("/decisions/demo")

    payload = resp.json()
    assert "inventory_risk" in payload
    assert "proposals" in payload
    assert "arbitration" in payload
    assert "audit_entry" in payload


def test_scenario_decision_valid_event():
    with patch("src.api.DecisionOrchestrator") as mock_orch, patch(
        "src.api.ScenarioLoader"
    ) as mock_loader:
        mock_orch.return_value.run_scenario.return_value = _mock_result()
        mock_loader.return_value.load_context.return_value = {}
        resp = client.post("/decisions/scenario/EVT-000001")

    assert resp.status_code == 200
    mock_orch.return_value.run_scenario.assert_called_once_with(
        "EVT-000001",
        mock_loader.return_value,
    )


def test_scenario_decision_invalid_event_returns_404():
    with patch("src.api.DecisionOrchestrator") as mock_orch, patch(
        "src.api.ScenarioLoader"
    ):
        mock_orch.return_value.run_scenario.side_effect = ValueError(
            "scenario not found: EVT-INVALID"
        )
        resp = client.post("/decisions/scenario/EVT-INVALID")

    assert resp.status_code == 404
    assert "scenario not found" in resp.json()["detail"]
