from __future__ import annotations

import math
import os
import threading
import time
import urllib.error
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError, OperationalError

from src.observability import Metrics, log_event
from src.orchestrator import DecisionOrchestrator

from .auth import AuthContext
from .context_builder import ContextBuildError, TenantContextBuilder
from .database import SessionLocal
from .models import Approval, DecisionAudit, DecisionDetail, ImportJob, ImportSignature, ImportSourceRow, Incident, Job, Proposal, TenantConfig
from .config import settings
from .job_runtime import llm_timeout_seconds
from .experience import attach_retrieval_result, persist_job_experience, retrieve_tenant_experience
from .notifications import ensure_rules, notify_event
from .onboarding import activate_tenant_after_business_data
from .proposal_mapper import map_decision_result
from .repository import add_audit


# 调度池与决策执行池必须分离：若外层作业和带超时的内层调用共用一个池，
# 4 个并发作业会占满全部 worker 并互相等待，形成线程池自死锁。


@dataclass(frozen=True)
class ClaimedJob:
    kind: str
    id: str
    tenant_id: str
    requester_id: str
    timeout_seconds: float
    attempts: int
    max_attempts: int
    worker_id: str


class JobTimeoutError(TimeoutError):
    """A cooperative deadline reached after a synchronous job boundary."""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _tenant_timeout_override(db, tenant_id: str) -> float | None:
    configs = db.scalars(
        select(TenantConfig).where(TenantConfig.tenant_id == tenant_id).order_by(TenantConfig.version.desc())
    )
    for item in configs:
        payload = item.payload if isinstance(item.payload, dict) else {}
        runtime = payload.get("jobRuntime", payload)
        value = runtime.get("timeoutSeconds") if isinstance(runtime, dict) else None
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def job_timeout_seconds(db, *, kind: str, tenant_id: str, rows: int) -> float:
    """Tenant override or base plus deterministic data-volume cost, capped."""
    override = _tenant_timeout_override(db, tenant_id)
    base = override if override is not None else (
        settings.decision_job_timeout_seconds if kind == "decision" else settings.import_job_timeout_seconds
    )
    return min(settings.job_timeout_max_seconds, base + math.ceil(max(rows, 0) / 1000) * settings.job_timeout_per_1000_rows_seconds)


def _job_rows(db, *, kind: str, tenant_id: str, job_id: str | None = None) -> int:
    if kind == "import" and job_id:
        return int(db.scalar(select(ImportSignature.row_count).where(ImportSignature.import_job_id == job_id, ImportSignature.tenant_id == tenant_id)) or 0)
    return int(db.scalar(select(func.count()).select_from(ImportSourceRow).where(ImportSourceRow.tenant_id == tenant_id)) or 0)


def _claim_model(db, model, kind: str, worker_id: str, moment: datetime) -> ClaimedJob | None:
    """CAS claim: portable to SQLite/Postgres and safe across API processes."""
    candidates = db.execute(
        select(model.id, model.tenant_id, model.requester_id, model.timeout_seconds, model.attempts, model.max_attempts, model.updated_at)
        .where(model.status == "pending", model.available_at <= moment)
        .order_by(model.available_at, model.created_at)
        .limit(8)
    ).all()
    db.commit()
    for job_id, tenant_id, requester_id, timeout, attempts, max_attempts, observed_updated_at in candidates:
        lease = moment + timedelta(seconds=float(timeout) + settings.job_shutdown_grace_seconds)
        result = db.execute(
            update(model)
            .where(model.id == job_id, model.status == "pending", model.updated_at == observed_updated_at)
            .values(status="running", progress=10 if kind == "decision" else 60, attempts=int(attempts) + 1,
                    claimed_by=worker_id, lease_expires_at=lease, updated_at=moment),
            execution_options={"synchronize_session": False},
        )
        db.commit()
        if result.rowcount:
            return ClaimedJob(kind, job_id, tenant_id, requester_id, float(timeout), int(attempts) + 1, int(max_attempts), worker_id)
    return None


def claim_next_job(worker_id: str, *, now: datetime | None = None) -> ClaimedJob | None:
    """Find work submitted by any API process and atomically claim it."""
    moment = _as_utc(now) or datetime.now(timezone.utc)
    with SessionLocal() as db:
        for model in (Job, ImportJob):
            expired_ids = list(db.scalars(
                select(model.id).where(
                    model.status == "running", model.lease_expires_at.is_not(None), model.lease_expires_at < moment,
                )
            ))
            db.commit()
            for job_id in expired_ids:
                db.execute(
                    update(model)
                    .where(model.id == job_id, model.status == "running", model.lease_expires_at < moment)
                    .values(status="pending", progress=0, claimed_by=None, lease_expires_at=None, available_at=moment, updated_at=moment),
                    execution_options={"synchronize_session": False},
                )
                db.commit()
        return _claim_model(db, Job, "decision", worker_id, moment) or _claim_model(db, ImportJob, "import", worker_id, moment)


