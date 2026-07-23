from __future__ import annotations

import uuid
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from sqlalchemy import func, select

from src.observability import Metrics, log_event
from src.orchestrator import DecisionOrchestrator

from .auth import AuthContext
from .context_builder import ContextBuildError, TenantContextBuilder
from .database import SessionLocal
from .models import Approval, DecisionAudit, DecisionDetail, ImportJob, Incident, Job, Proposal
from .experience import attach_retrieval_result, persist_job_experience, retrieve_tenant_experience
from .notifications import ensure_rules, notify_event
from .onboarding import activate_tenant_after_business_data
from .proposal_mapper import map_decision_result
from .repository import add_audit


# 调度池与决策执行池必须分离：若外层作业和带超时的内层调用共用一个池，
# 4 个并发作业会占满全部 worker 并互相等待，形成线程池自死锁。
job_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chainguard-job")
decision_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chainguard-decision")


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
    job = Job(id=f"job-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, kind="decision", resource_id=incident_id, idempotency_key=f"decision:{incident_id}", status="pending", progress=0, result={})
    incident = db.scalar(select(Incident).where(Incident.id == incident_id, Incident.tenant_id == ctx.tenant_id))
    if incident is None:
        raise ContextBuildError("CG-2510", "事件不存在", status_code=404)
    if incident.status == "pending": incident.status = "planning"
    db.add(job); db.commit(); sync_jobs_pending_metric(db)
    job_executor.submit(_run_decision_job, job.id, ctx)
    return job


def _run_decision_job(job_id: str, ctx: AuthContext) -> None:
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == ctx.tenant_id, Job.kind == "decision"))
        if not job: return
        job.status, job.progress = "running", 10; db.commit(); sync_jobs_pending_metric(db)
    # decision_executor 的 worker 自己创建 Session；请求 Session 和 job worker Session
    # 都不会跨线程传递到真正执行决策的线程。
    future = decision_executor.submit(_execute_tenant_decision, job_id, ctx.tenant_id)
    try:
        result = future.result(timeout=60)
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
            # P1-10：已进入审批流的 Proposal 是审计追溯的一部分，必须永久保留；
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
    except TimeoutError:
        future.cancel(); _fail_job(job_id, "CG-2501", "决策生成超时", ctx)
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
        _fail_job(job_id, "CG-2502", "决策生成失败", ctx)


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
    job_executor.submit(_run_import_job, job_id, ctx)


def _run_import_job(job_id: str, ctx: AuthContext) -> None:
    """Stream normalized rows through the shared YAML adapter into entities."""
    from pathlib import Path
    from src.intake_review import review_batch
    from .entity_import import import_audit_file, import_enterprise_directory, import_entity_rows, iter_csv_rows, update_import_signature
    from .enterprise_import_catalog import IMPORT_TYPE_CATALOG
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
        with SessionLocal() as db:
            item = db.get(ImportJob, job_id)
            if item:
                item.status = "failed"; item.progress = 100; item.result = {"code": "CG-2602", "message": "导入失败"}
                update_import_signature(db, item.tenant_id, item.id, "failed")
                ensure_rules(db, ctx.tenant_id)
                notify_event(db, ctx.tenant_id, "import_failed", {"trigger_user_id": ctx.user_id, "title": f"{item.file_name}导入失败", "target": "/data/import"})
                db.commit()
