from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_current_user, require_permission
from ..audit_chain import verify_audit_chain
from ..database import get_db
from ..errors import ApiError
from ..jobs import enqueue_decision_job
from ..context_builder import TenantContextBuilder
from ..models import Approval, AuditLog, DecisionAudit, DecisionDetail, ExperienceCard, ImportJob, Incident, InventoryEntity, Job, NotificationMessage, Proposal, Risk, Task, User
from ...automation_stats import summarize_automation
from ...audit import RISK_APPROVAL_THRESHOLD
from ..experience import mark_incident_experience_completed, mark_incident_experience_confirmed
from ..decision_detail import mask_for_requester, render_pdf
from ..impact_scope import incident_impact_scope, risk_impact_scope
from ..node_health import my_nodes as build_my_nodes, node_health_overview
from ..notifications import ensure_rules, notify_event
from ..data_scope import apply_scope
from ..repository import add_audit, get_tenant_record, list_tenant_records, serialize
from ..risk_explanation import explain_risk
from ..risk_recompute import recompute_inventory_risks
from ..schemas import IncidentCreate, PatchRequest
from ..tenant_time import as_utc, local_month_key, localize_iso, localize_record_times, start_of_day, start_of_week, tenant_zone, utc_now_iso
from ..versioning import V1_TOP_RISKS_DEPRECATION


router = APIRouter(tags=["business"])
INCIDENT_TRANSITIONS = {"pending": {"planning"}, "planning": {"deciding"}, "deciding": {"approving", "planning"}, "approving": {"executing", "planning"}, "executing": {"closed"}, "closed": set()}


def _create_execution_tasks(db: Session, approval: Approval, incident: Incident) -> None:
    """Create post-approval tasks exactly once, assigned to active tenant users."""
    if db.scalar(select(Task).where(Task.tenant_id == approval.tenant_id, Task.incident_id == incident.id)):
        return
    roles = [("buyer", "锁定替代供应商订单"), ("scm_lead", "安排关键物料加急运输"), ("sales", "通知受影响高等级客户"), ("warehouse", "调整安全库存与调拨"), ("planner", "调整生产排程")]
    due_at = (datetime.now(timezone.utc) + timedelta(days=1 if incident.level == "high" else 3)).isoformat()
    for role, title in roles:
        assignee = db.scalar(select(User).where(User.tenant_id == approval.tenant_id, User.role_code == role, User.status == "active").order_by(User.id))
        if assignee is not None:
            # 任务的行级归属跟着承接人走：本人负责（own）与本部门（dept）都据此判定
            db.add(Task(id=f"task-{uuid.uuid4().hex}", tenant_id=approval.tenant_id, title=title, source=incident.code, incident_id=incident.id, assignee=assignee.id, owner_id=assignee.id, dept_id=assignee.dept_id or None, role_code=role, status="pending", due_at=due_at, priority="高" if incident.level == "high" else "中", checklist=[]))
            ensure_rules(db, approval.tenant_id)
            notify_event(db, approval.tenant_id, "task_assigned", {"assignee_user_id": assignee.id, "title": f"任务已分派：{title}", "target": "/task/mine"})


def _finalize_approval(db: Session, approval: Approval, incident: Incident, *, timed_out: bool = False) -> None:
    approval.status = "approved"
    incident.status = "executing"
    _create_execution_tasks(db, approval, incident)
    mark_incident_experience_confirmed(db, approval.tenant_id, incident.id, approval.proposal_id)
    if timed_out:
        approval.history = [*approval.history, {"action": "countersign_timeout_release", "reason": "超时未会签自动放行", "time": datetime.now(timezone.utc).isoformat()}]
        ensure_rules(db, approval.tenant_id)
        notify_event(db, approval.tenant_id, "countersign_timeout_release", {"submitter": approval.submitter, "title": f"{approval.summary}已超时自动放行，请财务事后追认", "target": f"/decision/approval/{approval.id}"})


def _countersign_requested_at(approval: Approval) -> datetime | None:
    """Return the last boss-approval transition timestamp, not submission time."""
    for entry in reversed(approval.history):
        if entry.get("action") != "approve" or not entry.get("time"):
            continue
        try:
            value = datetime.fromisoformat(str(entry["time"]))
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def release_expired_countersigns(now: datetime | None = None) -> int:
    """First scheduler job: release high-risk approvals after the configured timeout."""
    from ..config import settings
    from ..database import SessionLocal
    now = now or datetime.now(timezone.utc)
    released = 0
    with SessionLocal() as db:
        pending = list(db.scalars(select(Approval).where(Approval.status == "pending_countersign").with_for_update(skip_locked=True)).all())
        for approval in pending:
            requested_at = _countersign_requested_at(approval)
            # Existing malformed legacy records must not be released merely because
            # they were submitted long ago; only a recorded transition starts SLA.
            if requested_at is None or now - requested_at < timedelta(hours=settings.countersign_timeout_hours):
                continue
            incident = db.get(Incident, approval.incident_id)
            if incident is None:
                continue
            _finalize_approval(db, approval, incident, timed_out=True)
            add_audit(db, AuthContext("system-scheduler", approval.tenant_id, "系统调度器", "system", ()), "超时未会签自动放行", "approval", approval.id, approval.summary, {"timeoutHours": settings.countersign_timeout_hours})
            released += 1
        if released:
            db.commit()
    return released


