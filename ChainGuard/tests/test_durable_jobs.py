"""Durable job queue contracts: another process may execute and failures retry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import subprocess
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from src.webapi.database import Base, SessionLocal, engine
from src.webapi import jobs
from src.webapi.jobs import DurableJobWorker
from src.webapi.models import ImportJob, Job, Tenant


def _tenant(db, tenant_id: str) -> None:
    db.add(Tenant(id=tenant_id, name="Durable queue test", industry="test", scale="small", status="active", plan="trial", trial_end_at="", demo_data_flag=False))


def test_another_process_claims_and_executes_a_persisted_import(tmp_path: Path) -> None:
    """The child process has no shared Python objects, only the same database row."""
    # Earlier HTTP tests can intentionally create the embedded ASGI-client
    # worker. Stop it before this proof so the child process is the only
    # eligible claimant, not merely a later observer of a completed job.
    with jobs._embedded_worker_lock:
        embedded = jobs._embedded_worker
        jobs._embedded_worker = None
    if embedded is not None:
        embedded.stop(grace_seconds=2)
    Base.metadata.create_all(engine)
    tenant_id = f"tenant-durable-{uuid.uuid4().hex}"
    job_id = f"import-durable-{uuid.uuid4().hex}"
    source = tmp_path / "materials.csv"
    source.write_text("material_id,material_name,standard_cost\nMAT-DURABLE,Durable material,12.5\n", encoding="utf-8")
    with SessionLocal() as db:
        _tenant(db, tenant_id)
        db.add(ImportJob(
            id=job_id, tenant_id=tenant_id, file_name=source.name, import_type="material",
            status="pending", progress=0, options={"path": str(source)}, result={}, requester_id="durable-test",
        ))
        db.commit()

    environment = os.environ.copy()
    completed = subprocess.run(
        [sys.executable, "-c", "from src.webapi.jobs import DurableJobWorker; raise SystemExit(0 if DurableJobWorker('child-process').run_once() else 3)"],
        cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 0, completed.stderr
    with SessionLocal() as db:
        item = db.get(ImportJob, job_id)
        assert item is not None and item.status == "succeeded"
        assert item.claimed_by == "child-process"
        assert item.attempts == 1


def test_retryable_failure_uses_backoff_then_stops_at_the_attempt_limit(monkeypatch) -> None:
    Base.metadata.create_all(engine)
    tenant_id = f"tenant-retry-{uuid.uuid4().hex}"
    job_id = f"job-retry-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        _tenant(db, tenant_id)
        db.add(Job(
            id=job_id, tenant_id=tenant_id, kind="decision", resource_id="missing-by-design",
            idempotency_key=job_id, status="pending", progress=0, result={}, requester_id="retry-test",
            max_attempts=2,
        ))
        db.commit()

    def transient_failure(*_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, OSError("temporary database outage"))

    monkeypatch.setattr("src.webapi.jobs._run_decision_job", transient_failure)
    worker = DurableJobWorker("retry-worker")
    assert worker.run_once() is True
    with SessionLocal() as db:
        item = db.get(Job, job_id)
        assert item.status == "pending" and item.attempts == 1
        assert item.available_at > datetime.now(timezone.utc)
        item.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    assert worker.run_once() is True
    with SessionLocal() as db:
        item = db.get(Job, job_id)
        assert item.status == "failed" and item.attempts == 2
        assert item.error_code == "CG-2502"
        assert db.scalar(select(Job).where(Job.id == job_id, Job.status == "pending")) is None


def test_non_retryable_database_error_fails_without_requeueing(monkeypatch) -> None:
    Base.metadata.create_all(engine)
    tenant_id = f"tenant-nonretry-{uuid.uuid4().hex}"
    job_id = f"job-nonretry-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        _tenant(db, tenant_id)
        db.add(Job(
            id=job_id, tenant_id=tenant_id, kind="decision", resource_id="invalid-by-design",
            idempotency_key=job_id, status="pending", progress=0, result={}, requester_id="nonretry-test",
            max_attempts=3,
        ))
        db.commit()

    def invalid_input(*_args, **_kwargs):
        raise IntegrityError("INSERT INTO jobs", {}, OSError("unique constraint"))

    monkeypatch.setattr("src.webapi.jobs._run_decision_job", invalid_input)
    assert DurableJobWorker("nonretry-worker").run_once() is True

    with SessionLocal() as db:
        item = db.get(Job, job_id)
        assert item is not None and item.status == "failed"
        assert item.attempts == 1
        assert item.available_at <= datetime.now(timezone.utc)
