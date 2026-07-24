from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_current_user
from ..database import get_db
from .business import top_risks_payload


router = APIRouter(tags=["v2"])


@router.get("/dashboard/top-risks", summary="List the tenant's top risks")
def top_risks(
    ctx: Annotated[AuthContext, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """v2 successor for the deprecated v1 dashboard endpoint."""
    return top_risks_payload(ctx, db)