def _retryable(error: Exception) -> bool:
    # OperationalError is SQLAlchemy's transient database category.  Do not
    # retry every DBAPIError: IntegrityError and data/constraint errors also
    # inherit from it, but replaying them cannot make the input valid.
    return isinstance(error, (JobTimeoutError, OSError, urllib.error.URLError, OperationalError)) or (
        isinstance(error, DBAPIError) and error.connection_invalidated
    )


def _finish_failure(claim: ClaimedJob, error: Exception) -> None:
    retry = _retryable(error) and claim.attempts < claim.max_attempts
    code = "CG-2501" if isinstance(error, JobTimeoutError) else ("CG-2502" if claim.kind == "decision" else "CG-2602")
    message = "Decision generation timed out" if isinstance(error, JobTimeoutError) else ("Decision generation failed" if claim.kind == "decision" else "Import failed")
    model = Job if claim.kind == "decision" else ImportJob
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        item = db.get(model, claim.id)
        if item is None or item.status != "running" or item.claimed_by != claim.worker_id:
            return
        if retry:
            delay = min(settings.job_retry_backoff_max_seconds, settings.job_retry_backoff_seconds * (2 ** (claim.attempts - 1)))
            item.status, item.progress = "pending", 0
            item.available_at = now + timedelta(seconds=delay)
            item.claimed_by = None
            item.lease_expires_at = None
            item.result = {"code": code, "message": message, "retryAt": item.available_at.isoformat(), "attempt": claim.attempts}
            if claim.kind == "decision":
                item.error_code = code
            db.commit()
            log_event("job_retry_scheduled", job_id=claim.id, kind=claim.kind, attempt=claim.attempts, delay_seconds=delay, exception=type(error).__name__)
            return
    if claim.kind == "decision":
        _fail_job(claim.id, code, message, AuthContext(claim.requester_id, claim.tenant_id, "", "", ()))
    else:
        _fail_import_job(claim, code, message)


class DurableJobWorker:
    """One DB-polling execution loop per API process; it owns no local queue."""

    def __init__(self, worker_id: str | None = None) -> None:
        self.worker_id = worker_id or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name=f"chainguard-db-worker-{self.worker_id}", daemon=True)
        self._thread.start()

    def stop(self, grace_seconds: float | None = None) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(settings.job_shutdown_grace_seconds if grace_seconds is None else grace_seconds)

    def run_once(self) -> bool:
        claim = claim_next_job(self.worker_id)
        if claim is None:
            return False
        try:
            if claim.kind == "decision":
                _run_decision_job(claim.id, AuthContext(claim.requester_id, claim.tenant_id, "", "", ()), timeout_seconds=claim.timeout_seconds)
            else:
                _run_import_job(claim.id, AuthContext(claim.requester_id, claim.tenant_id, "", "", ()), timeout_seconds=claim.timeout_seconds)
        except Exception as error:
            _finish_failure(claim, error)
        return True

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                claimed = self.run_once()
            except OperationalError as error:
                log_event("job_worker_poll_failed", worker_id=self.worker_id, exception=type(error).__name__)
                claimed = False
            if not claimed:
                self._stopping.wait(settings.job_poll_seconds)


_embedded_worker: DurableJobWorker | None = None
_embedded_worker_lock = threading.Lock()


def ensure_durable_worker_started() -> None:
    """Cover ASGI clients that issue requests without entering app lifespan.

    This starts a polling worker, not a request-local task queue. A normal
    Uvicorn process starts its worker during FastAPI startup, before requests
    can arrive, so this path is primarily useful to embedded ASGI consumers.
    """
    global _embedded_worker
    with _embedded_worker_lock:
        if _embedded_worker is None:
            _embedded_worker = DurableJobWorker()
            _embedded_worker.start()


def sync_jobs_pending_metric(db) -> int:
    """Export pending/running job pressure for Prometheus after every transition."""
    count = int(db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(["pending", "running"]))) or 0)
    Metrics.set_jobs_pending(count)
    return count


