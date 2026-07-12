from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..errors import ApiError
from ..models import Role, User


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    tenant_id: str
    name: str
    role_code: str
    permissions: tuple[str, ...]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def _token(user: User, token_type: str, expires: timedelta) -> str:
    now = datetime.now(timezone.utc)
    key = settings.jwt_rs256_private_key if settings.jwt_algorithm == "RS256" else settings.jwt_secret
    if not key: raise RuntimeError("JWT 签名密钥未配置")
    return jwt.encode({"sub": user.id, "tenantId": user.tenant_id, "role": user.role_code, "type": token_type, "iat": now, "exp": now + expires}, key, algorithm=settings.jwt_algorithm)


def create_tokens(user: User, *, include_refresh: bool = True) -> dict[str, object]:
    tokens: dict[str, object] = {
        "token": _token(user, "access", timedelta(minutes=settings.access_token_minutes)),
        "expiresIn": settings.access_token_minutes * 60,
    }
    if include_refresh:
        tokens["refreshToken"] = _token(user, "refresh", timedelta(days=settings.refresh_token_days))
    return tokens


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        key = settings.jwt_rs256_public_key if settings.jwt_algorithm == "RS256" else settings.jwt_secret
        payload = jwt.decode(token, key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != expected_type:
            raise ValueError("token type")
        return payload
    except Exception as error:
        raise ApiError(401, "CG-1002", "登录状态已失效，请重新登录") from error


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> AuthContext:
    if credentials is None:
        raise ApiError(401, "CG-1002", "请先登录")
    payload = decode_token(credentials.credentials)
    user = db.get(User, payload["sub"])
    if user is None or user.status != "active" or user.tenant_id != payload.get("tenantId"):
        raise ApiError(401, "CG-1002", "登录状态已失效，请重新登录")
    role = db.scalar(select(Role).where(Role.id == user.role_id, Role.tenant_id == user.tenant_id))
    if role is None:
        raise ApiError(403, "CG-1003", "账号未配置有效角色")
    return AuthContext(user.id, user.tenant_id, user.name, user.role_code, tuple(role.permissions))


def require_permission(code: str):
    def dependency(ctx: Annotated[AuthContext, Depends(get_current_user)]) -> AuthContext:
        implied = {
            "risk:manage": lambda p: p.startswith("risk:manage"),
            "incident:manage": lambda p: p == "risk:event:create",
            "decision:view": lambda p: p.startswith("decision:view"),
            "decision:modify": lambda p: p.startswith("decision:modify"),
            "decision:generate": lambda p: p.startswith("decision:modify"),
            "approval:view": lambda p: p.startswith("approval:"),
            "approval:submit": lambda p: p.startswith("approval:"),
            "approval:act": lambda p: p.startswith("approval:") and p != "approval:submit_high",
            "task:view": lambda p: p in {"task:view", "task:execute"},
            "data:import": lambda p: p.startswith("data:import"),
            "data:view": lambda p: p in {"data:view", "data:manage", "settings:manage"} or (p.startswith("data:") and p.endswith(":manage")),
            "report:view": lambda p: p.startswith("report:") or p == "settings:manage",
            "report:executive": lambda p: p == "settings:manage",
            "report:operation": lambda p: p == "settings:manage",
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
