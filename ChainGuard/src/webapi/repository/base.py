from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import AuthContext
from ..errors import ApiError
from ..models import AuditLog


T = TypeVar("T")


def list_tenant_records(db: Session, model: type[T], tenant_id: str) -> list[T]:
    return list(db.scalars(select(model).where(model.tenant_id == tenant_id)).all())


def get_tenant_record(db: Session, model: type[T], item_id: str, tenant_id: str) -> T:
    item = db.scalar(select(model).where(model.id == item_id, model.tenant_id == tenant_id))
    if item is None:
        raise ApiError(404, "CG-2001", "资源不存在")
    return item


def camel(value: str) -> str:
    return re.sub(r"_([a-z])", lambda match: match.group(1).upper(), value)


def serialize(item: Any, *, exclude: set[str] | None = None, include: set[str] | None = None) -> dict[str, Any]:
    hidden = {"password_hash", "account", "created_at", "updated_at"} | (exclude or set())
    hidden.difference_update(include or set())
    result: dict[str, Any] = {}
    for column in item.__table__.columns:
        if column.name in hidden:
            continue
        value = getattr(item, column.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        result[camel(column.name)] = value
    if hasattr(item, "created_at"):
        result["createdAt"] = item.created_at.isoformat()
    if "details" in result and isinstance(result["details"], dict):
        result.update(result.pop("details"))
    return result


def add_audit(db: Session, ctx: AuthContext, action: str, target_type: str, target_id: str, target_name: str, detail: dict[str, Any], ip: str = "") -> AuditLog:
    log = AuditLog(id=f"audit-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, time=datetime.now().astimezone().isoformat(), user_id=ctx.user_id, user_name=ctx.name, role_code=ctx.role_code, action=action, target_type=target_type, target_id=target_id, target_name=target_name, detail=detail, ip=ip)
    db.add(log)
    return log