def build_game_analysis(payload: dict) -> dict:
    """Persist game-theoretic evidence without changing the orchestrator internals."""
    from src.game_analysis import GameAnalyzer
    from src.game_model import PayoffModel

    context = payload.get("context") or {}
    model = PayoffModel(payoff_weights=(payload.get("risk_weights") or {}).get("payoff_weights"))
    payoffs = {
        "procurement": model.evaluate_procurement(context),
        "logistics": model.evaluate_logistics(context),
        "finance": model.evaluate_finance(context),
    }
    constraints = payload.get("constraint_analysis") or {}
    points = list(constraints.get("all_combos") or [])
    # Lightweight test/migration payloads may not carry the full solver output.
    if not {"individual_system_utility", "optimal_combo", "optimal_system_utility"}.issubset(constraints):
        return {"strategy_space_size": 27, "pareto": {"points": points, "frontier": []}, "status": "unavailable"}
    analysis = asdict(GameAnalyzer().analyze(payoffs, constraints, payload.get("debate_result") or {}))
    frontier, highest = [], float("-inf")
    for point in sorted((item for item in points if item.get("feasible")), key=lambda item: float(item.get("cost_multiplier", 0))):
        if float(point.get("system_utility", 0)) > highest:
            frontier.append(point)
            highest = float(point.get("system_utility", 0))
    analysis["pareto"] = {"points": points, "frontier": frontier}
    return analysis


def enqueue_decision_job(db, ctx: AuthContext, incident_id: str) -> Job:
    existing = db.scalar(select(Job).where(Job.tenant_id == ctx.tenant_id, Job.kind == "decision", Job.resource_id == incident_id, Job.status.in_(["pending", "running"])))
    if existing:
        return existing
    timeout = job_timeout_seconds(db, kind="decision", tenant_id=ctx.tenant_id, rows=_job_rows(db, kind="decision", tenant_id=ctx.tenant_id))
    job = Job(
        id=f"job-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, kind="decision", resource_id=incident_id,
        idempotency_key=f"decision:{incident_id}", status="pending", progress=0, result={},
        available_at=datetime.now(timezone.utc), timeout_seconds=timeout,
        max_attempts=settings.job_retry_max_attempts, requester_id=ctx.user_id,
    )
    incident = db.scalar(select(Incident).where(Incident.id == incident_id, Incident.tenant_id == ctx.tenant_id))
    if incident is None:
        raise ContextBuildError("CG-2510", "事件不存在", status_code=404)
    if incident.status == "pending": incident.status = "planning"
    db.add(job); db.commit(); sync_jobs_pending_metric(db)
    ensure_durable_worker_started()
    return job


