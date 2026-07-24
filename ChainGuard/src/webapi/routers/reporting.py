from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session


from ..auth import AuthContext, require_permission
from ..database import get_db
from ..reports import DEFAULT_MONTHS as REPORT_DEFAULT_MONTHS, executive_report as build_executive_report, operation_report as build_operation_report, response_report as build_response_report


router = APIRouter(tags=["imports-settings"])

@router.get("/reports/executive")
def executive_report(
    ctx: Annotated[AuthContext, Depends(require_permission("report:executive"))],
    db: Annotated[Session, Depends(get_db)],
    months: int = Query(REPORT_DEFAULT_MONTHS, ge=1, le=36),
):
    return build_executive_report(db, ctx.tenant_id, months)


@router.get("/reports/operation")
def operation_report(
    ctx: Annotated[AuthContext, Depends(require_permission("report:operation"))],
    db: Annotated[Session, Depends(get_db)],
    months: int = Query(REPORT_DEFAULT_MONTHS, ge=1, le=36),
):
    return build_operation_report(db, ctx.tenant_id, months)


@router.get("/reports/response")
def response_report(
    ctx: Annotated[AuthContext, Depends(require_permission("report:view"))],
    db: Annotated[Session, Depends(get_db)],
    months: int = Query(REPORT_DEFAULT_MONTHS, ge=1, le=36),
):
    return build_response_report(db, ctx.tenant_id, months)
