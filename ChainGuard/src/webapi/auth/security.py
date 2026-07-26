from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..errors import ApiError
from ..jwt_tokens import bearer, decode_typed_token, encode_typed_token
from ..models import RefreshToken, RevokedToken, Role, User


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    tenant_id: str
    name: str
    role_code: str
    permissions: tuple[str, ...]
    # 行级数据范围所需。给默认值是为了不破坏既有的位置参数构造（测试里大量存在），
    # 默认 all = 不过滤，等价于本特性上线前的行为——遗漏填充不会意外收紧或放宽权限。
    dept_id: str = ""
    data_scope: str = "all"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        # 仅 SSO 的账号存的是非 bcrypt 占位串：密码登录必须失败，而不是 500
        return False


def _token(user: User, token_type: str, expires: timedelta) -> str:
    return encode_typed_token(
        {
            "sub": user.id,
            "tenantId": user.tenant_id,
            "role": user.role_code,
        },
        token_type=token_type,
        expires=expires,
    )


def create_tokens(user: User, *, include_refresh: bool = True) -> dict[str, object]:
    tokens: dict[str, object] = {
        "token": _token(user, "access", timedelta(minutes=settings.access_token_minutes)),
        "expiresIn": settings.access_token_minutes * 60,
    }
    if include_refresh:
        tokens["refreshToken"] = _token(user, "refresh", timedelta(days=settings.refresh_token_days))
    return tokens


def decode_token(token: str, expected_type: str = "access", db: Session | None = None) -> dict:
    payload = decode_typed_token(token, expected_type)
    try:
        if db is not None and payload.get("jti") and db.get(RevokedToken, payload["jti"]):
            raise ValueError("token revoked")
        return payload
    except Exception as error:
        raise ApiError(401, "CG-1002", "登录状态已失效，请重新登录") from error


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> AuthContext:
    if credentials is None:
        raise ApiError(401, "CG-1002", "请先登录")
    payload = decode_token(credentials.credentials, db=db)
    user = db.get(User, payload["sub"])
    if user is None or user.status != "active" or user.tenant_id != payload.get("tenantId"):
        raise ApiError(401, "CG-1002", "登录状态已失效，请重新登录")
    role = db.scalar(select(Role).where(Role.id == user.role_id, Role.tenant_id == user.tenant_id))
    if role is None:
        raise ApiError(403, "CG-1003", "账号未配置有效角色")
    return AuthContext(
        user.id, user.tenant_id, user.name, user.role_code, tuple(role.permissions),
        dept_id=user.dept_id or "", data_scope=user.data_scope or "all",
    )


def record_refresh_token(db: Session, user: User, refresh_token: str) -> None:
    payload = decode_token(refresh_token, "refresh")
    expires = datetime.fromtimestamp(payload["exp"], timezone.utc)
    db.merge(RefreshToken(jti=payload["jti"], user_id=user.id, tenant_id=user.tenant_id, expires_at=expires))


def revoke_refresh_tokens(db: Session, user: User, *, only_jti: str | None = None) -> int:
    """Persist every invalidated refresh jti; decode checks this blacklist."""
    query = select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.tenant_id == user.tenant_id)
    if only_jti:
        query = query.where(RefreshToken.jti == only_jti)
    tokens = list(db.scalars(query).all())
    for token in tokens:
        db.merge(RevokedToken(jti=token.jti, user_id=token.user_id, tenant_id=token.tenant_id, expires_at=token.expires_at))
        db.delete(token)
    return len(tokens)


def cleanup_expired_revocations(db: Session) -> int:
    now = datetime.now(timezone.utc)
    expired = list(db.scalars(select(RevokedToken).where(RevokedToken.expires_at < now)).all())
    for item in expired: db.delete(item)
    return len(expired)


def require_permission(code: str):
    def dependency(ctx: Annotated[AuthContext, Depends(get_current_user)]) -> AuthContext:
        implied = {
            "risk:manage": lambda p: p.startswith("risk:manage"),
            "incident:manage": lambda p: p == "risk:event:create",
            "decision:view": lambda p: p.startswith("decision:view"),
            "decision:modify": lambda p: p.startswith("decision:modify"),
            "decision:generate": lambda p: p.startswith("decision:modify"),
            # 按结合审计复用口径，settings:manage 管理员可只读查看审批（列表/详情）；
            # 各审批动作在 approval_action 内有独立权限检查，管理员不会因此获得 approve/reject/countersign
            "approval:view": lambda p: p.startswith("approval:") or p == "settings:manage",
            "approval:submit": lambda p: p.startswith("approval:"),
            "approval:act": lambda p: p.startswith("approval:") and p != "approval:submit_high",
            "task:view": lambda p: p in {"task:view", "task:execute"},
            "data:import": lambda p: p.startswith("data:import"),
            "data:view": lambda p: p in {"data:view", "data:manage", "settings:manage"} or (p.startswith("data:") and p.endswith(":manage")),
            "report:view": lambda p: p.startswith("report:") or p == "settings:manage",
            "report:executive": lambda p: p == "settings:manage",
            "report:operation": lambda p: p == "settings:manage",
            # Calibrated parameters reuse the same gate as the existing
            # frontend canApprovalConfig capability; no new permission code.
            "settings:approval": lambda p: p in {"settings:manage", "settings:approval"},
        }
        allowed = code in ctx.permissions or "*" in ctx.permissions or any(implied.get(code, lambda _: False)(permission) for permission in ctx.permissions)
        if not allowed:
            raise ApiError(403, "CG-1003", "没有操作权限")
        return ctx
    return dependency


def can_view_data(ctx: AuthContext, resource_type: str) -> bool:
    """按资料类型收敛读取权限，避免仅导出权限被扩大为全量读取。"""
    permissions = set(ctx.permissions)
    if permissions & {"*", "data:view", "data:manage", "settings:manage"}:
        return True
    return resource_type in {"material", "supplier", "customer", "order", "inventory"} and f"data:{resource_type}:manage" in permissions