def _run_decision_job(job_id: str, ctx: AuthContext, *, timeout_seconds: float | None = None) -> None:
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == ctx.tenant_id, Job.kind == "decision"))
        if not job: return
        if job.status == "pending":
            job.status, job.progress = "running", 10
            db.commit(); sync_jobs_pending_metric(db)
        budget = float(timeout_seconds if timeout_seconds is not None else job.timeout_seconds)
    # decision_executor 的 worker 自己创建 Session；请求 Session 和 job worker Session
    # 都不会跨线程传递到真正执行决策的线程。
    started = time.monotonic()
    token = llm_timeout_seconds.set(max(1.0, budget))
    try:
        result = _execute_tenant_decision(job_id, ctx.tenant_id)
        if time.monotonic() - started > budget:
            raise JobTimeoutError()
        mapped = map_decision_result(result, job.resource_id)
        detail_payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        from src.sensitivity import run_sensitivity
        current_stock = float((detail_payload.get("context") or {}).get("inventory", {}).get("current_stock") or 0)
        sensitivity_values = sorted({max(current_stock * ratio, 0.0) for ratio in (0.5, 1.0, 1.5)})
        detail_payload["sensitivity"] = run_sensitivity(
            "current_stock",
            sensitivity_values,
            baseline_context=detail_payload["context"],
            risk_weights=detail_payload["risk_weights"],
            thresholds=detail_payload["thresholds"],
        )
        detail_payload["game_analysis"] = build_game_analysis(detail_payload)
        with SessionLocal() as db:
            job = db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == ctx.tenant_id, Job.kind == "decision"))
            if job is None:
                return
            incident = db.scalar(select(Incident).where(Incident.id == job.resource_id, Incident.tenant_id == ctx.tenant_id))
            if incident is None:
                raise ContextBuildError("CG-2510", "事件不存在", status_code=404)
            existing = list(db.scalars(select(Proposal).where(Proposal.tenant_id == ctx.tenant_id, Proposal.incident_id == incident.id)).all())
            # 已进入审批流的 Proposal 是审计追溯的一部分，必须永久保留；
            # 重新推演只替换未被任何审批单引用的候选方案，被引用的归档（archived）不再进入方案列表。
            referenced = set(db.scalars(select(Approval.proposal_id).where(Approval.tenant_id == ctx.tenant_id, Approval.incident_id == incident.id)).all())
            for item in existing:
                if item.id in referenced:
                    item.archived = True
                else:
                    db.delete(item)
            ids = []
            for values in mapped:
                # 方案继承所属事件的行级归属，否则推演出来的方案在 dept/own 范围下没人看得见
                proposal = Proposal(
                    id=f"prop-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id,
                    owner_id=incident.owner_id, dept_id=incident.dept_id, **values,
                )
                db.add(proposal); ids.append(proposal.id)
            persist_job_experience(
                db, tenant_id=ctx.tenant_id, job=job, incident=incident,
                result=result, proposals=[item for item in db.new if isinstance(item, Proposal)],
            )
            db.add(DecisionDetail(id=f"decision-detail-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, incident_id=incident.id, job_id=job.id, payload=detail_payload))
            audit = detail_payload.get("audit_entry") or {}
            db.add(DecisionAudit(id=f"decision-audit-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, incident_id=incident.id, decision_id=str(audit.get("decision_id", job.id)), entry=audit))
            ensure_rules(db, ctx.tenant_id)
            notify_event(db, ctx.tenant_id, "decision_succeeded", {"trigger_user_id": ctx.user_id, "title": f"{incident.title}方案生成完成", "target": f"/decision/generate/{incident.id}?readonly=1"})
            incident.status = "deciding"
            job.status, job.progress, job.result = "succeeded", 100, {
                "proposalIds": ids,
                "count": len(ids),
                "dataQuality": detail_payload.get("context", {}).get("data_quality", {}),
                "configuration": detail_payload.get("context", {}).get("configuration", {}),
                "inventoryRiskIndex": detail_payload.get("inventory_risk", {}).get("inventory_risk_index"),
            }
            add_audit(db, ctx, "生成方案", "incident", incident.id, incident.title, {"proposalCount": len(ids)})
            db.commit(); sync_jobs_pending_metric(db)
    except JobTimeoutError:
        if timeout_seconds is not None:
            raise
        _fail_job(job_id, "CG-2501", "Decision generation timed out", ctx)
    except ContextBuildError as error:
        _fail_job(
            job_id,
            error.code,
            error.message,
            ctx,
            detail={"level": "blocked", "blocking": [{"code": error.code, "message": error.message}]},
        )
    except Exception as error:
        # Do not echo exception messages here: DB drivers may include connection URLs
        # and input validation errors may contain business-sensitive field values.
        log_event("decision_job_failed", job_id=job_id, exception=type(error).__name__)
        if timeout_seconds is not None:
            raise
        _fail_job(job_id, "CG-2502", "决策生成失败", ctx)
    finally:
        llm_timeout_seconds.reset(token)


def _execute_tenant_decision(job_id: str, tenant_id: str):
    """Decision-worker boundary: create and close a dedicated DB Session here."""
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id, Job.kind == "decision"))
        if job is None:
            raise ContextBuildError("CG-2510", "决策作业不存在", status_code=404)
        built = TenantContextBuilder(db, tenant_id).build(job.resource_id)
        retrieval = retrieve_tenant_experience(db, tenant_id, built.context)
    result = DecisionOrchestrator().run_tenant_scenario(
        built.context,
        risk_weights=built.risk_weights,
        thresholds=built.thresholds,
    )
    return attach_retrieval_result(result, retrieval)


def _fail_job(
    job_id: str,
    code: str,
    message: str,
    ctx: AuthContext | None = None,
    *,
    detail: dict | None = None,
) -> None:
    with SessionLocal() as db:
        query = select(Job).where(Job.id == job_id)
        if ctx is not None:
            query = query.where(Job.tenant_id == ctx.tenant_id)
        job = db.scalar(query)
        if job:
            job.status, job.progress, job.error_code, job.result = "failed", 100, code, {
                "message": message,
                **({"dataQuality": detail} if detail else {}),
            }
            ensure_rules(db, job.tenant_id)
            notify_event(db, job.tenant_id, "decision_failed", {"trigger_user_id": ctx.user_id if ctx else None, "title": "决策方案生成失败", "target": f"/decision/generate/{job.resource_id}"})
            db.commit(); sync_jobs_pending_metric(db)


def enqueue_import_job(job_id: str, ctx: AuthContext) -> None:
    # The caller has committed a durable row. A DB worker in any process will claim it.
    ensure_durable_worker_started()
    return None


def prepare_import_job(db, item: ImportJob, ctx: AuthContext) -> None:
    """Stamp the durable retry/timeout contract before the row becomes ready."""
    item.timeout_seconds = job_timeout_seconds(
        db, kind="import", tenant_id=ctx.tenant_id,
        rows=_job_rows(db, kind="import", tenant_id=ctx.tenant_id, job_id=item.id),
    )
    item.max_attempts = settings.job_retry_max_attempts
    item.requester_id = ctx.user_id
    item.available_at = datetime.now(timezone.utc)
    item.claimed_by = None
    item.lease_expires_at = None


def _run_import_job(job_id: str, ctx: AuthContext, *, timeout_seconds: float | None = None) -> None:
    """Stream normalized rows through the shared YAML adapter into entities."""
    from pathlib import Path
    from src.intake_review import review_batch
    from .entity_import import import_audit_file, import_enterprise_directory, import_entity_rows, iter_csv_rows, update_import_signature
    from .enterprise_import_catalog import IMPORT_TYPE_CATALOG
    started = time.monotonic()
    try:
        with SessionLocal() as db:
            item = db.get(ImportJob, job_id)
            item.status = "running"
            item.progress = 60
            path = Path(item.options["path"])
            update_import_signature(db, ctx.tenant_id, item.id, "running")
            db.commit()
            if item.options.get("enterpriseMode"):
                directory = Path(item.options.get("enterpriseDir") or path.parent)
                result = import_enterprise_directory(db, ctx.tenant_id, item.id, directory)
            else:
                definition = IMPORT_TYPE_CATALOG[item.import_type]
                field_mapping = item.options.get("fieldMapping")
                if definition["entity"]:
                    result = import_entity_rows(
                        db, ctx.tenant_id, item.id, iter_csv_rows(path), item.import_type,
                        field_mapping=field_mapping,
                    )
                else:
                    result = import_audit_file(db, ctx.tenant_id, item.id, path)
            review = review_batch([{"signature": item.options.get("signature", path.stem), "result": result}], {})
            if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
                raise JobTimeoutError()
            item.status = "succeeded"
            item.progress = 100
            item.result = {
                "batchId": item.id,
                "streaming": result,
                "total": int(result.get("sourceRows", 0)),
                "success": int(result.get("successRows", 0)),
                "failed": int(result.get("rejectedRows", 0)),
                "imported": int(result.get("successRows", 0)),
                "review": asdict(review),
            }
            # C3 only treats persisted C2 entities as completion evidence;
            # this keeps a newly registered tenant from staying "initializing"
            # after a successful real import.
            activate_tenant_after_business_data(db, ctx.tenant_id)
            update_import_signature(db, ctx.tenant_id, item.id, "succeeded", int(result.get("sourceRows", 0)))
            ensure_rules(db, ctx.tenant_id)
            notify_event(db, ctx.tenant_id, "import_succeeded", {"trigger_user_id": ctx.user_id, "title": f"{item.file_name}导入完成", "target": "/data/import"})
            add_audit(db, ctx, "执行导入", "import", item.id, item.file_name, {"batchId": item.id}); db.commit()
    except Exception as error:
        log_event("import_job_failed", job_id=job_id, exception=type(error).__name__, message=str(error))
        if timeout_seconds is not None:
            raise
        with SessionLocal() as db:
            item = db.get(ImportJob, job_id)
            if item:
                item.status = "failed"; item.progress = 100; item.result = {"code": "CG-2602", "message": "导入失败"}
                update_import_signature(db, item.tenant_id, item.id, "failed")
                ensure_rules(db, ctx.tenant_id)
                notify_event(db, ctx.tenant_id, "import_failed", {"trigger_user_id": ctx.user_id, "title": f"{item.file_name}导入失败", "target": "/data/import"})
                db.commit()


def _fail_import_job(claim: ClaimedJob, code: str, message: str) -> None:
    with SessionLocal() as db:
        item = db.get(ImportJob, claim.id)
        if item is None:
            return
        item.status, item.progress, item.result = "failed", 100, {"code": code, "message": message}
        item.claimed_by = None
        item.lease_expires_at = None
        from .entity_import import update_import_signature

        update_import_signature(db, item.tenant_id, item.id, "failed")
        ensure_rules(db, item.tenant_id)
        notify_event(db, item.tenant_id, "import_failed", {"trigger_user_id": claim.requester_id, "title": f"{item.file_name} import failed", "target": "/data/import"})
        db.commit()