def release_overdue_tasks(now: datetime | None = None) -> int:
    """Scheduler scan: mark overdue pending tasks once and notify rule recipients."""
    from ..database import SessionLocal
    now = now or datetime.now(timezone.utc)
    overdue = 0
    with SessionLocal() as db:
        tasks = list(db.scalars(select(Task).where(Task.status == "pending").with_for_update(skip_locked=True)).all())
        for task in tasks:
            try:
                due_at = datetime.fromisoformat(str(task.due_at))
                due_at = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if due_at >= now:
                continue
            task.status = "overdue"
            ensure_rules(db, task.tenant_id)
            notify_event(db, task.tenant_id, "task_overdue", {"assignee_user_id": task.assignee, "title": f"任务已逾期：{task.title}", "target": "/task/overdue"})
            add_audit(db, AuthContext("system-scheduler", task.tenant_id, "系统调度器", "system", ()), "任务逾期", "task", task.id, task.title, {"dueAt": task.due_at})
            overdue += 1
        if overdue:
            db.commit()
    return overdue


def page(items: list[Any], current: int, page_size: int) -> dict:
    start = max(current - 1, 0) * page_size
    return {"data": [serialize(x) for x in items[start:start + page_size]], "total": len(items), "success": True, "current": current, "pageSize": page_size}


@router.get("/risks")
def risks(ctx: Annotated[AuthContext, Depends(require_permission("risk:view"))], db: Annotated[Session, Depends(get_db)], current: int = 1, page_size: int = Query(20, alias="pageSize"), level: str | None = None, status_: str | None = Query(None, alias="status"), type_: str | None = Query(None, alias="type")):
    items = list_tenant_records(db, Risk, ctx.tenant_id, ctx)
    items = [x for x in items if (not level or x.level == level) and (not status_ or x.status == status_) and (not type_ or x.type == type_)]
    return page(items, current, page_size)


@router.post("/risks/recompute")
def recompute_risks(request: Request, ctx: Annotated[AuthContext, Depends(require_permission("risk:manage"))], db: Annotated[Session, Depends(get_db)]):
    """A03：按当前租户实体重算库存风险。同步单次，不进调度器、不发通知。"""
    outcome = recompute_inventory_risks(db, ctx.tenant_id, commit=False).to_dict()
    add_audit(db, ctx, "重算风险", "risk", "-", "库存风险重算", outcome, request.client.host if request.client else "")
    db.commit()
    return outcome


@router.get("/risks/matrix")
def risk_matrix(ctx: Annotated[AuthContext, Depends(require_permission("risk:view"))], db: Annotated[Session, Depends(get_db)]):
    return [{"name": x.code, "value": [i + 2, round(x.score / 10), x.score], "level": x.level} for i, x in enumerate(list_tenant_records(db, Risk, ctx.tenant_id, ctx))]


@router.get("/risks/{item_id}")
def risk_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("risk:view"))], db: Annotated[Session, Depends(get_db)]):
    return serialize(get_tenant_record(db, Risk, item_id, ctx.tenant_id, ctx))


@router.get("/risks/{item_id}/explanation")
def risk_explanation(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("risk:view"))], db: Annotated[Session, Depends(get_db)]):
    """A03：这条风险为什么是现在这个等级、由哪些当前租户数据触发、证据在哪。

    跨租户请求走 get_tenant_record 的 404 路径，不泄露存在性；出口统一过既有字段脱敏。
    """
    return explain_risk(db, ctx.tenant_id, get_tenant_record(db, Risk, item_id, ctx.tenant_id, ctx), ctx.permissions)


@router.get("/risks/{item_id}/impact-scope")
def risk_impact(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("risk:view"))], db: Annotated[Session, Depends(get_db)]):
    """A04：这条风险波及了哪些真实业务对象、经由什么关系（两跳，沿 C2 真实外键）。

    与解释端点同权限码、同租户隔离路径、同脱敏出口；不新增权限码。
    """
    return risk_impact_scope(db, ctx.tenant_id, get_tenant_record(db, Risk, item_id, ctx.tenant_id, ctx), ctx.permissions)


@router.patch("/risks/{item_id}/status")
def patch_risk(item_id: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("risk:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Risk, item_id, ctx.tenant_id, ctx)
    if body.status == "ignored" and not (body.reason or "").strip():
        raise ApiError(422, "CG-2101", "忽略风险必须填写理由")
    before = item.status
    item.status = body.status or item.status
    add_audit(db, ctx, "更新风险", "risk", item.id, item.code, {"before": before, "after": item.status, "reason": body.reason}, request.client.host if request.client else "")
    db.commit()
    return serialize(item)


@router.get("/incidents")
def incidents(ctx: Annotated[AuthContext, Depends(require_permission("incident:view"))], db: Annotated[Session, Depends(get_db)], current: int = 1, page_size: int = Query(20, alias="pageSize")):
    return page(list_tenant_records(db, Incident, ctx.tenant_id, ctx), current, page_size)


@router.post("/incidents", status_code=201)
def create_incident(body: IncidentCreate, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("risk:event:create"))], db: Annotated[Session, Depends(get_db)]):
    # 建事件的来源风险必须也在本人数据范围内，否则等于借建事件读取越权风险的属性。
    risks = list(db.scalars(apply_scope(
        db, ctx, Risk,
        select(Risk).where(Risk.tenant_id == ctx.tenant_id, Risk.id.in_(body.risk_ids)),
    )).all())
    if len(risks) != len(set(body.risk_ids)):
        raise ApiError(404, "CG-2001", "部分风险不存在")
    item_id = f"inc-{uuid.uuid4().hex}"
    level = "high" if any(x.level == "high" for x in risks) else (risks[0].level if risks else "medium")
    # owner_id / dept_id 必须落值：留空的记录在 dept/own 范围下对所有人不可见，
    # 创建者自己都看不到自己刚建的事件。
    item = Incident(id=item_id, tenant_id=ctx.tenant_id, code=f"INC-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}", title=body.title or f"{risks[0].object_name if risks else '手工'}风险应急事件", type=body.type, level=level, status="pending", owner=ctx.name, owner_id=ctx.user_id, dept_id=ctx.dept_id or None, source_risk_ids=body.risk_ids, loss=body.loss, cost=body.cost)
    db.add(item)
    for risk in risks:
        risk.status, risk.incident_id = "incident_created", item_id
    if level == "high":
        ensure_rules(db, ctx.tenant_id)
        notify_event(db, ctx.tenant_id, "risk_high", {"trigger_user_id": ctx.user_id, "title": f"高风险事件：{item.title}", "target": f"/incident/{item.id}"})
    add_audit(db, ctx, "创建事件", "incident", item.id, item.title, {"riskIds": body.risk_ids}, request.client.host if request.client else "")
    db.commit()
    return serialize(item)


