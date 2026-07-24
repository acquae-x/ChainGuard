from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from src.api import app
from src.webapi.jwt_tokens import create_metrics_token


client = TestClient(app)


def test_missing_api_key_configuration_does_not_open_metrics(monkeypatch):
    """没有 API-key 配置时，旧 X-API-Key 也不能打开监控端点。"""
    monkeypatch.delenv("CHAINGUARD_API_KEYS", raising=False)

    resp = client.get("/metrics", headers={"X-API-Key": "legacy-admin-key"})

    assert resp.status_code == 401


def test_valid_metrics_service_jwt_allows_prometheus_scrape():
    token = create_metrics_token(expires=timedelta(minutes=5))

    with patch("src.webapi.jobs.sync_jobs_pending_metric") as sync_metric:
        resp = client.get(
            "/metrics",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert "chainguard_jobs_pending" in resp.text
    sync_metric.assert_called_once()


def test_prometheus_scrape_config_uses_mounted_bearer_token_file():
    config = yaml.safe_load(
        Path("config/prometheus.yml").read_text(encoding="utf-8")
    )
    chainguard_job = next(
        job for job in config["scrape_configs"] if job["job_name"] == "chainguard"
    )

    assert chainguard_job["metrics_path"] == "/metrics"
    assert chainguard_job["authorization"] == {
        "type": "Bearer",
        "credentials_file": "/run/secrets/chainguard_metrics_token",
    }

    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert (
        "${CHAINGUARD_METRICS_TOKEN_FILE:-./secrets/prometheus.jwt}:"
        "/run/secrets/chainguard_metrics_token:ro"
    ) in compose
