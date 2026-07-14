from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth.security import AuthContext, create_tokens, decode_token, get_current_user, hash_password, record_refresh_token, revoke_refresh_tokens, verify_password
from ..config import settings
from ..database import get_db
from ..errors import ApiError
from ..models import Role, Tenant, User
from ..limits import limiter
from ..repository import add_audit, serialize
from ..schemas import LoginRequest, RefreshRequest, RegisterRequest


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


@router.post("/login")
@limiter.limit("5/minute")
def login(body: LoginRequest, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]):
    user = db.scalar(select(User).where(or_(User.account == body.account.lower(), User.phone == body.account, User.email == body.account.lower())))
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "CG-1004", "账号或密码错误")
    if user.status != "active":
        raise ApiError(403, "CG-1005", "账号已停用")
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
    tenant = Tenant(id=tenant_id, name=body.company_name.strip(), industry=body.industry, scale=body.scale, status="active", plan=body.plan, trial_end_at="", demo_data_flag=False)
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
