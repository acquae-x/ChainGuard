from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_current_user, require_permission
from ..database import get_db
from ..errors import ApiError
from ..jobs import enqueue_decision_job
from ..models import Approval, AuditLog, Incident, Job, NotificationMessage, Proposal, Risk, Task, User
from ..repository import add_audit, get_tenant_record, list_tenant_records, serialize
from ..schemas import IncidentCreate, PatchRequest


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
            db.add(Task(id=f"task-{uuid.uuid4().hex}", tenant_id=approval.tenant_id, title=title, source=incident.code, incident_id=incident.id, assignee=assignee.id, role_code=role, status="pending", due_at=due_at, priority="高" if incident.level == "high" else "中", checklist=[]))


def _finalize_approval(db: Session, approval: Approval, incident: Incident, *, timed_out: bool = False) -> None:
    approval.status = "approved"
    incident.status = "executing"
    _create_execution_tasks(db, approval, incident)
    if timed_out:
        approval.history = [*approval.history, {"action": "countersign_timeout_release", "reason": "超时未会签自动放行", "time": datetime.now(timezone.utc).isoformat()}]
        db.add(NotificationMessage(id=f"notification-{uuid.uuid4().hex}", tenant_id=approval.tenant_id, kind="approval", title=f"{approval.summary}已超时自动放行，请财务事后追认", target=f"/decision/approval/{approval.id}"))


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


def page(items: list[Any], current: int, page_size: int) -> dict:
    start = max(current - 1, 0) * page_size
    return {"data": [serialize(x) for x in items[start:start + page_size]], "total": len(items), "success": True, "current": current, "pageSize": page_size}


@router.get("/risks")
def risks(ctx: Annotated[AuthContext, Depends(require_permission("risk:view"))], db: Annotated[Session, Depends(get_db)], current: int = 1, page_size: int = Query(20, alias="pageSize"), level: str | None = None, status_: str | None = Query(None, alias="status"), type_: str | None = Query(None, alias="type")):
    items = list_tenant_records(db, Risk, ctx.tenant_id)
    items = [x for x in items if (not level or x.level == level) and (not status_ or x.status == status_) and (not type_ or x.type == type_)]
    return page(items, current, page_size)


@router.get("/risks/matrix")
def risk_matrix(ctx: Annotated[AuthContext, Depends(require_permission("risk:view"))], db: Annotated[Session, Depends(get_db)]):
    return [{"name": x.code, "value": [i + 2, round(x.score / 10), x.score], "level": x.level} for i, x in enumerate(list_tenant_records(db, Risk, ctx.tenant_id))]


@router.get("/risks/{item_id}")
def risk_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("risk:view"))], db: Annotated[Session, Depends(get_db)]):
    return serialize(get_tenant_record(db, Risk, item_id, ctx.tenant_id))


@router.patch("/risks/{item_id}/status")
def patch_risk(item_id: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("risk:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Risk, item_id, ctx.tenant_id)
    if body.status == "ignored" and not (body.reason or "").strip():
        raise ApiError(422, "CG-2101", "忽略风险必须填写理由")
    before = item.status
    item.status = body.status or item.status
    add_audit(db, ctx, "更新风险", "risk", item.id, item.code, {"before": before, "after": item.status, "reason": body.reason}, request.client.host if request.client else "")
    db.commit()
    return serialize(item)


@router.get("/incidents")
def incidents(ctx: Annotated[AuthContext, Depends(require_permission("incident:view"))], db: Annotated[Session, Depends(get_db)], current: int = 1, page_size: int = Query(20, alias="pageSize")):
    return page(list_tenant_records(db, Incident, ctx.tenant_id), current, page_size)


@router.post("/incidents", status_code=201)
def create_incident(body: IncidentCreate, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("risk:event:create"))], db: Annotated[Session, Depends(get_db)]):
    risks = list(db.scalars(select(Risk).where(Risk.tenant_id == ctx.tenant_id, Risk.id.in_(body.risk_ids))).all())
    if len(risks) != len(set(body.risk_ids)):
        raise ApiError(404, "CG-2001", "部分风险不存在")
    item_id = f"inc-{uuid.uuid4().hex}"
    level = "high" if any(x.level == "high" for x in risks) else (risks[0].level if risks else "medium")
    item = Incident(id=item_id, tenant_id=ctx.tenant_id, code=f"INC-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}", title=body.title or f"{risks[0].object_name if risks else '手工'}风险应急事件", type=body.type, level=level, status="pending", owner=ctx.name, source_risk_ids=body.risk_ids, loss=body.loss, cost=body.cost)
    db.add(item)
    for risk in risks:
        risk.status, risk.incident_id = "incident_created", item_id
    add_audit(db, ctx, "创建事件", "incident", item.id, item.title, {"riskIds": body.risk_ids}, request.client.host if request.client else "")
    db.commit()
    return serialize(item)


