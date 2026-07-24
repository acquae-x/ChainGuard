from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.api import app
from src.webapi.auth.security import create_tokens
from src.webapi.database import SessionLocal
from src.webapi.models import User
from src.webapi.seed import seed
from src.webapi.versioning import (
    DeprecationHeadersMiddleware,
    V1_TOP_RISKS_DEPRECATION,
)


def _headers() -> dict[str, str]:
    seed()
    with SessionLocal() as db:
        user = db.get(User, "u-scm_lead")
        return {"Authorization": f"Bearer {create_tokens(user)['token']}"}


def test_deprecated_v1_endpoint_advertises_runtime_migration_headers() -> None:
    response = TestClient(app).get(
        "/api/v1/dashboard/top-risks", headers=_headers()
    )

    assert response.status_code == 200
    assert response.headers["Deprecation"] == V1_TOP_RISKS_DEPRECATION.deprecation_header
    assert response.headers["Sunset"] == V1_TOP_RISKS_DEPRECATION.sunset_header
    assert response.headers["Link"] == '</api/v2/dashboard/top-risks>; rel="successor-version"'


def test_v1_deprecation_is_documented_and_v2_successor_coexists() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    v1_operation = paths["/api/v1/dashboard/top-risks"]["get"]

    assert v1_operation["deprecated"] is True
    assert v1_operation["x-chainguard-deprecation"] == {
        "deprecatedAt": V1_TOP_RISKS_DEPRECATION.deprecated_at.isoformat(),
        "sunsetAt": V1_TOP_RISKS_DEPRECATION.sunset_at.isoformat(),
        "successor": "/api/v2/dashboard/top-risks",
    }
    assert {"Deprecation", "Sunset"}.issubset(v1_operation["responses"]["200"]["headers"])
    assert "/api/v2/dashboard/top-risks" in paths


def test_deprecation_middleware_preserves_an_existing_link_header() -> None:
    test_app = FastAPI()
    test_app.add_middleware(
        DeprecationHeadersMiddleware,
        policies={
            V1_TOP_RISKS_DEPRECATION.key: V1_TOP_RISKS_DEPRECATION,
        },
    )

    @test_app.get("/api/v1/dashboard/top-risks")
    def legacy_endpoint() -> JSONResponse:
        return JSONResponse({}, headers={"Link": '</docs/paging>; rel="help"'})

    response = TestClient(test_app).get("/api/v1/dashboard/top-risks")

    assert response.headers["Link"] == (
        '</docs/paging>; rel="help", '
        '</api/v2/dashboard/top-risks>; rel="successor-version"'
    )
