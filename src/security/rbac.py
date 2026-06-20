from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"view_decision", "run_decision", "export", "approve", "admin"},
    "operator": {"view_decision", "run_decision", "export"},
    "approver": {"view_decision", "approve"},
    "viewer": {"view_decision"},
}

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER_AUTH = HTTPBearer(auto_error=False)


def _api_keys() -> dict[str, str]:
    import src.api as api_module

    return api_module._API_KEYS


async def verify_bearer_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> tuple[str, str] | None:
    """
    Verify an optional OIDC/OAuth2 bearer token and return (subject, role).

    SSO is enabled only when a verifier dependency and IdP settings are present.
    Without those settings, callers fall back to API-key auth/open mode.
    """
    if credentials is None:
        return None

    issuer = os.environ.get("CHAINGUARD_OIDC_ISSUER", "").strip()
    audience = os.environ.get("CHAINGUARD_OIDC_AUDIENCE", "").strip()
    secret = os.environ.get("CHAINGUARD_OIDC_HS256_SECRET", "").strip()
    if not (issuer or audience or secret):
        return None

    try:
        from jose import JWTError, jwt
    except Exception:
        return None

    options = {
        "verify_aud": bool(audience),
        "verify_iss": bool(issuer),
    }
    try:
        claims = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
            audience=audience or None,
            issuer=issuer or None,
            options=options,
        )
    except JWTError as error:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from error

    role_claim = os.environ.get("CHAINGUARD_OIDC_ROLE_CLAIM", "role")
    subject = str(claims.get("sub") or "")
    role = str(claims.get(role_claim) or claims.get("role") or "viewer")
    return subject, role


async def authenticate_role(
    api_key: str | None = Security(_API_KEY_HEADER),
    credentials: HTTPAuthorizationCredentials | None = Security(_BEARER_AUTH),
) -> str:
    """
    Resolve the caller role from API key or optional bearer token.

    Open mode returns admin to preserve the existing no-key behavior.
    """
    keys = _api_keys()
    if api_key:
        if not keys:
            return "admin"
        if api_key in keys:
            return keys[api_key]
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    bearer_identity = await verify_bearer_token(credentials)
    if bearer_identity is not None:
        return bearer_identity[1]

    if not keys:
        return "admin"
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


def require(permission: str) -> Callable:
    """Return a FastAPI dependency that enforces a single RBAC permission."""

    async def dependency(role: str = Depends(authenticate_role)) -> str:
        if permission not in ROLE_PERMISSIONS.get(role, set()):
            raise HTTPException(status_code=403, detail="Insufficient permission")
        return role

    return dependency
