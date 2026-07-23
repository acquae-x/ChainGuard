from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import sso as sso_service
from ..account_lifecycle import (
    assert_not_locked,
    clear_login_failures,
    confirm_password_reset,
    redeem_invitation,
    register_login_failure,
    request_password_reset,
)
from ..auth.security import AuthContext, create_tokens, decode_token, get_current_user, hash_password, record_refresh_token, revoke_refresh_tokens, verify_password
from ..config import settings
from ..database import get_db
from ..errors import ApiError
from ..models import Role, Tenant, User
from ..limits import limiter
from ..repository import add_audit, serialize
from ..schemas import (
    InvitationRedeemRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequestBody,
    RefreshRequest,
    RegisterRequest,
    SsoCallbackRequest,
)


router = APIRouter(prefix="/auth", tags=["auth"])

OWNER_ROLE_CODES = {"老板/总经理": "boss", "供应链负责人": "scm_lead", "IT 管理员": "admin"}


def user_payload(db: Session, user: User) -> dict:
    role = db.get(Role, user.role_id)
    return {"id": user.id, "tenantId": user.tenant_id, "name": user.name, "phone": user.phone, "email": user.email, "deptId": user.dept_id, "roleIds": [user.role_id], "roleCode": user.role_code, "status": user.status, "permissions": role.permissions if role else [], "dataScope": user.data_scope, "readonly": user.role_code == "auditor", "mustChangePassword": user.must_change_password}


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """刷新令牌仅通过受限 HttpOnly Cookie 传递，永不放入 JSON 响应。"""
    response.set_cookie(
        "chainguard_refresh_token",
        refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.refresh_cookie_secure,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path="/api/v1/auth",
    )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("/login")
# IP 限流与账号锁定是两条独立防线：前者按来源地址挡单机高频，后者按账号挡分布式撞库，
# 任一条都不能替代另一条。默认 5/minute 不变，仅允许部署方按需放宽 IP 预算。
@limiter.limit(settings.login_ip_rate_limit)
def login(body: LoginRequest, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]):
    user = db.scalar(select(User).where(or_(User.account == body.account.lower(), User.phone == body.account, User.email == body.account.lower())))
    if user is None:
        # 账号不存在时不落锁定计数，也不区分提示，避免枚举
        raise ApiError(401, "CG-1004", "账号或密码错误")
    assert_not_locked(user)
    if not verify_password(body.password, user.password_hash):
        register_login_failure(db, user, client_ip(request))  # 内部按阈值抛 401 或 423
    if user.status != "active":
        raise ApiError(403, "CG-1005", "账号已停用")
    clear_login_failures(user)
    tenant = db.get(Tenant, user.tenant_id)
    tokens = create_tokens(user)
    record_refresh_token(db, user, str(tokens["refreshToken"]))
    ctx = AuthContext(user.id, user.tenant_id, user.name, user.role_code, ())
    add_audit(db, ctx, "登录", "user", user.id, user.name, {}, request.client.host if request.client else "")
    db.commit()
    set_refresh_cookie(response, str(tokens.pop("refreshToken")))
    return {**tokens, "currentUser": user_payload(db, user), "tenant": serialize(tenant)}


@router.post("/register", status_code=201)
def register(body: RegisterRequest, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]):
    """创建独立租户、九个内置角色和首位业务管理员，供首次开通后直接完成演练。"""
    if len(body.password) < 8:
        raise ApiError(422, "CG-1006", "密码至少需要 8 位")
    if db.scalar(select(User).where(User.phone == body.phone)):
        raise ApiError(409, "CG-1007", "手机号已注册")
    from ..seed import BASE, ROLE_NAMES, ROLE_PERMISSIONS
    import uuid

    tenant_id = f"tenant-{uuid.uuid4().hex}"
    # C3 starts every newly registered tenant in an explicit, resumable
    # initialization state.  It is advisory (users may enter the workspace),
    # while the onboarding API still uses actual entity data as the source of truth.
    tenant = Tenant(id=tenant_id, name=body.company_name.strip(), industry=body.industry, scale=body.scale, status="initializing", plan=body.plan, trial_end_at="", demo_data_flag=False)
    db.add(tenant)
    # PostgreSQL 强制外键：先落库租户再插角色、先角色再用户，固定语句顺序（同 seed.py，SQLite 不校验外键掩盖该问题）
    db.flush()
    roles: dict[str, Role] = {}
    for code, name in ROLE_NAMES.items():
        role = Role(id=f"role-{tenant_id}-{code}", tenant_id=tenant_id, code=code, name=name, builtin=True, permissions=[*BASE, *ROLE_PERMISSIONS[code]])
        roles[code] = role
        db.add(role)
    db.flush()
    role_code = OWNER_ROLE_CODES.get(body.owner_role, "admin")
    user = User(id=f"u-{uuid.uuid4().hex}", tenant_id=tenant_id, account=body.phone, password_hash=hash_password(body.password), name=body.company_name.strip(), phone=body.phone, email="", dept_id="dept-1", role_id=roles[role_code].id, role_code=role_code, status="active", data_scope="all")
    db.add(user)
    ctx = AuthContext(user.id, tenant_id, user.name, role_code, ())
    add_audit(db, ctx, "注册企业", "tenant", tenant_id, tenant.name, {"ownerRole": role_code}, request.client.host if request.client else "")
    db.commit()
    tokens = create_tokens(user)
    record_refresh_token(db, user, str(tokens["refreshToken"]))
    set_refresh_cookie(response, str(tokens.pop("refreshToken")))
    return {**tokens, "currentUser": user_payload(db, user), "tenant": serialize(tenant)}


