from pathlib import Path

import pytest


def test_demo_source_uses_global_paths():
    from src.data_source import demo_source

    ds = demo_source()

    assert ds.tenant_id == "default"
    assert ds.experience_cards_path == "data/experience_cards.json"
    assert ds.audit_log_path == "data/audit_log.jsonl"


def test_enterprise_source_paths_are_tenant_scoped():
    from src import data_source as ds_mod

    fake_db = ds_mod.tenant_scenario_db_path("acme_i43")
    fake_db.parent.mkdir(parents=True, exist_ok=True)
    fake_db.write_bytes(b"")
    try:
        ds = ds_mod.enterprise_source("acme_i43")

        assert ds.tenant_id == "acme_i43"
        assert ds.experience_cards_path == "data/experience_cards.acme_i43.json"
        assert ds.audit_log_path == "data/audit_log.acme_i43.jsonl"
        assert ds.experience_cards_path != "data/experience_cards.json"
        assert ds.audit_log_path != "data/audit_log.jsonl"
        assert "acme_i43" in ds.scenario_db_path
    finally:
        fake_db.unlink(missing_ok=True)


@pytest.mark.parametrize("tenant_id", ["default", "../etc", "", " bad tenant "])
def test_illegal_or_default_tenant_rejected(tenant_id):
    from src.data_source import enterprise_source

    with pytest.raises(ValueError):
        enterprise_source(tenant_id)


def test_missing_enterprise_database_rejected():
    from src.data_source import enterprise_source, tenant_scenario_db_path

    tenant_id = "missing_i43"
    tenant_scenario_db_path(tenant_id).unlink(missing_ok=True)

    with pytest.raises(ValueError):
        enterprise_source(tenant_id, require_exists=True)


def test_tenant_scenario_db_path_matches_suffix_convention():
    from src.data_source import tenant_scenario_db_path

    path = tenant_scenario_db_path("tenant_x")

    assert isinstance(path, Path)
    assert path.name == "chainguard_enterprise_demo.tenant_x.db"
