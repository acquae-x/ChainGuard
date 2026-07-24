from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.webapi.audit_chain import verify_audit_chain
from src.webapi.auth import AuthContext
from src.webapi.database import Base
from src.webapi.models import AuditLog
from src.webapi.repository import add_audit
from src.webapi.routers.business import verify_audit_logs


ROOT = Path(__file__).resolve().parents[1]


def _ctx(tenant_id: str = "tenant-audit-chain") -> AuthContext:
    return AuthContext("user-audit-chain", tenant_id, "Audit tester", "auditor", ("audit:view",))


def _session() -> tuple[Session, object]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def _append_three(db: Session, ctx: AuthContext) -> list[AuditLog]:
    entries = [
        add_audit(db, ctx, "create", "incident", "incident-1", "Incident 1", {"status": "new"}),
        add_audit(db, ctx, "update", "incident", "incident-1", "Incident 1", {"status": "triaged"}),
        add_audit(db, ctx, "close", "incident", "incident-1", "Incident 1", {"status": "closed"}),
    ]
    db.commit()
    return entries


def test_audit_chain_validates_normal_chain_and_endpoint():
    db, engine = _session()
    try:
        ctx = _ctx()
        entries = _append_three(db, ctx)
        result = verify_audit_chain(db, ctx.tenant_id)
        assert result.valid
        assert result.checked_entries == 3
        assert all(len(entry.prev_hash) == 64 and len(entry.entry_hash) == 64 for entry in entries)
        assert verify_audit_logs(ctx, db) == {
            "tenantId": ctx.tenant_id,
            "valid": True,
            "checkedEntries": 3,
            "errors": [],
        }
    finally:
        db.close()
        engine.dispose()


def test_audit_chain_rejects_detail_tampering():
    db, engine = _session()
    try:
        ctx = _ctx()
        entries = _append_three(db, ctx)
        entries[1].detail = {"status": "forged"}
        db.commit()
        result = verify_audit_chain(db, ctx.tenant_id)
        assert not result.valid
        assert f"entry_hash_mismatch:{entries[1].id}" in result.errors
    finally:
        db.close()
        engine.dispose()


def test_audit_chain_rejects_deleted_row_including_tail():
    db, engine = _session()
    try:
        ctx = _ctx()
        entries = _append_three(db, ctx)
        db.delete(entries[-1])
        db.commit()
        result = verify_audit_chain(db, ctx.tenant_id)
        assert not result.valid
        assert "entry_count_mismatch" in result.errors
        assert "head_hash_mismatch" in result.errors
    finally:
        db.close()
        engine.dispose()


def _run_alembic(database: Path, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
        text=True, capture_output=True, check=True,
    )


def test_audit_hash_migration_upgrade_downgrade_upgrade(tmp_path: Path):
    database = tmp_path / "audit-hash-chain.db"
    _run_alembic(database, "upgrade", "20260723_0012")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO audit_logs (time, user_id, user_name, role_code, action, target_type, "
            "target_id, target_name, detail, ip, id, tenant_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-07-24T00:00:00+00:00", "legacy-user", "Legacy", "auditor", "legacy", "incident",
                "incident-legacy", "Legacy incident", '{\"source\":\"migration\"}', "127.0.0.1",
                "audit-legacy", "tenant-legacy", "2026-07-24 00:00:00", "2026-07-24 00:00:00",
            ),
        )
        connection.commit()

    _run_alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info('audit_logs')")}
        assert {"prev_hash", "entry_hash"} <= columns
        assert connection.execute(
            "SELECT entry_count, length(head_hash) FROM audit_chain_states WHERE tenant_id = 'tenant-legacy'"
        ).fetchone() == (1, 64)
        assert connection.execute(
            "SELECT length(prev_hash), length(entry_hash) FROM audit_logs WHERE id = 'audit-legacy'"
        ).fetchone() == (64, 64)

    _run_alembic(database, "downgrade", "20260723_0012")
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info('audit_logs')")}
        assert "prev_hash" not in columns and "entry_hash" not in columns
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'audit_chain_states'"
        ).fetchone() is None

    _run_alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT entry_count FROM audit_chain_states WHERE tenant_id = 'tenant-legacy'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260724_0013",)


POSTGRES_URL = os.getenv("CHAINGUARD_TEST_POSTGRES_URL")


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set CHAINGUARD_TEST_POSTGRES_URL to a disposable migrated PostgreSQL database",
)
def test_audit_chain_postgresql_round_trip():
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    db = Session(engine)
    try:
        ctx = _ctx(f"tenant-audit-chain-pg-{uuid.uuid4().hex}")
        entries = _append_three(db, ctx)
        assert verify_audit_chain(db, ctx.tenant_id).valid

        entries[1].detail = {"status": "forged"}
        db.commit()
        result = verify_audit_chain(db, ctx.tenant_id)
        assert not result.valid
        assert f"entry_hash_mismatch:{entries[1].id}" in result.errors
    finally:
        db.close()
        engine.dispose()