@router.post("/refresh")
def refresh(
    response: Response,
    _: RefreshRequest | None = None,
    refresh_token: Annotated[str | None, Cookie(alias="chainguard_refresh_token")] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    if not refresh_token:
        raise ApiError(401, "CG-1002", "登录状态已失效，请重新登录")
    payload = decode_token(refresh_token, "refresh", db)
    user = db.get(User, payload["sub"])
    if user is None or user.tenant_id != payload.get("tenantId") or user.status != "active":
        raise ApiError(401, "CG-1002", "登录状态已失效，请重新登录")
    tokens = create_tokens(user)
    revoke_refresh_tokens(db, user, only_jti=payload.get("jti"))
    record_refresh_token(db, user, str(tokens["refreshToken"]))
    db.commit()
    set_refresh_cookie(response, str(tokens.pop("refreshToken")))
    return tokens


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)], refresh_token: Annotated[str | None, Cookie(alias="chainguard_refresh_token")] = None):
    if refresh_token:
        try: revoke_refresh_tokens(db, db.get(User, ctx.user_id), only_jti=decode_token(refresh_token, "refresh").get("jti"))
        except ApiError: pass
    add_audit(db, ctx, "登出", "user", ctx.user_id, ctx.name, {}, request.client.host if request.client else "")
    db.commit()
    response.delete_cookie("chainguard_refresh_token", path="/api/v1/auth")


@router.get("/me")
def me(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    user = db.get(User, ctx.user_id)
    return {"currentUser": user_payload(db, user), "tenant": serialize(db.get(Tenant, ctx.tenant_id))}


def _session_response(db: Session, response: Response, user: User, tenant: Tenant) -> dict:
    tokens = create_tokens(user)
    record_refresh_token(db, user, str(tokens["refreshToken"]))
    db.commit()
    set_refresh_cookie(response, str(tokens.pop("refreshToken")))
    return {**tokens, "currentUser": user_payload(db, user), "tenant": serialize(tenant)}


# --------------------------------------------------------------------------
# 找回密码（通道未配置时降级为管理员兜底，绝不谎称已发送）
# --------------------------------------------------------------------------

@router.post("/password-reset/request")
@limiter.limit("5/minute")
def password_reset_request(body: PasswordResetRequestBody, request: Request, db: Annotated[Session, Depends(get_db)]):
    return request_password_reset(db, body.account, client_ip(request))


@router.post("/password-reset/confirm")
@limiter.limit("10/minute")
def password_reset_confirm(body: PasswordResetConfirmRequest, request: Request, db: Annotated[Session, Depends(get_db)]):
    return confirm_password_reset(db, body.token, body.new_password, client_ip(request))


# --------------------------------------------------------------------------
# 企业邀请码：租户由服务端从邀请码解析，客户端无法指定要加入哪个企业
# --------------------------------------------------------------------------

@router.post("/join", status_code=201)
@limiter.limit("10/minute")
def join_by_invitation(body: InvitationRedeemRequest, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]):
    user, tenant, _invitation = redeem_invitation(db, body.model_dump(by_alias=True), client_ip(request))
    return _session_response(db, response, user, tenant)


# --------------------------------------------------------------------------
# OIDC SSO
# --------------------------------------------------------------------------

@router.get("/sso/discover")
@limiter.limit("30/minute")
def sso_discover(request: Request, db: Annotated[Session, Depends(get_db)], account: str = "", tenantId: str = ""):
    """登录页探测入口是否可用。未配置就明确返回不可用，不展示假的成功。"""
    return sso_service.discover(db, account=account, tenant_id=tenantId)


@router.post("/sso/authorize")
@limiter.limit("20/minute")
def sso_authorize(request: Request, db: Annotated[Session, Depends(get_db)], body: dict | None = None):
    values = body or {}
    tenant_id = str(values.get("tenantId") or "").strip()
    if not tenant_id:
        found = sso_service.discover(db, account=str(values.get("account") or ""))
        if not found.get("enabled"):
            raise ApiError(409, "CG-1014", found.get("message", "该企业未配置企业单点登录（SSO）"))
        tenant_id = str(found["tenantId"])
    return sso_service.start_login(db, tenant_id)


@router.post("/sso/callback")
@limiter.limit("20/minute")
def sso_callback(body: SsoCallbackRequest, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]):
    user, tenant = sso_service.complete_login(db, body.state, body.code, client_ip(request))
    return _session_response(db, response, user, tenant)


@router.post("/change-password")
def change_password(body: dict, request: Request, response: Response, ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    user = db.get(User, ctx.user_id)
    if not verify_password(str(body.get("oldPassword", "")), user.password_hash):
        raise ApiError(422, "CG-1010", "旧密码不正确")
    new_password = str(body.get("newPassword", ""))
    if len(new_password) < 8: raise ApiError(422, "CG-1006", "密码至少需要 8 位")
    user.password_hash, user.must_change_password = hash_password(new_password), False
    revoke_refresh_tokens(db, user)
    add_audit(db, ctx, "修改密码", "user", user.id, user.name, {}, request.client.host if request.client else "")
    db.commit(); response.delete_cookie("chainguard_refresh_token", path="/api/v1/auth")
    return {"ok": True, "reloginRequired": True}