@router.get("/incidents/{item_id}")
def incident_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("incident:view"))], db: Annotated[Session, Depends(get_db)]):
    return serialize(get_tenant_record(db, Incident, item_id, ctx.tenant_id, ctx))


@router.patch("/incidents/{item_id}")
def update_incident(item_id: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("incident:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Incident, item_id, ctx.tenant_id, ctx)
    if body.status and body.status not in INCIDENT_TRANSITIONS.get(item.status, set()):
        raise ApiError(409, "CG-2201", f"事件不能从{item.status}流转到{body.status}")
    before = item.status
    if body.status: item.status = body.status
    if body.note:
        item.notes = [*item.notes, {"text": body.note, "userId": ctx.user_id, "time": utc_now_iso()}]
    add_audit(db, ctx, "更新事件", "incident", item.id, item.title, {"before": before, "after": item.status, "note": body.note}, request.client.host if request.client else "")
    db.commit()
    return serialize(item)


@router.delete("/incidents/{item_id}", status_code=204)
def delete_incident(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("incident:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Incident, item_id, ctx.tenant_id, ctx)
    if item.status != "pending": raise ApiError(409, "CG-2202", "仅待处理事件可以删除")
    db.delete(item); db.commit()


@router.get("/incidents/{item_id}/impact")
def impact(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("incident:view"))], db: Annotated[Session, Depends(get_db)]):
    """A04：事件影响范围完整版。

    路径与权限码保持不变，实现就地替换为 C2 实体图谱遍历。原先的实现是把风险 details
    里的任意字符串当关键词，去 DataRecord 的文本里找子串——那是**猜测关系**：既漏掉实体表
    上的真实外键，又会把所有含"上海"的行都算成受影响。按 A04 规格第 3 条，它不得保留。
    """
    return incident_impact_scope(db, ctx.tenant_id, get_tenant_record(db, Incident, item_id, ctx.tenant_id, ctx), ctx.permissions)


@router.get("/incidents/{item_id}/timeline")
def timeline(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("incident:view"))], db: Annotated[Session, Depends(get_db)]):
    logs = list(db.scalars(select(AuditLog).where(AuditLog.tenant_id == ctx.tenant_id, AuditLog.target_id == item_id)).all())
    return localize_record_times([serialize(x) for x in logs], tenant_zone(db, ctx.tenant_id))


def _decision_detail_response(item_id: str, ctx: AuthContext, db: Session) -> dict:
    get_tenant_record(db, Incident, item_id, ctx.tenant_id, ctx)
    detail = db.scalar(select(DecisionDetail).where(DecisionDetail.tenant_id == ctx.tenant_id, DecisionDetail.incident_id == item_id).order_by(DecisionDetail.created_at.desc()))
    if detail is None: raise ApiError(404, "CG-2503", "尚未生成完整推演")
    payload = dict(detail.payload)
    approvals = list(db.scalars(select(Approval).where(Approval.tenant_id == ctx.tenant_id, Approval.incident_id == item_id)).all())
    payload["approval_chain"] = [serialize(item) for item in approvals]
    payload["decision_id"] = detail.id
    return mask_for_requester(payload, ctx.permissions)


@router.get("/incidents/{item_id}/decision-detail")
def decision_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))], db: Annotated[Session, Depends(get_db)]):
    return _decision_detail_response(item_id, ctx, db)


@router.get("/incidents/{item_id}/decision-readiness")
def decision_readiness(
    item_id: str,
    ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))],
    db: Annotated[Session, Depends(get_db)],
):
    # Preserve the product's non-enumerating cross-tenant 404 contract.
    get_tenant_record(db, Incident, item_id, ctx.tenant_id, ctx)
    return TenantContextBuilder(db, ctx.tenant_id).readiness(item_id)


@router.get("/incidents/{item_id}/decision-detail/export")
def export_decision_detail(item_id: str, format: str = "json", ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))] = None, db: Annotated[Session, Depends(get_db)] = None):
    payload = _decision_detail_response(item_id, ctx, db)
    if format == "json": return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="decision-{item_id}.json"'})
    if format == "pdf":
        # 运行环境缺 reportlab 时给出明确业务错误（503），不再落到 CG-5000
        try:
            content = render_pdf(payload)
        except RuntimeError as error:
            raise ApiError(503, "CG-2505", "PDF 导出依赖未安装：请在服务运行环境执行 pip install -r requirements.txt 后重启") from error
        return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="decision-{item_id}.pdf"'})
    raise ApiError(422, "CG-2504", "仅支持 JSON 或 PDF 导出")


@router.post("/incidents/{item_id}/proposals:generate", status_code=status.HTTP_202_ACCEPTED)
def generate(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("decision:generate"))], db: Annotated[Session, Depends(get_db)]):
    get_tenant_record(db, Incident, item_id, ctx.tenant_id, ctx)
    job = enqueue_decision_job(db, ctx, item_id)
    return {"jobId": job.id, "status": job.status}


