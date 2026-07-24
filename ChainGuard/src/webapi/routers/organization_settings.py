from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session


from ..auth import AuthContext, require_permission
from ..database import get_db
from ..org_settings import approval_chain_view, data_scope_view, save_approval_chain, save_data_scope
from ..repository import add_audit


router = APIRouter(tags=["imports-settings"])

@router.get("/settings/approval-chain")
def get_approval_chain(
    ctx: Annotated[AuthContext, Depends(require_permission("settings:approval"))],
    db: Annotated[Session, Depends(get_db)],
):
    return approval_chain_view(db, ctx.tenant_id)


@router.put("/settings/approval-chain")
def put_approval_chain(
    body: dict[str, Any],
    ctx: Annotated[AuthContext, Depends(require_permission("settings:approval"))],
    db: Annotated[Session, Depends(get_db)],
):
    result = save_approval_chain(db, ctx.tenant_id, body, actor=ctx.user_id)
    add_audit(db, ctx, "更新审批流", "approval_chain", "approval_chain", "审批链配置", result)
    db.commit()
    return result


@router.get("/settings/data-scopes")
def get_data_scopes(
    ctx: Annotated[AuthContext, Depends(require_permission("role:manage"))],
    db: Annotated[Session, Depends(get_db)],
):
    return data_scope_view(db, ctx.tenant_id)


@router.put("/settings/data-scopes")
def put_data_scopes(
    body: dict[str, Any],
    ctx: Annotated[AuthContext, Depends(require_permission("role:manage"))],
    db: Annotated[Session, Depends(get_db)],
):
    result = save_data_scope(db, ctx.tenant_id, body, actor=ctx.user_id)
    add_audit(db, ctx, "更新数据范围", "data_scope", "data_scope", "角色数据范围", body)
    db.commit()
    return result