@router.get("/incidents/{item_id}")
def incident_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("incident:view"))], db: Annotated[Session, Depends(get_db)]):
    return serialize(get_tenant_record(db, Incident, item_id, ctx.tenant_id))


@router.patch("/incidents/{item_id}")
def update_incident(item_id: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("incident:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Incident, item_id, ctx.tenant_id)
    if body.status and body.status not in INCIDENT_TRANSITIONS.get(item.status, set()):
        raise ApiError(409, "CG-2201", f"事件不能从{item.status}流转到{body.status}")
    before = item.status
    if body.status: item.status = body.status
    if body.note:
        item.notes = [*item.notes, {"text": body.note, "userId": ctx.user_id, "time": datetime.now().isoformat()}]
    add_audit(db, ctx, "更新事件", "incident", item.id, item.title, {"before": before, "after": item.status, "note": body.note}, request.client.host if request.client else "")
    db.commit()
    return serialize(item)


@router.delete("/incidents/{item_id}", status_code=204)
def delete_incident(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("incident:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Incident, item_id, ctx.tenant_id)
    if item.status != "pending": raise ApiError(409, "CG-2202", "仅待处理事件可以删除")
    db.delete(item); db.commit()


@router.get("/incidents/{item_id}/impact")
def impact(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("incident:view"))], db: Annotated[Session, Depends(get_db)]):
    from ..models import DataRecord
    incident = get_tenant_record(db, Incident, item_id, ctx.tenant_id)
    risks = list(db.scalars(select(Risk).where(Risk.tenant_id == ctx.tenant_id, Risk.id.in_(incident.source_risk_ids))).all())
    terms = {value.strip().lower() for risk in risks for value in [risk.object_name, *(risk.details.values() if isinstance(risk.details, dict) else [])] if isinstance(value, str) and len(value.strip()) >= 2}
    records = list_tenant_records(db, DataRecord, ctx.tenant_id)
    def matches(record: DataRecord) -> bool:
        text = " ".join([record.name, *map(str, record.payload.values())]).lower()
        return any(term in text for term in terms)
    materials = [{"id": item.id, "name": item.name, **item.payload} for item in records if item.resource_type == "material" and matches(item)]
    orders = [{"id": item.id, "orderNo": item.payload.get("orderNo", item.name), **item.payload} for item in records if item.resource_type == "order" and matches(item)]
    suppliers = [{"id": item.id, "name": item.name, **item.payload} for item in records if item.resource_type == "supplier" and matches(item)]
    inventory = [{"id": item.id, "material": item.payload.get("material", item.name), **item.payload} for item in records if item.resource_type == "inventory" and matches(item)]
    return {"id": item_id, "materials": materials, "orders": orders, "suppliers": suppliers, "inventory": inventory, "dataMissing": {"materials": not bool(materials), "orders": not bool(orders), "suppliers": not bool(suppliers), "inventory": not bool(inventory)}}


@router.get("/incidents/{item_id}/timeline")
def timeline(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("incident:view"))], db: Annotated[Session, Depends(get_db)]):
    logs = list(db.scalars(select(AuditLog).where(AuditLog.tenant_id == ctx.tenant_id, AuditLog.target_id == item_id)).all())
    return [serialize(x) for x in logs]


@router.post("/incidents/{item_id}/proposals:generate", status_code=status.HTTP_202_ACCEPTED)
def generate(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("decision:generate"))], db: Annotated[Session, Depends(get_db)]):
    get_tenant_record(db, Incident, item_id, ctx.tenant_id)
    job = enqueue_decision_job(db, ctx, item_id)
    return {"jobId": job.id, "status": job.status}


