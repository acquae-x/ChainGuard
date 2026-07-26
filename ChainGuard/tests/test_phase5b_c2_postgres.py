"""PostgreSQL-only acceptance for C2 database invariants.

Run explicitly against a disposable database:

    CHAINGUARD_TEST_POSTGRES_URL=postgresql+psycopg://... \
      python -m pytest tests/test_phase5b_c2_postgres.py -q

The regular suite skips this module so it never points at a developer or
production database by accident.
"""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.webapi.entity_mapping import upsert_entities
from src.webapi.models import Material


POSTGRES_URL = os.getenv("CHAINGUARD_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set CHAINGUARD_TEST_POSTGRES_URL to a disposable migrated PostgreSQL database",
)


@pytest.fixture()
def pg_session():
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def _expect_integrity_error(session: Session, statement, params: dict[str, object]) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(statement, params)
        session.flush()


def test_postgresql_business_key_and_tenant_isolation(pg_session: Session):
    prefix = uuid.uuid4().hex
    upsert_entities(pg_session, f"tenant-a-{prefix}", "material", [{"material_id": "MAT-SAME", "daily_consumption": 24}])
    upsert_entities(pg_session, f"tenant-b-{prefix}", "material", [{"material_id": "MAT-SAME", "daily_consumption": 48}])
    pg_session.flush()

    rows = list(pg_session.scalars(select(Material).where(Material.material_id == "MAT-SAME", Material.tenant_id.in_([f"tenant-a-{prefix}", f"tenant-b-{prefix}"]))))
    assert {row.tenant_id: row.daily_consumption for row in rows} == {
        f"tenant-a-{prefix}": 24.0,
        f"tenant-b-{prefix}": 48.0,
    }

    _expect_integrity_error(
        pg_session,
        text("INSERT INTO materials (id, tenant_id, material_id) VALUES (:id, :tenant, 'MAT-SAME')"),
        {"id": f"duplicate-{prefix}", "tenant": f"tenant-a-{prefix}"},
    )


def test_postgresql_composite_foreign_keys_block_cross_tenant_refs(pg_session: Session):
    prefix = uuid.uuid4().hex
    pg_session.execute(
        text("INSERT INTO materials (id, tenant_id, material_id) VALUES (:id, :tenant, 'MAT-1')"),
        {"id": f"material-{prefix}", "tenant": f"tenant-a-{prefix}"},
    )
    pg_session.execute(
        text("INSERT INTO suppliers (id, tenant_id, supplier_id) VALUES (:id, :tenant, 'SUP-1')"),
        {"id": f"supplier-{prefix}", "tenant": f"tenant-a-{prefix}"},
    )
    pg_session.flush()

    _expect_integrity_error(
        pg_session,
        text(
            "INSERT INTO supplier_materials "
            "(id, tenant_id, supplier_material_id, supplier_id, material_id) "
            "VALUES (:id, :tenant, 'SM-1', 'SUP-1', 'MAT-1')"
        ),
        {"id": f"relation-{prefix}", "tenant": f"tenant-b-{prefix}"},
    )


def test_postgresql_partial_unique_index_allows_one_active_per_tenant(pg_session: Session):
    prefix = uuid.uuid4().hex
    tenant_a = f"tenant-a-{prefix}"
    tenant_b = f"tenant-b-{prefix}"
    statement = text(
        "INSERT INTO tenant_configs "
        "(id, tenant_id, config_type, payload, version, source, is_active) "
        "VALUES (:id, :tenant, 'thresholds', CAST(:payload AS json), :version, 'expert', :active)"
    )
    pg_session.execute(statement, {"id": f"a1-{prefix}", "tenant": tenant_a, "payload": "{}", "version": 1, "active": True})
    pg_session.execute(statement, {"id": f"a2-{prefix}", "tenant": tenant_a, "payload": "{}", "version": 2, "active": False})
    pg_session.execute(statement, {"id": f"b1-{prefix}", "tenant": tenant_b, "payload": "{}", "version": 1, "active": True})
    pg_session.flush()

    _expect_integrity_error(
        pg_session,
        statement,
        {"id": f"a3-{prefix}", "tenant": tenant_a, "payload": "{}", "version": 3, "active": True},
    )


def test_postgresql_frozen_0005_backfill_uses_core_snapshot(pg_session: Session):
    prefix = uuid.uuid4().hex
    tenant = f"tenant-frozen-{prefix}"
    timestamp = "2026-07-18T08:00:00+00:00"
    statement = text(
        "INSERT INTO data_records "
        "(id, tenant_id, resource_type, name, payload, created_at, updated_at) "
        "VALUES (:id, :tenant, :resource_type, :name, CAST(:payload AS json), :created_at, :updated_at)"
    )
    pg_session.execute(statement, {
        "id": f"legacy-good-{prefix}", "tenant": tenant, "resource_type": "material", "name": "PG芯片",
        "payload": '{"materialId":"MAT-PG","dailyConsumption":36,"cost":18.5}',
        "created_at": timestamp, "updated_at": timestamp,
    })
    pg_session.execute(statement, {
        "id": f"legacy-secret-{prefix}", "tenant": tenant, "resource_type": "material", "name": "敏感",
        "payload": '{"materialId":"MAT-SECRET","token":"reject-me"}',
        "created_at": timestamp, "updated_at": timestamp,
    })
    pg_session.flush()

    revision_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260718_0005_phase5b_c2_import_execution.py"
    frozen_backfill = runpy.run_path(str(revision_path))["_frozen_backfill_data_records"]
    frozen_backfill(pg_session.connection())
    pg_session.flush()

    material = pg_session.scalar(
        select(Material).where(Material.tenant_id == tenant, Material.material_id == "MAT-PG")
    )
    assert material is not None and material.material_name == "PG芯片"
    assert material.daily_consumption == 36.0 and material.unit_cost == 18.5
    assert pg_session.execute(
        text("SELECT source_record_id FROM import_rejections WHERE tenant_id=:tenant"), {"tenant": tenant}
    ).scalar_one() == f"legacy-secret-{prefix}"
