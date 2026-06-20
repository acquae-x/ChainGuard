from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.domain_models import DecisionResult


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
        audit_entry={"decision_status": "ok"},
    )


class _MockOrchestrator:
    def run_demo(self) -> DecisionResult:
        return _mock_result()


@pytest.fixture
def client_with_rbac(monkeypatch):
    monkeypatch.setenv(
        "CHAINGUARD_API_KEYS",
        "viewer-key:viewer,operator-key:operator",
    )
    import src.api as api_module

    monkeypatch.setattr(api_module, "_API_KEYS", api_module._load_api_keys())
    monkeypatch.setattr(api_module, "DecisionOrchestrator", _MockOrchestrator)
    return TestClient(api_module.app)


@pytest.fixture
def client_open_mode(monkeypatch):
    monkeypatch.delenv("CHAINGUARD_API_KEYS", raising=False)
    import src.api as api_module

    monkeypatch.setattr(api_module, "_API_KEYS", {})
    monkeypatch.setattr(api_module, "DecisionOrchestrator", _MockOrchestrator)
    return TestClient(api_module.app)


def test_insufficient_permission_returns_403(client_with_rbac):
    resp = client_with_rbac.post(
        "/decisions/demo",
        headers={"X-API-Key": "viewer-key"},
    )

    assert resp.status_code == 403


def test_sufficient_permission_allows(client_with_rbac):
    resp = client_with_rbac.post(
        "/decisions/demo",
        headers={"X-API-Key": "operator-key"},
    )

    assert resp.status_code == 200


def test_missing_key_returns_401(client_with_rbac):
    resp = client_with_rbac.post("/decisions/demo")

    assert resp.status_code == 401


def test_open_mode_backward_compatible(client_open_mode):
    resp = client_open_mode.post("/decisions/demo")

    assert resp.status_code == 200