@router.get("/jobs/{item_id}")
def job_status(item_id: str, ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    return serialize(get_tenant_record(db, Job, item_id, ctx.tenant_id))


@router.get("/proposals")
def proposals(ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))], db: Annotated[Session, Depends(get_db)], incident_id: str | None = Query(None, alias="incidentId")):
    items = list_tenant_records(db, Proposal, ctx.tenant_id)
    if incident_id: items = [x for x in items if x.incident_id == incident_id]
    return {"data": [serialize(x) for x in items], "total": len(items), "success": True}


@router.get("/proposals/{item_id}")
def proposal_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))], db: Annotated[Session, Depends(get_db)]):
    return serialize(get_tenant_record(db, Proposal, item_id, ctx.tenant_id))


@router.get("/proposals/{item_id}/explanation")
def proposal_explanation(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Proposal, item_id, ctx.tenant_id)
    return {"proposalId": item.id, **item.explanation, "evidence": item.explanation.get("evidence", ["安全库存阈值", "高等级客户交付约束"])}


@router.patch("/proposals/{item_id}")
def recalc_proposal(item_id: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("decision:modify"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Proposal, item_id, ctx.tenant_id)
    before = item.total_cost
    item.total_cost = round(float(body.overrides.get("totalCost", before * 1.04)), 2)
    item.modified = True
    add_audit(db, ctx, "重算方案", "proposal", item.id, item.name, {"before": before, "overrides": body.overrides}, request.client.host if request.client else "")
    db.commit(); return serialize(item)


@router.post("/proposals/{item_id}/draft")
def save_draft(item_id: str, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("decision:modify"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Proposal, item_id, ctx.tenant_id); item.draft = True
    add_audit(db, ctx, "保存草稿", "proposal", item.id, item.name, {}, request.client.host if request.client else "")
    db.commit(); return {"proposalId": item.id, "savedAt": datetime.now().isoformat()}


@router.get("/incidents/{item_id}/draft")
def get_draft(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("decision:view"))], db: Annotated[Session, Depends(get_db)]):
    item = db.scalar(select(Proposal).where(Proposal.tenant_id == ctx.tenant_id, Proposal.incident_id == item_id, Proposal.draft.is_(True)))
    return serialize(item) if item else None


@router.post("/proposals/{item_id}/submit")
def submit_approval(item_id: str, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("approval:submit"))], db: Annotated[Session, Depends(get_db)]):
    proposal = get_tenant_record(db, Proposal, item_id, ctx.tenant_id)
    incident = get_tenant_record(db, Incident, proposal.incident_id, ctx.tenant_id)
    if incident.status != "deciding": raise ApiError(409, "CG-2301", "事件当前不能提交审批")
    approval = Approval(id=f"ap-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, proposal_id=proposal.id, incident_id=incident.id, status="submitted", risk_level=incident.level, summary=proposal.name, cost_impact=proposal.total_cost, submitter=ctx.name, cc_role_codes=["finance"] if incident.level == "high" or (incident.level == "medium" and proposal.total_cost > 50000) else [], history=[])
    db.add(approval); incident.status = "approving"
    if approval.cc_role_codes:
        db.add(NotificationMessage(id=f"notification-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, kind="approval", title=f"{proposal.name}待财务会签", target=f"/decision/approval/{approval.id}"))
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
    proposal = get_tenant_record(db, Proposal, approval.proposal_id, ctx.tenant_id)
    options = list(db.scalars(select(Proposal).where(Proposal.tenant_id == ctx.tenant_id, Proposal.incident_id == approval.incident_id)).all())
    return {"approval": serialize(approval), "proposal": serialize(proposal), "chain": ["供应链负责人提交", "老板/总经理终批", "财务会签后生效"] if approval.risk_level == "high" else ["供应链负责人审批"], "comparison": {"current": serialize(proposal), "baseline": serialize(options[-1]) if options else serialize(proposal), "alternative": serialize(options[1]) if len(options) > 1 else serialize(proposal)}}


def approval_action(item_id: str, action: str, body: PatchRequest, request: Request, ctx: AuthContext, db: Session):
    approval = get_tenant_record(db, Approval, item_id, ctx.tenant_id)
    incident = get_tenant_record(db, Incident, approval.incident_id, ctx.tenant_id)
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
    approval.history = [*approval.history, {"action": action, "userId": ctx.user_id, "reason": body.reason, "time": datetime.now().astimezone().isoformat()}]
    add_audit(db, ctx, f"审批{action}", "approval", approval.id, approval.summary, {"reason": body.reason, "assignee": body.assignee}, request.client.host if request.client else "")
    db.commit(); return {"ok": True, "id": item_id, "action": action, "approval": serialize(approval)}


@router.post("/approvals/{item_id}/{action}")
def act_approval(item_id: str, action: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("approval:view"))], db: Annotated[Session, Depends(get_db)]):
    if action not in {"approve", "reject", "recalc", "transfer", "withdraw", "submit", "countersign"}: raise ApiError(404, "CG-2001", "审批动作不存在")
    return approval_action(item_id, action, body, request, ctx, db)


@router.get("/tasks")
def tasks(ctx: Annotated[AuthContext, Depends(require_permission("task:view"))], db: Annotated[Session, Depends(get_db)], scope: str | None = None):
    items = list_tenant_records(db, Task, ctx.tenant_id)
    if scope == "overdue": items = [x for x in items if x.status == "overdue"]
    return {"data": [serialize(x) for x in items], "total": len(items), "success": True}


@router.get("/tasks/{item_id}")
def task_detail(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("task:view"))], db: Annotated[Session, Depends(get_db)]): return serialize(get_tenant_record(db, Task, item_id, ctx.tenant_id))


