import json
from pathlib import Path

import pytest

from src.observability import Metrics, log_event


def test_log_event_emits_json_fields(capsys):
    log_event("unit_test_event", scenario_type="demo", risk_index=42)

    payload = json.loads(capsys.readouterr().out)
    assert payload["event"] == "unit_test_event"
    assert "timestamp" in payload
    assert payload["scenario_type"] == "demo"
    assert payload["risk_index"] == 42


def test_monitoring_bootstrap_exports_job_gauge_and_node_exporter():
    Metrics.reset()
    Metrics.set_jobs_pending(2)
    assert _plain_metric_value(Metrics.render(), "chainguard_jobs_pending") == pytest.approx(2.0)
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    prometheus = Path("config/prometheus.yml").read_text(encoding="utf-8")
    assert "node-exporter:" in compose
    assert "node-exporter:9100" in prometheus


def _plain_metric_value(text: str, name: str) -> float:
    for line in text.splitlines():
        if line.startswith(f"{name} "):
            return float(line.split()[-1])
    raise AssertionError(f"metric {name!r} not found in:\n{text}")
