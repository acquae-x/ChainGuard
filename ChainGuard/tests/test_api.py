from fastapi.testclient import TestClient

from src.api import app


def test_removed_legacy_routes_are_not_in_openapi():
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert {
        "/health",
        "/scenarios",
        "/decisions/demo",
        "/decisions/scenario/{event_id}",
        "/notifications/pending",
        "/auth/status",
    }.isdisjoint(paths)