@router.get("/jobs/{item_id}")
def job_status(item_id: str, ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    return serialize(get_tenant_record(db, Job, item_id, ctx.tenant_id))


@router.get("/proposals")
def proposals(ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))], db: Annotated[Session, Depends(get_db)], incident_id: str | None = Query(None, alias="incidentId")):
    items = list_tenant_records(db, Proposal, ctx.tenant_id, ctx)
    # 归档方案仅供审批详情按 id 追溯，不进入方案列表
    items = [x for x in items if not x.archived]
    if incident_id: items = [x for x in items if x.incident_id == incident_id]
    history = {"matched": False, "count": 0, "conclusions": [], "sources": []}
    if incident_id:
        detail = db.scalar(select(DecisionDetail).where(
            DecisionDetail.tenant_id == ctx.tenant_id,
            DecisionDetail.incident_id == incident_id,
        ).order_by(DecisionDetail.created_at.desc()))
        matched = list(((detail.payload.get("experience_references") or {}).get("references") or [])) if detail else []
        history = {
            "matched": bool(matched), "count": len(matched),
            "conclusions": [str(item.get("recommended_pattern") or "") for item in matched if item.get("recommended_pattern")],
            "sources": [str(item.get("case_id") or "") for item in matched if item.get("case_id")],
        }
    return {"data": [{**serialize(x), "historyExperience": history} for x in items], "total": len(items), "success": True}


@router.get("/experiences")
def experiences(ctx: Annotated[AuthContext, Depends(require_permission("case:view"))], db: Annotated[Session, Depends(get_db)]):
    cards = list(db.scalars(select(ExperienceCard).where(
        ExperienceCard.tenant_id == ctx.tenant_id,
    ).order_by(ExperienceCard.created_at.desc())).all())
    data = []
    for card in cards:
        row = serialize(card)
        retrieval = (card.content or {}).get("retrievalCard") or card.content or {}
        row.update({
            "scenario": retrieval.get("scenario", ""),
            "recommendedPattern": retrieval.get("recommended_pattern", ""),
            "triggerConditions": retrieval.get("trigger_conditions", []),
            "source": {"jobId": card.source_job_id, "incidentId": card.source_incident_id, "proposalId": card.source_proposal_id},
        })
        data.append(row)
    return {"data": data, "total": len(data), "success": True}


@router.get("/proposals/{item_id}")
def proposal_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))], db: Annotated[Session, Depends(get_db)]):
    return serialize(get_tenant_record(db, Proposal, item_id, ctx.tenant_id, ctx))


@router.get("/proposals/{item_id}/explanation")
def proposal_explanation(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Proposal, item_id, ctx.tenant_id, ctx)
    return {"proposalId": item.id, **item.explanation, "evidence": item.explanation.get("evidence", ["安全库存阈值", "高等级客户交付约束"])}


@router.patch("/proposals/{item_id}")
def recalc_proposal(item_id: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("decision:modify"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Proposal, item_id, ctx.tenant_id, ctx)
    before = item.total_cost
    # 成本缺失（None）时无基数可推 4% 浮动；仅当调用方显式给出 totalCost 才写入，否则保持缺失
    override_cost = body.overrides.get("totalCost", before * 1.04 if before is not None else None)
    item.total_cost = round(float(override_cost), 2) if override_cost is not None else None
    item.modified = True
    add_audit(db, ctx, "重算方案", "proposal", item.id, item.name, {"before": before, "overrides": body.overrides}, request.client.host if request.client else "")
    db.commit(); return serialize(item)


@router.post("/proposals/{item_id}/draft")
def save_draft(item_id: str, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("decision:modify"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Proposal, item_id, ctx.tenant_id, ctx); item.draft = True
    add_audit(db, ctx, "保存草稿", "proposal", item.id, item.name, {}, request.client.host if request.client else "")
    db.commit(); return {"proposalId": item.id, "savedAt": localize_iso(utc_now_iso(), tenant_zone(db, ctx.tenant_id))}


@router.get("/incidents/{item_id}/draft")
def get_draft(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))], db: Annotated[Session, Depends(get_db)]):
    # 先按数据范围确认这个事件本人可见，越权事件直接 404，不透出其草稿
    get_tenant_record(db, Incident, item_id, ctx.tenant_id, ctx)
    item = db.scalar(select(Proposal).where(Proposal.tenant_id == ctx.tenant_id, Proposal.incident_id == item_id, Proposal.draft.is_(True)))
    return serialize(item) if item else None


