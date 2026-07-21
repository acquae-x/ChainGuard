"""租户级 OIDC 单点登录。

沿用 src/security/rbac.py 骨架的取向（HS256 + issuer/audience/role-claim 校验），
把它从"进程级环境变量"提升为"租户级持久配置"，并补上 Web 登录必需的三件事：
授权跳转、一次性 state/nonce、code 换 token 后的 id_token 校验与账号匹配。

安全约束：
- client_secret 与 ERP 凭证同款 Fernet 加密落库，加密不可用时拒绝保存；任何读接口只回 clientSecretSet。
- state/nonce 一次性消费，回调后立即删除，重放直接失败。
- auto_provision 关闭时，IdP 认证成功但本租户无对应账号 → 拒绝登录，不凭空建号。
"""

from __future__ import annotations

import base64
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error as urlerror, parse, request as urlrequest

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.security.encryption import decrypt_bytes, encrypt_bytes, encryption_status

from .auth import AuthContext
from .config import settings
from .errors import ApiError
from .models import Role, SsoConfig, SsoLoginState, Tenant, User
from .repository import add_audit


REQUIRED_FIELDS = ("issuer", "clientId", "authorizationEndpoint", "tokenEndpoint", "redirectUri")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encrypt_secret(value: str) -> str:
    if not encryption_status()["active"]:
        raise ApiError(503, "CG-1014", "凭证加密未启用，不能保存 SSO 客户端密钥")
    encrypted = encrypt_bytes(value.encode("utf-8"))
    if encrypted == value.encode("utf-8"):
        raise ApiError(503, "CG-1014", "凭证加密不可用，不能保存 SSO 客户端密钥")
    return base64.urlsafe_b64encode(encrypted).decode("ascii")


def _decrypt_secret(item: SsoConfig) -> str:
    if not item.client_secret_encrypted:
        return ""
    try:
        return decrypt_bytes(base64.urlsafe_b64decode(item.client_secret_encrypted.encode("ascii"))).decode("utf-8")
    except Exception as err:
        raise ApiError(503, "CG-1014", "SSO 客户端密钥不可用，请重新配置") from err


def get_config(db: Session, tenant_id: str) -> SsoConfig | None:
    return db.get(SsoConfig, tenant_id)


def public_config(item: SsoConfig | None) -> dict[str, Any]:
    """管理端配置视图。密钥只以布尔位存在，任何情况下都不回显密文或明文。"""
    if item is None:
        return {"configured": False, "enabled": False, "clientSecretSet": False, "issuer": "", "clientId": "",
                "authorizationEndpoint": "", "tokenEndpoint": "", "redirectUri": "", "scopes": "openid email profile",
                "emailClaim": "email", "subjectClaim": "sub", "allowedDomains": [], "autoProvision": False,
                "defaultRoleCode": "auditor", "updatedAt": None}
    return {
        "configured": is_ready(item), "enabled": item.enabled, "clientSecretSet": bool(item.client_secret_encrypted),
        "issuer": item.issuer, "clientId": item.client_id,
        "authorizationEndpoint": item.authorization_endpoint, "tokenEndpoint": item.token_endpoint,
        "redirectUri": item.redirect_uri, "scopes": item.scopes,
        "emailClaim": item.email_claim, "subjectClaim": item.subject_claim,
        "allowedDomains": list(item.allowed_domains or []), "autoProvision": item.auto_provision,
        "defaultRoleCode": item.default_role_code, "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
    }


def is_ready(item: SsoConfig | None) -> bool:
    return bool(item and item.enabled and item.issuer and item.client_id and item.client_secret_encrypted
                and item.authorization_endpoint and item.token_endpoint and item.redirect_uri)


