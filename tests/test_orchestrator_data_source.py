from src.data_source import DataSource, demo_source
from src.orchestrator import DecisionOrchestrator
from src.scenario_loader import ScenarioLoader


def _isolated_source(tmp_path, *, scenario_db_path: str = "") -> DataSource:
    return DataSource(
        kind="enterprise",
        tenant_id="isol_i43",
        label="isolated",
        scenario_db_path=scenario_db_path,
        experience_cards_path=str(tmp_path / "experience_cards_isolated.json"),
        audit_log_path=str(tmp_path / "audit_isolated.jsonl"),
    )


def test_run_demo_with_data_source_writes_to_tenant_audit(tmp_path):
    audit_path = tmp_path / "audit_isolated.jsonl"
    ds = _isolated_source(tmp_path)

    DecisionOrchestrator().run_demo(data_source=ds)

    assert audit_path.exists()
    assert audit_path.read_text(encoding="utf-8").strip()


def test_run_demo_default_unchanged():
    result = DecisionOrchestrator().run_demo()

    assert result.audit_entry is not None


def test_run_scenario_with_data_source_writes_to_tenant_audit(tmp_path):
    base = demo_source()
    loader = ScenarioLoader(base.scenario_db_path)
    event_id = loader.list_scenarios(limit=1)[0]["event_id"]
    ds = _isolated_source(tmp_path, scenario_db_path=base.scenario_db_path)
    audit_path = tmp_path / "audit_isolated.jsonl"

    DecisionOrchestrator().run_scenario(event_id, loader, data_source=ds)

    assert audit_path.exists()
    assert audit_path.read_text(encoding="utf-8").strip()