@router.post("/proposals/{item_id}/submit")
def submit_approval(item_id: str, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("approval:submit"))], db: Annotated[Session, Depends(get_db)]):
    proposal = get_tenant_record(db, Proposal, item_id, ctx.tenant_id, ctx)
    incident = get_tenant_record(db, Incident, proposal.incident_id, ctx.tenant_id, ctx)
    if incident.status != "deciding": raise ApiError(409, "CG-2301", "事件当前不能提交审批")
    # 成本未知（None）不是 0——中风险成本未知时保守抄送财务，而不是当作 0 跳过会签口径
    cost_requires_finance = proposal.total_cost is None or proposal.total_cost > 50000
    approval = Approval(id=f"ap-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, proposal_id=proposal.id, incident_id=incident.id, status="submitted", risk_level=incident.level, summary=proposal.name, cost_impact=proposal.total_cost, submitter=ctx.name, cc_role_codes=["finance"] if incident.level == "high" or (incident.level == "medium" and cost_requires_finance) else [], history=[])
    db.add(approval); incident.status = "approving"
    ensure_rules(db, ctx.tenant_id)
    notify_event(db, ctx.tenant_id, "approval_submitted", {"submitter_user_id": ctx.user_id, "risk_level": approval.risk_level, "cost_impact": approval.cost_impact, "title": f"{proposal.name}待审批", "target": f"/decision/approval/{approval.id}"})
    if approval.cc_role_codes:
        notify_event(db, ctx.tenant_id, "countersign_requested", {"title": f"{proposal.name}待财务会签", "target": f"/decision/approval/{approval.id}"})
    add_audit(db, ctx, "提交审批", "approval", approval.id, proposal.name, {"incidentId": incident.id}, request.client.host if request.client else "")
    db.commit(); return serialize(approval)


@router.get("/approvals")
def approvals(ctx: Annotated[AuthContext, Depends(require_permission("approval:view"))], db: Annotated[Session, Depends(get_db)], tab: str = "pending"):
    items = list_tenant_records(db, Approval, ctx.tenant_id)
    done = {"approved", "rejected", "recalc_requested", "transferred", "withdrawn"}
    if tab == "done": items = [x for x in items if x.status in done]
    elif tab == "cc": items = [x for x in items if ctx.role_code in x.cc_role_codes]
    else: items = [x for x in items if x.status in {"submitted", "pending", "pending_countersign"}]
    return {"data": [serialize(x) for x in items], "total": len(items), "success": True}


@router.get("/approvals/{item_id}")
def approval_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("approval:view"))], db: Annotated[Session, Depends(get_db)]):
    approval = get_tenant_record(db, Approval, item_id, ctx.tenant_id)
    proposal = get_tenant_record(db, Proposal, approval.proposal_id, ctx.tenant_id, ctx)
    options = list(db.scalars(select(Proposal).where(Proposal.tenant_id == ctx.tenant_id, Proposal.incident_id == approval.incident_id, Proposal.archived.is_(False))).all())
    # 评审修复：审批页确认点清单依赖推演数据，随详情按请求者角色脱敏后一并返回（无推演的旧单为 None）
    detail_row = db.scalar(select(DecisionDetail).where(DecisionDetail.tenant_id == ctx.tenant_id, DecisionDetail.incident_id == approval.incident_id).order_by(DecisionDetail.created_at.desc()))
    decision_detail = mask_for_requester(detail_row.payload, ctx.permissions) if detail_row is not None else None
    return {"approval": serialize(approval), "proposal": serialize(proposal), "decisionDetail": decision_detail, "chain": ["供应链负责人提交", "老板/总经理终批", "财务会签后生效"] if approval.risk_level == "high" else ["供应链负责人审批"], "comparison": {"current": serialize(proposal), "baseline": serialize(options[-1]) if options else serialize(proposal), "alternative": serialize(options[1]) if len(options) > 1 else serialize(proposal)}}


def approval_action(item_id: str, action: str, body: PatchRequest, request: Request, ctx: AuthContext, db: Session):
    approval = get_tenant_record(db, Approval, item_id, ctx.tenant_id)
    incident = get_tenant_record(db, Incident, approval.incident_id, ctx.tenant_id, ctx)
    if action == "countersign" and "approval:countersign" not in ctx.permissions:
        raise ApiError(403, "CG-1003", "没有会签权限")
    if action == "submit" and "approval:submit_high" not in ctx.permissions:
        raise ApiError(403, "CG-1003", "没有高风险提交权限")
    if action in {"approve", "recalc", "transfer"} and f"approval:{approval.risk_level}" not in ctx.permissions:
        raise ApiError(403, "CG-1003", "没有该风险等级的审批权限")
    if action == "reject" and not (f"approval:{approval.risk_level}" in ctx.permissions or (approval.status == "pending_countersign" and "approval:countersign" in ctx.permissions)):
        raise ApiError(403, "CG-1003", "没有该风险等级的审批权限")
    if action == "withdraw" and approval.submitter != ctx.name:
        raise ApiError(403, "CG-1003", "仅提交人可以撤回审批")
    transfer_user = None
    if action == "transfer":
        if not (body.assignee or "").strip():
            raise ApiError(422, "CG-2403", "转办必须指定接收人")
        transfer_user = db.scalar(select(User).where(User.tenant_id == ctx.tenant_id, User.status == "active", or_(User.id == body.assignee, User.name == body.assignee)))
        if transfer_user is None:
            raise ApiError(422, "CG-2404", "转办接收人不是本租户有效用户")
    # 追认分支必须先于通用"审批单已处理"检查：追认只发生在超时放行后的 approved 状态
    if action in {"ratify_approve", "ratify_object"}:
        if ctx.role_code != "finance" or approval.status != "approved" or not any(item.get("action") == "countersign_timeout_release" for item in approval.history):
            raise ApiError(409, "CG-2401", "当前审批单不等待财务追认")
        if any(item.get("action") in {"ratify_approve", "ratify_object"} for item in approval.history):
            raise ApiError(409, "CG-2405", "该审批单已完成追认，不能重复追认")
        if action == "ratify_object" and not (body.reason or "").strip(): raise ApiError(422, "CG-2402", "追认异议必须填写理由")
        approval.history = [*approval.history, {"action": action, "userId": ctx.user_id, "reason": body.reason, "time": utc_now_iso()}]
        add_audit(db, ctx, "财务追认通过" if action == "ratify_approve" else "财务追认异议", "approval", approval.id, approval.summary, {"reason": body.reason}, request.client.host if request.client else "")
        ensure_rules(db, ctx.tenant_id)
        ratify_text = "财务追认通过" if action == "ratify_approve" else f"财务追认异议：{(body.reason or '').strip()}"
        notify_event(db, ctx.tenant_id, "countersign_ratified", {"submitter": approval.submitter, "title": f"{approval.summary}{ratify_text}", "target": f"/decision/approval/{approval.id}"})
        # 留痕不回滚：已生成的执行任务保持不变
        db.commit(); return {"ok": True, "id": item_id, "action": action, "approval": serialize(approval)}
    if approval.status not in {"submitted", "pending", "transferred", "pending_countersign"}: raise ApiError(409, "CG-2401", "审批单已处理")
    if action == "reject" and not (body.reason or "").strip(): raise ApiError(422, "CG-2402", "驳回必须填写理由")
    mapping = {"approve": "approved", "reject": "rejected", "recalc": "recalc_requested", "transfer": "transferred", "withdraw": "withdrawn", "submit": "pending"}
    if action == "countersign":
        if approval.status != "pending_countersign": raise ApiError(409, "CG-2401", "审批单当前不等待会签")
        approval.countersigned = True
        _finalize_approval(db, approval, incident)
    else: approval.status = mapping[action]
    if action == "approve":
        if approval.risk_level == "high": approval.status = "pending_countersign"
        else: _finalize_approval(db, approval, incident)
    elif action in {"reject", "recalc", "withdraw"}: incident.status = "planning"
    elif action == "transfer": approval.transferred_to = transfer_user.id
    # 带时区写入：会签超时 SLA 依赖该时间戳做跨时区正确的差值计算（无时区会被扫描器按 UTC 解读）
    approval.history = [*approval.history, {"action": action, "userId": ctx.user_id, "reason": body.reason, "time": utc_now_iso()}]
    if action == "countersign": notify_event(db, ctx.tenant_id, "countersign_completed", {"submitter": approval.submitter, "title": f"{approval.summary}财务会签完成", "target": f"/decision/approval/{approval.id}"})
    if action == "reject" and ctx.role_code == "finance": notify_event(db, ctx.tenant_id, "countersign_rejected", {"submitter": approval.submitter, "title": f"{approval.summary}财务拒签", "target": f"/decision/approval/{approval.id}"})
    add_audit(db, ctx, f"审批{action}", "approval", approval.id, approval.summary, {"reason": body.reason, "assignee": body.assignee}, request.client.host if request.client else "")
    db.commit(); return {"ok": True, "id": item_id, "action": action, "approval": serialize(approval)}