def save_config(db: Session, ctx: AuthContext, values: dict[str, Any]) -> dict[str, Any]:
    item = get_config(db, ctx.tenant_id)
    if item is None:
        item = SsoConfig(tenant_id=ctx.tenant_id)
        db.add(item)
    for field, column in (("issuer", "issuer"), ("clientId", "client_id"),
                          ("authorizationEndpoint", "authorization_endpoint"), ("tokenEndpoint", "token_endpoint"),
                          ("redirectUri", "redirect_uri"), ("scopes", "scopes"),
                          ("emailClaim", "email_claim"), ("subjectClaim", "subject_claim"),
                          ("defaultRoleCode", "default_role_code")):
        if field in values and values[field] is not None:
            setattr(item, column, str(values[field]).strip())
    if "allowedDomains" in values:
        domains = values["allowedDomains"]
        if isinstance(domains, str):
            domains = [part.strip() for part in domains.split(",")]
        item.allowed_domains = [str(part).strip().lower().lstrip("@") for part in (domains or []) if str(part).strip()]
    if "autoProvision" in values:
        item.auto_provision = bool(values["autoProvision"])
    if "enabled" in values:
        item.enabled = bool(values["enabled"])
    secret = str(values.get("clientSecret") or "").strip()
    if secret:
        item.client_secret_encrypted = _encrypt_secret(secret)

    if item.enabled:
        # 域名是"邮箱 → 租户"的唯一解析依据；两家租户claim同一域名会让登录落到错误租户，
        # 因此在启用时就拒绝，而不是留到 discover 时静默取第一条。
        claimed = db.scalars(select(SsoConfig).where(
            SsoConfig.enabled.is_(True), SsoConfig.tenant_id != ctx.tenant_id)).all()
        taken = {str(value).lower() for other in claimed for value in (other.allowed_domains or [])}
        conflicts = sorted(set(item.allowed_domains or []) & taken)
        if conflicts:
            raise ApiError(409, "CG-1014", f"域名已被其他企业的 SSO 配置占用：{'、'.join(conflicts)}")

        missing = [field for field in REQUIRED_FIELDS if not getattr(item, {
            "issuer": "issuer", "clientId": "client_id", "authorizationEndpoint": "authorization_endpoint",
            "tokenEndpoint": "token_endpoint", "redirectUri": "redirect_uri"}[field])]
        if not item.client_secret_encrypted:
            missing.append("clientSecret")
        if missing:
            raise ApiError(422, "CG-1014", f"启用 SSO 前必须填写：{'、'.join(missing)}")
        if item.auto_provision:
            role = db.scalar(select(Role).where(Role.tenant_id == ctx.tenant_id, Role.code == item.default_role_code))
            if role is None:
                raise ApiError(422, "CG-1014", "首次登录自动建号所用的默认角色不存在")

    item.updated_by = ctx.user_id
    item.updated_at = _now()
    # 审计只记开关与端点，密钥字段仅记"是否变更"
    add_audit(db, ctx, "保存 SSO 配置", "sso", ctx.tenant_id, item.issuer or "未配置", {
        "enabled": item.enabled, "issuer": item.issuer, "autoProvision": item.auto_provision,
        "clientSecretChanged": bool(secret),
    })
    db.commit()
    return public_config(item)


def discover(db: Session, account: str = "", tenant_id: str = "") -> dict[str, Any]:
    """登录页探测：这个账号/企业能不能走 SSO。未配置就明说不可用，绝不展示假入口。"""
    item: SsoConfig | None = None
    if tenant_id:
        item = get_config(db, tenant_id)
    elif "@" in account:
        domain = account.strip().lower().rpartition("@")[2]
        for candidate in db.scalars(select(SsoConfig).where(SsoConfig.enabled.is_(True))).all():
            if domain in [str(value).lower() for value in (candidate.allowed_domains or [])]:
                item = candidate
                break
    if not is_ready(item):
        return {"enabled": False, "message": "该企业未配置企业单点登录（SSO），请使用账号密码登录或联系管理员开启。"}
    assert item is not None
    tenant = db.get(Tenant, item.tenant_id)
    return {"enabled": True, "tenantId": item.tenant_id, "tenantName": tenant.name if tenant else "", "issuer": item.issuer}


def start_login(db: Session, tenant_id: str) -> dict[str, Any]:
    item = get_config(db, tenant_id)
    if not is_ready(item):
        raise ApiError(409, "CG-1014", "该企业未配置企业单点登录（SSO），无法发起 SSO 登录")
    assert item is not None
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(16)
    db.add(SsoLoginState(state=state, tenant_id=tenant_id, nonce=nonce, redirect_uri=item.redirect_uri,
                         expires_at=_now() + timedelta(minutes=settings.sso_state_minutes)))
    # 顺手清掉过期 state，避免表无限增长
    for stale in db.scalars(select(SsoLoginState).where(SsoLoginState.expires_at < _now())).all():
        db.delete(stale)
    db.commit()
    query = parse.urlencode({
        "response_type": "code", "client_id": item.client_id, "redirect_uri": item.redirect_uri,
        "scope": item.scopes or "openid email profile", "state": state, "nonce": nonce,
    })
    separator = "&" if "?" in item.authorization_endpoint else "?"
    return {"authorizeUrl": f"{item.authorization_endpoint}{separator}{query}", "state": state, "tenantId": tenant_id}


