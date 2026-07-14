import json
import re
from pathlib import Path
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


def test_monitoring_bootstrap_exports_job_gauge_and_node_exporter():
    Metrics.reset()
    Metrics.set_jobs_pending(2)
    assert _plain_metric_value(Metrics.render(), "chainguard_jobs_pending") == pytest.approx(2.0)
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    prometheus = Path("config/prometheus.yml").read_text(encoding="utf-8")
    assert "node-exporter:" in compose
    assert "node-exporter:9100" in prometheus


def _metric_value(text: str, name: str, status: str) -> float:
    pattern = re.compile(rf'^{re.escape(name)}{{status="{re.escape(status)}"}}\s+([0-9.]+)$')
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            return float(match.group(1))
    raise AssertionError(f"metric {name} with status={status!r} not found in:\n{text}")


def _plain_metric_value(text: str, name: str) -> float:
    for line in text.splitlines():
        if line.startswith(f"{name} "):
            return float(line.split()[-1])
    raise AssertionError(f"metric {name!r} not found in:\n{text}")
