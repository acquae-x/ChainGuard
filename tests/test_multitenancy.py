import sqlite3
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.db import get_connection
from src.domain_models import DecisionResult
from src.scenario_loader import ScenarioLoader


@pytest.fixture
def two_tenant_dbs():
    """Create temporary SQLite files for default and tenant_a."""
    tenant_dir = Path("tests/_runtime_tmp") / f"tenant_{uuid.uuid4().hex}"
    tenant_dir.mkdir(parents=True, exist_ok=True)
    db_default = tenant_dir / "main.db"
    db_tenant = tenant_dir / "main.tenant_a.db"
    for db_path, marker in [(db_default, "default"), (db_tenant, "tenant_a")]:
        with sqlite3.connect(db_path) as connection:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("CREATE TABLE test_marker (id TEXT)")
            connection.execute("INSERT INTO test_marker VALUES (?)", (marker,))
            connection.commit()
    yield tenant_dir
    shutil.rmtree(tenant_dir, ignore_errors=True)


def test_default_tenant_matches_current_behavior():
    with get_connection(tenant_id="default") as connection:
        row = connection.execute("SELECT 1 AS value").fetchone()

    assert row["value"] == 1
    assert ScenarioLoader().list_scenarios(limit=1)


def test_two_tenants_isolated(two_tenant_dbs: Path):
    base_url = f"sqlite:///{two_tenant_dbs}/main.db"

    with get_connection(base_url, tenant_id="default") as connection:
        row_default = connection.execute("SELECT id FROM test_marker").fetchone()
    with get_connection(base_url, tenant_id="tenant_a") as connection:
        row_tenant = connection.execute("SELECT id FROM test_marker").fetchone()

    assert row_default["id"] == "default"
    assert row_tenant["id"] == "tenant_a"


def test_unknown_tenant_rejected():
    with pytest.raises(ValueError, match="未知租户"):
        get_connection(tenant_id="nonexistent_xyz_12345")


def test_api_response_includes_tenant_id(monkeypatch):
    import src.api as api_module

    monkeypatch.setattr(api_module, "DecisionOrchestrator", _MockOrchestrator)
    client = TestClient(api_module.app)

    response = client.post("/decisions/demo", headers={"X-Tenant-ID": "default"})

    assert response.status_code == 200
    assert response.json().get("tenant_id") == "default"


class _MockOrchestrator:
    def run_demo(self) -> DecisionResult:
        return DecisionResult(
            risk_weights={},
            thresholds={},
            context={},
            inventory_risk={"risk_index": 75.0},
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