def _exchange_code(item: SsoConfig, code: str, secret: str) -> dict[str, Any]:
    body = parse.urlencode({
        "grant_type": "authorization_code", "code": code, "redirect_uri": item.redirect_uri,
        "client_id": item.client_id, "client_secret": secret,
    }).encode("utf-8")
    req = urlrequest.Request(item.token_endpoint, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
    })
    try:
        with urlrequest.urlopen(req, timeout=settings.sso_http_timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as err:
        # 上游报文可能含密钥，只透出状态码
        raise ApiError(502, "CG-1015", f"身份提供方拒绝了本次登录（HTTP {err.code}）") from err
    except Exception as err:
        raise ApiError(502, "CG-1015", "无法连接身份提供方，请稍后重试或联系管理员") from err


def complete_login(db: Session, state: str, code: str, request_ip: str = "") -> tuple[User, Tenant]:
    """消费 state → 换 token → 校验 id_token → 匹配账号（或按规则首次加入）。"""
    record = db.get(SsoLoginState, (state or "").strip()) if state else None
    if record is None:
        raise ApiError(400, "CG-1015", "SSO 回调校验失败：登录请求无效或已被使用，请重新发起登录")
    tenant_id, nonce, expired = record.tenant_id, record.nonce, record.expires_at <= _now()
    db.delete(record)  # 一次性消费：无论成败都不允许重放
    db.commit()
    if expired:
        raise ApiError(400, "CG-1015", "SSO 登录请求已超时，请重新发起登录")
    if not (code or "").strip():
        raise ApiError(400, "CG-1015", "SSO 回调缺少授权码")

    item = get_config(db, tenant_id)
    if not is_ready(item):
        raise ApiError(409, "CG-1014", "该企业未配置企业单点登录（SSO）")
    assert item is not None
    secret = _decrypt_secret(item)
    payload = _exchange_code(item, code.strip(), secret)
    id_token = str(payload.get("id_token") or "")
    if not id_token:
        raise ApiError(502, "CG-1015", "身份提供方未返回 id_token，无法完成 SSO 登录")
    try:
        claims = jwt.decode(id_token, secret, algorithms=["HS256"], audience=item.client_id,
                            issuer=item.issuer, options={"require": ["exp", "iss", "aud"]})
    except Exception as err:
        raise ApiError(401, "CG-1015", "SSO 身份令牌校验失败，请联系管理员核对 SSO 配置") from err
    if str(claims.get("nonce") or "") != nonce:
        raise ApiError(401, "CG-1015", "SSO 身份令牌校验失败：nonce 不匹配")

    subject = str(claims.get(item.subject_claim) or claims.get("sub") or "").strip()
    email = str(claims.get(item.email_claim) or "").strip().lower()
    if not subject:
        raise ApiError(401, "CG-1015", "SSO 身份令牌缺少用户标识")
    domains = [str(value).lower() for value in (item.allowed_domains or [])]
    if domains and (not email or email.rpartition("@")[2] not in domains):
        raise ApiError(403, "CG-1015", "该邮箱域名不在企业允许的 SSO 域名范围内")

    user = db.scalar(select(User).where(User.tenant_id == tenant_id, User.sso_subject == subject)) if subject else None
    if user is None and email:
        user = db.scalar(select(User).where(User.tenant_id == tenant_id, User.email == email))
    if user is None:
        if not item.auto_provision:
            raise ApiError(403, "CG-1015", "该 SSO 账号在本企业尚无对应用户，请联系企业管理员先创建账号或开启首次登录自动加入")
        if not email:
            raise ApiError(403, "CG-1015", "SSO 身份令牌缺少邮箱，无法自动创建账号")
        role = db.scalar(select(Role).where(Role.tenant_id == tenant_id, Role.code == item.default_role_code))
        if role is None:
            raise ApiError(409, "CG-1014", "SSO 默认角色不存在，请管理员重新配置")
        user = User(id=f"u-{uuid.uuid4().hex}", tenant_id=tenant_id, account=email,
                    password_hash=f"sso-only-{secrets.token_urlsafe(32)}",  # 非 bcrypt 串，密码登录必然失败
                    name=str(claims.get("name") or email.partition("@")[0]), phone="", email=email,
                    dept_id="dept-1", role_id=role.id, role_code=role.code, status="active",
                    data_scope="custom", sso_subject=subject)
        db.add(user)
        db.flush()
        ctx = AuthContext(user.id, tenant_id, user.name, user.role_code, ())
        add_audit(db, ctx, "SSO 首次登录自动加入", "user", user.id, user.name,
                  {"issuer": item.issuer, "roleCode": role.code}, request_ip)
    if user.status != "active":
        raise ApiError(403, "CG-1005", "账号已停用")
    if not user.sso_subject:
        user.sso_subject = subject

    from .account_lifecycle import clear_login_failures, mask_account
    clear_login_failures(user)
    ctx = AuthContext(user.id, tenant_id, user.name, user.role_code, ())
    add_audit(db, ctx, "SSO 登录", "user", user.id, mask_account(user.account), {"issuer": item.issuer}, request_ip)
    db.commit()
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    return user, tenant
