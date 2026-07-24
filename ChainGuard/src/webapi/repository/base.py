from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import AuthContext
from ..data_scope import apply_scope, is_visible
from ..errors import ApiError
from ..models import AuditLog
from ..tenant_time import utc_now_iso


T = TypeVar("T")


def list_tenant_records(db: Session, model: type[T], tenant_id: str, ctx: AuthContext | None = None) -> list[T]:
    """租户内列表查询。

    传入 ctx 时额外施加行级数据范围（部门/本人）。不传表示系统内部调用
    （调度扫描、作业执行、通知派发等），这些路径本就不代表某个用户的视角。
    """
    stmt = select(model).where(model.tenant_id == tenant_id)
    if ctx is not None:
        stmt = apply_scope(db, ctx, model, stmt)
    return list(db.scalars(stmt).all())


def get_tenant_record(db: Session, model: type[T], item_id: str, tenant_id: str, ctx: AuthContext | None = None) -> T:
    """租户内单条读取。

    越出数据范围的记录一律按 404 处理，与跨租户访问口径一致——
    返回 403 会暴露"这条记录确实存在"，等于泄漏了本不该可见的信息。
    """
    item = db.scalar(select(model).where(model.id == item_id, model.tenant_id == tenant_id))
    if item is None:
        raise ApiError(404, "CG-2001", "资源不存在")
    if ctx is not None and not is_visible(db, ctx, item):
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
    # 存储用 UTC 规范时间；显示时按租户时区本地化。用 datetime.now().astimezone()
    # 会把服务器进程时区写进审计（生产容器 TZ 各异），同一事件在不同主机读出不同偏移。
    log = AuditLog(id=f"audit-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, time=utc_now_iso(), user_id=ctx.user_id, user_name=ctx.name, role_code=ctx.role_code, action=action, target_type=target_type, target_id=target_id, target_name=target_name, detail=detail, ip=ip)
    db.add(log)
    return log