@router.post("/approvals/{item_id}/{action}")
def act_approval(item_id: str, action: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("approval:view"))], db: Annotated[Session, Depends(get_db)]):
    if action not in {"approve", "reject", "recalc", "transfer", "withdraw", "submit", "countersign", "ratify_approve", "ratify_object"}: raise ApiError(404, "CG-2001", "审批动作不存在")
    return approval_action(item_id, action, body, request, ctx, db)


def _can_manage_all_tasks(ctx: AuthContext) -> bool:
    """复用 task:manage 落实数据范围，不新增权限码。

    有 task:manage（或超级 *）才能看/管理整租户任务；否则只能触达
    分派给自己（assignee == 当前用户）的任务，落实 buyer 的 custom 数据范围。
    """
    return "*" in ctx.permissions or "task:manage" in ctx.permissions


@router.get("/tasks")
def tasks(ctx: Annotated[AuthContext, Depends(require_permission("task:view"))], db: Annotated[Session, Depends(get_db)], scope: str | None = None):
    items = list_tenant_records(db, Task, ctx.tenant_id, ctx)
    # 无 task:manage 的角色（buyer 等 custom 范围）只能看到分派给自己的任务，
    # 不再返回租户全部任务。
    if not _can_manage_all_tasks(ctx):
        items = [x for x in items if x.assignee == ctx.user_id]
    if scope == "overdue": items = [x for x in items if x.status == "overdue"]
    # 负责人展示姓名而非 u-buyer；前端逾期看板按姓名聚合
    names = {u.id: u.name for u in list_tenant_records(db, User, ctx.tenant_id)}
    data = []
    for x in items:
        row = serialize(x)
        row["assigneeName"] = names.get(x.assignee, x.assignee)
        data.append(row)
    return {"data": data, "total": len(data), "success": True}


@router.get("/tasks/{item_id}")
def task_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("task:view"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Task, item_id, ctx.tenant_id, ctx)
    # 无 task:manage 者不得越权查看他人任务详情，返回 404 避免存在性枚举
    if not _can_manage_all_tasks(ctx) and item.assignee != ctx.user_id:
        raise ApiError(404, "CG-2010", "任务不存在")
    return serialize(item)


