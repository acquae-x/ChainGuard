from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from sqlalchemy import select

from src.observability import log_event
from src.orchestrator import DecisionOrchestrator

from .auth import AuthContext
from .database import SessionLocal
from .models import ImportJob, Incident, Job, Proposal
from .proposal_mapper import map_decision_result
from .repository import add_audit


# 调度池与决策执行池必须分离：若外层作业和带超时的内层调用共用一个池，
# 4 个并发作业会占满全部 worker 并互相等待，形成线程池自死锁。
job_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chainguard-job")
decision_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chainguard-decision")


def enqueue_decision_job(db, ctx: AuthContext, incident_id: str) -> Job:
    existing = db.scalar(select(Job).where(Job.tenant_id == ctx.tenant_id, Job.kind == "decision", Job.resource_id == incident_id, Job.status.in_(["pending", "running"])))
    if existing:
        return existing
    job = Job(id=f"job-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, kind="decision", resource_id=incident_id, idempotency_key=f"decision:{incident_id}", status="pending", progress=0, result={})
    incident = db.get(Incident, incident_id)
    if incident.status == "pending": incident.status = "planning"
    db.add(job); db.commit()
    job_executor.submit(_run_decision_job, job.id, ctx)
    return job


def _run_decision_job(job_id: str, ctx: AuthContext) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job: return
        job.status, job.progress = "running", 10; db.commit()
    # 当前 MVP 的 Incident 尚未具备可直接喂给决策引擎的完整物料上下文，
    # 因此仍调用 run_demo；作业与事件只通过 tenant/id、状态及方案持久化关联。
    future = decision_executor.submit(DecisionOrchestrator().run_demo)
    try:
        result = future.result(timeout=60)
        mapped = map_decision_result(result, job.resource_id)
        with SessionLocal() as db:
            job = db.get(Job, job_id); incident = db.get(Incident, job.resource_id)
            existing = list(db.scalars(select(Proposal).where(Proposal.tenant_id == ctx.tenant_id, Proposal.incident_id == incident.id)).all())
            for item in existing: db.delete(item)
            ids = []
            for values in mapped:
                proposal = Proposal(id=f"prop-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, **values)
                db.add(proposal); ids.append(proposal.id)
            incident.status = "deciding"
            job.status, job.progress, job.result = "succeeded", 100, {"proposalIds": ids, "count": len(ids)}
            add_audit(db, ctx, "生成方案", "incident", incident.id, incident.title, {"proposalCount": len(ids)})
            db.commit()
    except TimeoutError:
        future.cancel(); _fail_job(job_id, "CG-2501", "决策生成超时")
    except Exception as error:
        log_event("decision_job_failed", job_id=job_id, exception=type(error).__name__, message=str(error))
        _fail_job(job_id, "CG-2502", "决策生成失败")


def _fail_job(job_id: str, code: str, message: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job:
            job.status, job.progress, job.error_code, job.result = "failed", 100, code, {"message": message}
            db.commit()


def enqueue_import_job(job_id: str, ctx: AuthContext) -> None:
    job_executor.submit(_run_import_job, job_id, ctx)


def _run_import_job(job_id: str, ctx: AuthContext) -> None:
    """复用流式导入与 intake review，避免把整份文件载入内存。"""
    from pathlib import Path
    from dataclasses import asdict
    from src.streaming_import import stream_import_csv
    from src.intake_review import review_batch
    try:
        with SessionLocal() as db:
            item = db.get(ImportJob, job_id); item.status = "running"; item.progress = 60; path = Path(item.options["path"]); db.commit()
        target = path.parent / "import.db"
        if item.options.get("enterpriseMode"):
            from src.enterprise_ingest import import_tenant_from_dir
            enterprise_result = import_tenant_from_dir(ctx.tenant_id, str(path.parent))
            result = asdict(enterprise_result)
        else:
            result = stream_import_csv(path, path.stem.lower(), target, overwrite=True)
        review = review_batch([{"signature": path.stem, "result": result}], {})
        with SessionLocal() as db:
            item = db.get(ImportJob, job_id); item.status = "succeeded"; item.progress = 100; item.result = {"batchId": item.id, "streaming": asdict(result) if hasattr(result, "__dataclass_fields__") else result, "review": asdict(review) if hasattr(review, "__dataclass_fields__") else str(review)}
            add_audit(db, ctx, "执行导入", "import", item.id, item.file_name, {"batchId": item.id}); db.commit()
    except Exception as error:
        log_event("import_job_failed", job_id=job_id, exception=type(error).__name__, message=str(error))
        with SessionLocal() as db:
            item = db.get(ImportJob, job_id)
            if item: item.status = "failed"; item.progress = 100; item.result = {"code": "CG-2602", "message": "导入失败"}; db.commit()
