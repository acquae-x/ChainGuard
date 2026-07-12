from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import app


def test_open_mode_health_no_key_required():
    with patch("src.api._API_KEYS", {}):
        client = TestClient(app)
        resp = client.get("/health")

    assert resp.status_code == 200


def test_key_mode_valid_key_returns_200():
    with patch("src.api._API_KEYS", {"demo-key": "admin"}):
        client = TestClient(app)
        resp = client.get("/health", headers={"X-API-Key": "demo-key"})

    assert resp.status_code == 200


def test_key_mode_invalid_key_returns_401():
    with patch("src.api._API_KEYS", {"valid-key": "admin"}):
        client = TestClient(app)
        resp = client.get("/health", headers={"X-API-Key": "wrong-key"})

    assert resp.status_code == 401


def test_key_mode_missing_key_returns_401():
    with patch("src.api._API_KEYS", {"valid-key": "admin"}):
        client = TestClient(app)
        resp = client.get("/health")

    assert resp.status_code == 401


def test_auth_status_open_mode():
    with patch("src.api._API_KEYS", {}):
        client = TestClient(app)
        resp = client.get("/auth/status")

    assert resp.status_code == 200
    assert resp.json()["mode"] == "open"
    assert resp.json()["role"] == "admin"


def test_auth_status_key_mode_shows_role():
    with patch("src.api._API_KEYS", {"analyst-key": "readonly"}):
        client = TestClient(app)
        resp = client.get(
            "/auth/status",
            headers={"X-API-Key": "analyst-key"},
        )

    assert resp.status_code == 200
    assert resp.json()["role"] == "readonly"
    assert resp.json()["mode"] == "key-required"
