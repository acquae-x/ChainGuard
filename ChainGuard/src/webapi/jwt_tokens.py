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


def _verification_keys() -> list[str]:
    """Return the active verification key followed by comma-separated old keys."""
    if settings.jwt_algorithm == "RS256":
        current = settings.jwt_rs256_public_key
        previous = settings.jwt_rs256_public_key_previous
    else:
        current = settings.jwt_secret
        previous = settings.jwt_secret_previous
    return [current, *(item.strip() for item in previous.split(",") if item.strip())]


def _decode_with_any_verification_key(token: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for key in _verification_keys():
        try:
            return jwt.decode(token, key, algorithms=[settings.jwt_algorithm])
        except Exception as error:
            # A historical key is allowed only for verification.  Continue until
            # one key validates the complete JWT (signature and registered claims).
            last_error = error
    if last_error is not None:
        raise last_error
    raise RuntimeError("JWT 验签密钥未配置")


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
        payload = _decode_with_any_verification_key(token)
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
