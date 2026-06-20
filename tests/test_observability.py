import json
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.domain_models import DecisionResult
from src.observability import Metrics, log_event


client = TestClient(app)


def _mock_result() -> DecisionResult:
    return DecisionResult(
        risk_weights={},
        thresholds={},
        context={},
        inventory_risk={"inventory_risk_index": 75.0, "warning_level": "yellow"},
        proposals=[],
        conflict={},
        rebuttal={},
        arbitration={},
        experience_card={},
        constraint_analysis={},
        debate_result={},
        experience_references={},
        explanation={},
        audit_entry={
            "event_type": "typhoon_port_shutdown",
            "inventory_risk_index": 75.0,
            "human_approval_required": False,
            "decision_status": "ok",
        },
    )


def test_metrics_increment_after_decision():
    Metrics.reset()
    with patch("src.api.DecisionOrchestrator") as mock_orch:
        mock_orch.return_value.run_demo.return_value = _mock_result()
        resp = client.post("/decisions/demo")

    assert resp.status_code == 200

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    assert _metric_value(
        metrics_resp.text,
        "chainguard_decisions_total",
        "ok",
    ) == pytest.approx(1.0)


def test_log_event_emits_json_fields(capsys):
    log_event("unit_test_event", scenario_type="demo", risk_index=42)

    payload = json.loads(capsys.readouterr().out)
    assert payload["event"] == "unit_test_event"
    assert "timestamp" in payload
    assert payload["scenario_type"] == "demo"
    assert payload["risk_index"] == 42


def test_health_reports_dependencies():
    resp = client.get("/health")

    assert resp.status_code == 200
    dependencies = resp.json()["dependencies"]
    assert "enterprise_db" in dependencies
    assert isinstance(dependencies["enterprise_db"], bool)


def _metric_value(text: str, name: str, status: str) -> float:
    pattern = re.compile(rf'^{re.escape(name)}{{status="{re.escape(status)}"}}\s+([0-9.]+)$')
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            return float(match.group(1))
    raise AssertionError(f"metric {name} with status={status!r} not found in:\n{text}")
