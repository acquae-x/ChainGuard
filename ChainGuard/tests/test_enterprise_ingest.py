import pytest


def test_import_demo_csvs_into_tenant_and_smoke_ok():
    from src.data_source import tenant_scenario_db_path
    from src.enterprise_ingest import import_tenant_from_dir

    tenant_id = "itest_ok_i43"
    db = tenant_scenario_db_path(tenant_id)
    db.unlink(missing_ok=True)
    try:
        res = import_tenant_from_dir(tenant_id, "demo_assets/enterprise/csv")

        assert res.tenant_id == tenant_id
        assert res.ok_tables >= 5
        assert res.smoke_ok is True
        assert "冒烟校验通过" in res.smoke_message
        assert db.exists()
    finally:
        db.unlink(missing_ok=True)


def test_import_empty_dir_smoke_fails(tmp_path):
    from src.data_source import tenant_scenario_db_path
    from src.enterprise_ingest import import_tenant_from_dir

    tenant_id = "itest_empty_i43"
    db = tenant_scenario_db_path(tenant_id)
    db.unlink(missing_ok=True)
    try:
        res = import_tenant_from_dir(tenant_id, str(tmp_path))

        assert res.ok_tables == 0
        assert res.smoke_ok is False
        assert "冒烟校验失败" in res.smoke_message
    finally:
        db.unlink(missing_ok=True)


def test_import_rejects_illegal_tenant(tmp_path):
    from src.enterprise_ingest import import_tenant_from_dir

    with pytest.raises(ValueError):
        import_tenant_from_dir("default", str(tmp_path))
