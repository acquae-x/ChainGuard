from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session


from ..auth import AuthContext, get_current_user, require_permission
from ..database import get_db
from ..errors import ApiError
from ..models import Department, Tenant
from ..calibration_governance import build_governance_snapshot, confirm_governance_snapshot
from ..repository import add_audit, serialize
from ..schemas import PatchRequest, TenantSettingsUpdate


router = APIRouter(tags=["imports-settings"])

@router.get("/settings/tenant")
def tenant(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): return serialize(db.get(Tenant, ctx.tenant_id))


@router.patch("/settings/tenant")
def update_tenant(
    body: TenantSettingsUpdate,
    ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))],
    db: Annotated[Session, Depends(get_db)],
):
    item = db.get(Tenant, ctx.tenant_id)
    if item is None:
        raise ApiError(404, "CG-2805", "租户不存在")
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        value = value.strip()
        if not value:
            raise ApiError(422, "CG-2806", f"{field} 不能为空")
        setattr(item, field, value)
    if changes:
        add_audit(db, ctx, "更新企业信息", "tenant", item.id, item.name, changes)
        db.commit()
        db.refresh(item)
    return serialize(item)
@router.get("/settings/departments")
def departments(
    ctx: Annotated[AuthContext, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """真实部门树（此前是端点里的 5 个硬编码字符串，没有层级也不可配置）。"""
    rows = list(db.scalars(select(Department).where(Department.tenant_id == ctx.tenant_id).order_by(Department.code)).all())
    return [
        {"id": row.id, "tenantId": row.tenant_id, "code": row.code, "name": row.name, "parentId": row.parent_id}
        for row in rows
    ]


@router.get("/settings/calibration-governance")
def calibration_governance(
    ctx: Annotated[AuthContext, Depends(require_permission("settings:approval"))],
    db: Annotated[Session, Depends(get_db)],
):
    """Read a tenant's existing-engine calibration proposal; no config writes."""
    snapshot = build_governance_snapshot(db, ctx.tenant_id)
    db.commit()  # persists only D3 notification messages/rules when drift exceeds limits
    return snapshot


@router.post("/settings/calibration-governance/confirm")
def confirm_calibration_governance(
    body: PatchRequest,
    ctx: Annotated[AuthContext, Depends(require_permission("settings:approval"))],
    db: Annotated[Session, Depends(get_db)],
):
    recommendation_id = str(body.values.get("recommendationId") or "")
    if not recommendation_id:
        raise ApiError(422, "CG-2901", "必须指定当前校准建议")
    try:
        result = confirm_governance_snapshot(db, ctx.tenant_id, ctx.user_id, recommendation_id)
    except ValueError as error:
        raise ApiError(409, "CG-2902", str(error)) from error
    add_audit(db, ctx, "确认校准建议", "calibration_governance", recommendation_id, "风险阈值与权重校准", result)
    db.commit()
    return {"ok": True, **result}
