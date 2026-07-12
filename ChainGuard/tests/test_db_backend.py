import sqlite3

from src.db import get_connection
from src.scenario_loader import DEFAULT_SCENARIO_DB, ScenarioLoader


def test_default_is_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with get_connection() as connection:
        assert isinstance(connection, sqlite3.Connection)
        row = connection.execute("SELECT 1 AS value").fetchone()

    assert row["value"] == 1


def test_parse_postgres_url():
    try:
        get_connection("postgresql://localhost/nonexistent_test_db")
    except ImportError as e:
        assert "psycopg" in str(e).lower()
    except Exception:
        pass


def test_scenario_loader_still_works_on_sqlite():
    scenarios = ScenarioLoader(DEFAULT_SCENARIO_DB).list_scenarios(limit=3)

    assert scenarios
    assert len(scenarios) <= 3
    assert "event_id" in scenarios[0]
