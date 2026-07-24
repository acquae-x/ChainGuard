from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .errors import ApiError


METRICS_TOKEN_TYPE = "metrics"
METRICS_SCOPE = "metrics:read"
bearer = HTTPBearer(auto_error=False)


def encode_typed_token(
    claims: dict[str, Any],
    *,
    token_type: str,
    expires: timedelta,
) -> str:
    now = datetime.now(timezone.utc)
    key = (
        settings.jwt_rs256_private_key
        if settings.jwt_algorithm == "RS256"
        else settings.jwt_secret
    )
    if not key:
        raise RuntimeError("JWT 签名密钥未配置")
    return jwt.encode(
        {
            **claims,
            "type": token_type,
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + expires,
        },
        key,
        algorithm=settings.jwt_algorithm,
    )


def decode_typed_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        key = (
            settings.jwt_rs256_public_key
            if settings.jwt_algorithm == "RS256"
            else settings.jwt_secret
        )
        payload = jwt.decode(token, key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != expected_type:
            raise ValueError("token type")
        return payload
    except Exception as error:
        raise ApiError(401, "CG-1002", "登录状态已失效，请重新登录") from error


def create_metrics_token(
    *,
    expires: timedelta,
    subject: str = "prometheus",
) -> str:
    return encode_typed_token(
        {"sub": subject, "scope": METRICS_SCOPE},
        token_type=METRICS_TOKEN_TYPE,
        expires=expires,
    )


def require_metrics_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    """Validate the Prometheus service JWT without entering tenant user lookup."""
    if credentials is None:
        raise ApiError(401, "CG-1002", "监控令牌缺失")
    payload = decode_typed_token(credentials.credentials, METRICS_TOKEN_TYPE)
    if payload.get("scope") != METRICS_SCOPE:
        raise ApiError(403, "CG-1003", "监控令牌权限不足")
    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise ApiError(401, "CG-1002", "监控令牌无效")
    return subject