@router.patch("/tasks/{item_id}")
def update_task(item_id: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("task:execute"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Task, item_id, ctx.tenant_id, ctx)
    # 越权闸门——无 task:manage 者只能更新自己名下的任务
    if not _can_manage_all_tasks(ctx) and item.assignee != ctx.user_id:
        raise ApiError(403, "CG-2011", "只能操作分派给本人的任务")
    if body.status:
        item.status = body.status
        if item.incident_id and body.status in {"completed", "done"}:
            mark_incident_experience_completed(db, ctx.tenant_id, item.incident_id)
    if body.assignee:
        assignee = db.scalar(select(User).where(User.tenant_id == ctx.tenant_id, User.status == "active", or_(User.id == body.assignee, User.name == body.assignee)))
        if assignee is None: raise ApiError(422, "CG-2404", "任务负责人不是本租户有效用户")
        item.assignee = assignee.id
    add_audit(db, ctx, "更新任务", "task", item.id, item.title, body.model_dump(exclude_none=True), request.client.host if request.client else "")
    db.commit(); return serialize(item)


@router.post("/tasks/{item_id}/urge")
def urge_task(item_id: str, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("task:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Task, item_id, ctx.tenant_id, ctx); ensure_rules(db, ctx.tenant_id); notify_event(db, ctx.tenant_id, "task_urged", {"assignee_user_id": item.assignee, "title": f"请处理任务：{item.title}", "target": "/task/mine"}); add_audit(db, ctx, "催办任务", "task", item.id, item.title, {}, request.client.host if request.client else ""); db.commit(); return {"ok": True, "message": "已发送站内信催办"}


@router.get("/audit-logs")
def audit_logs(ctx: Annotated[AuthContext, Depends(require_permission("audit:view"))], db: Annotated[Session, Depends(get_db)], current: int = 1, page_size: int = Query(20, alias="pageSize"), user_id: str | None = Query(None, alias="userId"), target_type: str | None = Query(None, alias="targetType"), action: str | None = None):
    items = list_tenant_records(db, AuditLog, ctx.tenant_id)
    items = [x for x in items if (not user_id or x.user_id == user_id) and (not target_type or x.target_type == target_type) and (not action or x.action == action)]
    items.sort(key=lambda item: item.created_at, reverse=True)
    result = page(items, current, page_size)
    result["data"] = localize_record_times(result["data"], tenant_zone(db, ctx.tenant_id))
    return result


@router.get("/audit-logs/verify")
def verify_audit_logs(ctx: Annotated[AuthContext, Depends(require_permission("audit:view"))], db: Annotated[Session, Depends(get_db)]):
    return verify_audit_chain(db, ctx.tenant_id).as_dict()


def build_dashboard_kpis(db: Session, ctx: AuthContext, *, now: datetime | None = None) -> dict[str, Any]:
    # KPI 由真实数据计算，且任务口径与 /tasks、逾期看板一致（无 task:manage 只算本人）。
    risks = list_tenant_records(db, Risk, ctx.tenant_id, ctx)
    approvals = list_tenant_records(db, Approval, ctx.tenant_id)
    incidents = list_tenant_records(db, Incident, ctx.tenant_id, ctx)
    all_tasks = list_tenant_records(db, Task, ctx.tenant_id, ctx)
    mine = all_tasks if _can_manage_all_tasks(ctx) else [t for t in all_tasks if t.assignee == ctx.user_id]
    # 管理员工作台的四个 KPI 此前只有前端写死的演示字面量（成员数 9、未完成初始化项 2、
    # 本周导入批次 3、失败任务 0），既不随租户变化也和 /onboarding/status 互相矛盾。
    # 统一在这里按真实数据算，前端不再保留任何兜底数值。
    from ..onboarding import DECISION_REQUIRED, entity_summary

    summary = entity_summary(db, ctx.tenant_id)
    real_counts = summary["realCounts"]
    zone = tenant_zone(db, ctx.tenant_id)
    current = as_utc(now) or datetime.now(timezone.utc)
    today_start = start_of_day(zone, current).astimezone(timezone.utc)
    week_start = start_of_week(zone, current).astimezone(timezone.utc)
    import_jobs = list_tenant_records(db, ImportJob, ctx.tenant_id)

    # 采购视角的"待到货延误"：预计到货晚于计划到货的库存行。此前是前端写死的 0。
    arrival_delays = len([
        row for row in list_tenant_records(db, InventoryEntity, ctx.tenant_id)
        if row.planned_arrival_at and row.estimated_arrival_at
        and as_utc(row.estimated_arrival_at) > as_utc(row.planned_arrival_at)
    ])

    # 金额口径直接复用经营看板（reports.executive_report）的定义，不另立一套：
    # 避免损失 = Σ incident.loss，应急成本 = Σ incident.cost，净收益 = 两者之差。
    # 无事件时为 None（前端显示"数据缺失"），绝不用 0 冒充。
    # 只发给有对应字段权限的角色——KPI 接口过去只返回计数，加金额后必须自己做字段级门控，
    # 否则等于绕开 SensitiveField 把成本/利润泄漏给无 field:cost:view 的角色。
    permissions = set(ctx.permissions)
    can_cost = bool(permissions & {"*", "field:cost:view"})
    can_profit = bool(permissions & {"*", "field:profit:view"})
    avoided_loss = sum(float(i.loss or 0) for i in incidents) if incidents else None
    emergency_cost = sum(float(i.cost or 0) for i in incidents) if incidents else None
    net_benefit = round(avoided_loss - emergency_cost, 2) if incidents else None

    # 工作台的两张趋势图此前是写死的数组（['2月'..'7月'] 配 [12,14,9,18,16,12.8]），
    # 与租户无关。这里按真实事件/审批按月聚合；没有数据就返回空数组，前端画空态。
    cost_buckets: dict[str, dict[str, float]] = {}
    for item in incidents:
        moment = as_utc(item.created_at)
        if moment is None:
            continue
        bucket = cost_buckets.setdefault(local_month_key(moment, zone), {"avoidedLoss": 0.0, "emergencyCost": 0.0})
        bucket["avoidedLoss"] += float(item.loss or 0)
        bucket["emergencyCost"] += float(item.cost or 0)
    monthly_series = [
        {"month": key, "avoidedLoss": round(value["avoidedLoss"], 2), "emergencyCost": round(value["emergencyCost"], 2)}
        for key, value in sorted(cost_buckets.items())
    ]

    response_buckets: dict[str, list[float]] = {}
    for item in approvals:
        moment = as_utc(item.created_at)
        if moment is None or item.status not in {"approved", "rejected"} or item.waiting_hours is None:
            continue
        response_buckets.setdefault(local_month_key(moment, zone), []).append(float(item.waiting_hours))
    response_series = [
        {"month": key, "avgResponseHours": round(sum(values) / len(values), 2)}
        for key, values in sorted(response_buckets.items()) if values
    ]

    return {
        "riskCount": len(risks),
        "todayRiskCount": len([r for r in risks if (moment := as_utc(r.created_at)) and moment >= today_start]),
        "highRiskCount": len([r for r in risks if r.level == "high"]),
        "pendingApprovals": len([a for a in approvals if a.status in {"pending", "submitted"}]),
        "countersign": len([a for a in approvals if a.status == "pending_countersign"]),
        "myTasks": len(mine),
        "overdueTasks": len([t for t in mine if t.status == "overdue"]),
        "incidentCount": len([i for i in incidents if i.status != "closed"]),
        "memberCount": len(list_tenant_records(db, User, ctx.tenant_id)),
        # 决策链路必需但本租户还没有真实数据的资料类型数；与 /onboarding/status 同源。
        "onboardingPending": len([name for name in DECISION_REQUIRED if not real_counts.get(name)]),
        "weeklyImports": len([j for j in import_jobs if (moment := as_utc(j.created_at)) and moment >= week_start]),
        "failedImports": len([j for j in import_jobs if j.status == "failed"]),
        "arrivalDelays": arrival_delays,
        "avoidedLoss": round(avoided_loss, 2) if can_cost and avoided_loss is not None else None,
        "emergencyCost": round(emergency_cost, 2) if can_cost and emergency_cost is not None else None,
        "netBenefit": net_benefit if can_profit else None,
        "monthlySeries": monthly_series if can_cost else [],
        "responseSeries": response_series,
        "timezone": zone.key,
    }


def build_dashboard_automation(db: Session, ctx: AuthContext) -> dict[str, Any]:
    """Return tenant-scoped human-in-the-loop outcomes from decision audit facts.

    ``DecisionAudit`` is written exactly once for each completed decision job and
    contains the orchestrator's ``audit_entry``.  Generic ``AuditLog`` rows only
    describe user actions, so they cannot establish whether a decision was
    automatically released or escalated to a human.
    """
    entries = [
        item.entry
        for item in list_tenant_records(db, DecisionAudit, ctx.tenant_id)
        if isinstance(item.entry, dict) and "human_approval_required" in item.entry
    ]
    summary = summarize_automation(entries)
    return {
        "totalDecisions": summary.total,
        "autoApproved": summary.auto_approved,
        "escalated": summary.escalated,
        "automationRate": summary.automation_rate,
        "escalationRate": summary.escalation_rate,
        "escalationReasons": summary.escalation_reasons,
        "escalationRules": [
            {
                "code": "inventory_risk_threshold",
                "description": f"库存风险指数大于 {RISK_APPROVAL_THRESHOLD:g}",
            },
            {
                "code": "debate_not_converged",
                "description": "多智能体辩论未收敛",
            },
            {
                "code": "no_feasible_solution",
                "description": "约束求解无可行方案",
            },
        ],
    }


@router.get("/dashboard/kpis")
def dashboard_kpis(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    return build_dashboard_kpis(db, ctx)


@router.get("/dashboard/automation")
def dashboard_automation(
    ctx: Annotated[AuthContext, Depends(require_permission("dashboard:view"))],
    db: Annotated[Session, Depends(get_db)],
):
    return build_dashboard_automation(db, ctx)


@router.get("/dashboard/node-health")
def dashboard_node_health(
    ctx: Annotated[AuthContext, Depends(require_permission("dashboard:view"))],
    db: Annotated[Session, Depends(get_db)],
    node_type: str | None = Query(None, alias="nodeType"),
    health: str | None = None,
    keyword: str | None = None,
    current: int = 1,
    page_size: int = Query(20, alias="pageSize"),
):
    """C02：管理者工作台的供应链节点健康概览。

    四类节点全部由本租户 C2 实体算出：物料走既有库存风险引擎，仓库/供应商/订单走实体行
    事实判据与物料节点传播。出口统一过既有字段脱敏；不新增权限码。
    """
    return node_health_overview(
        db, ctx.tenant_id, ctx.permissions,
        node_types=[node_type] if node_type else None,
        health=health, keyword=keyword, current=current, page_size=page_size,
    )


@router.get("/dashboard/my-nodes")
def dashboard_my_nodes(
    ctx: Annotated[AuthContext, Depends(require_permission("dashboard:view"))],
    db: Annotated[Session, Depends(get_db)],
    health: str | None = None,
    keyword: str | None = None,
    current: int = 1,
    page_size: int = Query(20, alias="pageSize"),
):
    """C03：一线角色的「我的节点」明细。

    节点类型范围由**既有**权限码派生（data:*:manage / risk:manage:*），与 can_view_data
    同族口径；没有对口类型的角色得到 CG-C031 说明而非空列表伪装。
    """
    return build_my_nodes(
        db, ctx.tenant_id, ctx.permissions,
        health=health, keyword=keyword, current=current, page_size=page_size,
    )


def top_risks_payload(ctx: AuthContext, db: Session) -> list[dict]:
    return [
        serialize(item)
        for item in sorted(
            list_tenant_records(db, Risk, ctx.tenant_id, ctx),
            key=lambda item: item.score,
            reverse=True,
        )[:10]
    ]


@router.get("/dashboard/top-risks", **V1_TOP_RISKS_DEPRECATION.openapi_kwargs())
def top_risks(
    ctx: Annotated[AuthContext, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return top_risks_payload(ctx, db)
@router.get("/dashboard/my-tasks")
def my_tasks(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): return [serialize(x) for x in list_tenant_records(db, Task, ctx.tenant_id, ctx) if x.role_code == ctx.role_code]
@router.get("/dashboard/pending-approvals")
def pending_approvals(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): return [serialize(x) for x in list_tenant_records(db, Approval, ctx.tenant_id) if x.status in {"pending", "submitted"}]
@router.get("/dashboard/audit")
def dashboard_audit(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): return localize_record_times([serialize(x) for x in list_tenant_records(db, AuditLog, ctx.tenant_id)[:6]], tenant_zone(db, ctx.tenant_id))


@router.get("/notifications")
def notifications(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    items = [x for x in list_tenant_records(db, NotificationMessage, ctx.tenant_id) if x.user_id in {None, ctx.user_id}]
    return {"data": [serialize(x) for x in items], "unread": len([x for x in items if not x.read])}


@router.post("/notifications/{item_id}/read")
def mark_read(item_id: str, ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, NotificationMessage, item_id, ctx.tenant_id)
    if item.user_id not in {None, ctx.user_id}:
        raise ApiError(404, "CG-2001", "通知不存在")
    item.read = True; db.commit(); return {"ok": True, "id": item_id}
