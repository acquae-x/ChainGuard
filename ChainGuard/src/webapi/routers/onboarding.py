from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session


from ..auth import AuthContext, get_current_user, require_permission
from ..database import get_db
from ..errors import ApiError
from ..models import Tenant
from ..onboarding import inject_demo_dataset, onboarding_status, save_onboarding_progress
from ..repository import serialize
from ..schemas import PatchRequest


router = APIRouter(tags=["imports-settings"])

@router.get("/onboarding/templates")
def templates(): return [{"id": "electronics", "name": "电子制造", "desc": "芯片、PCB、关键物料齐套与替代供应商模板"}]


@router.get("/onboarding/status")
def onboarding_status_endpoint(
    ctx: Annotated[AuthContext, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """C3 status is always recomputed from this tenant's persisted C2 entities."""
    return onboarding_status(db, ctx.tenant_id)


@router.post("/onboarding/progress")
def save_progress(
    body: dict[str, Any],
    ctx: Annotated[AuthContext, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    status = save_onboarding_progress(db, ctx, body)
    db.commit()
    return {"ok": True, "status": status}


@router.post("/onboarding/demo-dataset", status_code=201)
def inject_onboarding_demo_dataset(
    body: PatchRequest,
    ctx: Annotated[AuthContext, Depends(require_permission("data:import"))],
    db: Annotated[Session, Depends(get_db)],
):
    # No implicit path: both UI and API callers must record an explicit second confirmation.
    if body.values.get("confirmed") is not True:
        raise ApiError(422, "CG-2701", "请确认后再注入演示数据集")
    try:
        result = inject_demo_dataset(db, ctx)
    except ValueError as error:
        raise ApiError(409, "CG-2702", str(error)) from error
    db.commit()
    return result


@router.post("/onboarding/templates/{template_id}/apply")
def apply_template(template_id: str, ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): item = db.get(Tenant, ctx.tenant_id); item.industry = template_id; db.commit(); return {"ok": True, "tenant": serialize(item)}