@router.patch("/tasks/{item_id}")
def update_task(item_id: str, body: PatchRequest, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("task:execute"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Task, item_id, ctx.tenant_id)
    if body.status: item.status = body.status
    if body.assignee:
        assignee = db.scalar(select(User).where(User.tenant_id == ctx.tenant_id, User.status == "active", or_(User.id == body.assignee, User.name == body.assignee)))
        if assignee is None: raise ApiError(422, "CG-2404", "任务负责人不是本租户有效用户")
        item.assignee = assignee.id
    add_audit(db, ctx, "更新任务", "task", item.id, item.title, body.model_dump(exclude_none=True), request.client.host if request.client else "")
    db.commit(); return serialize(item)


@router.post("/tasks/{item_id}/urge")
def urge_task(item_id: str, request: Request, ctx: Annotated[AuthContext, Depends(require_permission("task:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Task, item_id, ctx.tenant_id); add_audit(db, ctx, "催办任务", "task", item.id, item.title, {}, request.client.host if request.client else ""); db.commit(); return {"ok": True, "message": "已发送站内信催办"}


@router.get("/audit-logs")
def audit_logs(ctx: Annotated[AuthContext, Depends(require_permission("audit:view"))], db: Annotated[Session, Depends(get_db)], current: int = 1, page_size: int = Query(20, alias="pageSize"), user_id: str | None = Query(None, alias="userId"), target_type: str | None = Query(None, alias="targetType"), action: str | None = None):
    items = list_tenant_records(db, AuditLog, ctx.tenant_id)
    items = [x for x in items if (not user_id or x.user_id == user_id) and (not target_type or x.target_type == target_type) and (not action or x.action == action)]
    items.sort(key=lambda item: item.created_at, reverse=True)
    return page(items, current, page_size)


@router.get("/dashboard/kpis")
def dashboard_kpis(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    return {"riskCount": len(list_tenant_records(db, Risk, ctx.tenant_id)), "pendingApprovals": len([x for x in list_tenant_records(db, Approval, ctx.tenant_id) if x.status in {"pending", "submitted"}]), "myTasks": len(list_tenant_records(db, Task, ctx.tenant_id)), "incidentCount": len(list_tenant_records(db, Incident, ctx.tenant_id))}


@router.get("/dashboard/top-risks")
def top_risks(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): return [serialize(x) for x in sorted(list_tenant_records(db, Risk, ctx.tenant_id), key=lambda x: x.score, reverse=True)[:10]]
@router.get("/dashboard/my-tasks")
def my_tasks(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): return [serialize(x) for x in list_tenant_records(db, Task, ctx.tenant_id) if x.role_code == ctx.role_code]
@router.get("/dashboard/pending-approvals")
def pending_approvals(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): return [serialize(x) for x in list_tenant_records(db, Approval, ctx.tenant_id) if x.status in {"pending", "submitted"}]
@router.get("/dashboard/audit")
def dashboard_audit(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): return [serialize(x) for x in list_tenant_records(db, AuditLog, ctx.tenant_id)[:6]]


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
