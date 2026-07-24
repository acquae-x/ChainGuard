from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session


from .. import sso as sso_service
from ..auth import AuthContext, require_permission
from ..database import get_db


router = APIRouter(tags=["imports-settings"])

@router.get("/settings/sso")
def sso_config(ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    return sso_service.public_config(sso_service.get_config(db, ctx.tenant_id))


@router.put("/settings/sso")
def save_sso_config(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    return sso_service.save_config(db, ctx, body)
