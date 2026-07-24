from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session


from ..account_lifecycle import create_invitation, list_invitations, list_password_resets, lock_state, mask_account, resolve_pending_resets, revoke_invitation, unlock_account
from ..auth import AuthContext, require_permission
from ..database import get_db
from ..models import Role, User
from ..repository import add_audit, get_tenant_record, list_tenant_records, serialize


router = APIRouter(tags=["imports-settings"])

@router.get("/settings/users")
def users(ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    items = list_tenant_records(db, User, ctx.tenant_id)
    # 登录标识按 5B 账户完善要求脱敏后回显（字段保留，值不再是可直接撞库的原文）；
    # SSO subject 是 IdP 侧标识，不出接口。锁定状态随行返回，供"解锁"操作判断。
    data = [{**serialize(x, exclude={"sso_subject"}), "account": mask_account(x.account), "roleIds": [x.role_id], "ssoLinked": bool(x.sso_subject), **lock_state(x)} for x in items]
    return {"data": data, "total": len(data), "success": True}


@router.post("/settings/users", status_code=201)
def create_user(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    from ..auth.security import hash_password
    role = get_tenant_record(db, Role, body["roleId"], ctx.tenant_id)
    item = User(id=f"u-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, account=str(body.get("account") or body.get("phone") or body.get("email")).lower(), password_hash=hash_password(str(body.get("password") or uuid.uuid4().hex)), name=body["name"], phone=body.get("phone", ""), email=body.get("email", ""), dept_id=body.get("deptId", "dept-1"), role_id=role.id, role_code=role.code, status=body.get("status", "active"), data_scope=body.get("dataScope", "custom")); db.add(item); add_audit(db, ctx, "创建用户", "user", item.id, item.name, {"roleCode": role.code}); db.commit(); return {"ok": True, "id": item.id}


@router.patch("/settings/users/{item_id}")
def update_user(item_id: str, body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, User, item_id, ctx.tenant_id)
    before = {"name": item.name, "status": item.status, "roleCode": item.role_code}
    for field in ("name", "phone", "email", "status"):
        if field in body: setattr(item, field, body[field])
    if "dataScope" in body: item.data_scope = body["dataScope"]
    if "roleId" in body:
        role = get_tenant_record(db, Role, body["roleId"], ctx.tenant_id); item.role_id = role.id; item.role_code = role.code
    add_audit(db, ctx, "更新用户", "user", item.id, item.name, {"before": before, "after": body}); db.commit(); return {"ok": True, "id": item.id}


@router.post("/settings/users/{item_id}/reset-password")
def reset_user_password(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    from ..auth.security import hash_password, revoke_refresh_tokens
    import secrets
    item = get_tenant_record(db, User, item_id, ctx.tenant_id)
    temporary_password = f"Cg!{secrets.token_urlsafe(9)}"
    item.password_hash, item.must_change_password = hash_password(temporary_password), True
    revoke_refresh_tokens(db, item)
    # 管理员兜底重置同时解锁并关掉该用户的找回密码待办，闭合"通道未配置"降级链路
    from ..account_lifecycle import clear_login_failures
    clear_login_failures(item)
    resolved = resolve_pending_resets(db, ctx, item)
    add_audit(db, ctx, "重置密码", "user", item.id, item.name, {"mustChangePassword": True, "resolvedResetRequests": resolved})
    db.commit()
    return {"ok": True, "temporaryPassword": temporary_password, "mustChangePassword": True, "resolvedResetRequests": resolved}


@router.post("/settings/users/{item_id}/unlock")
def unlock_user(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, User, item_id, ctx.tenant_id)
    result = unlock_account(db, ctx, item)
    db.commit()
    return result


@router.get("/settings/password-resets")
def password_resets(ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    data = list_password_resets(db, ctx.tenant_id)
    return {"data": data, "total": len(data), "success": True}


@router.get("/settings/invitations")
def invitations(ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    data = list_invitations(db, ctx.tenant_id)
    return {"data": data, "total": len(data), "success": True}


@router.post("/settings/invitations", status_code=201)
def add_invitation(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    """返回体里的 code 是这枚邀请码明文唯一一次出现；库内与后续列表只有哈希与掩码。"""
    return create_invitation(db, ctx, body)


@router.post("/settings/invitations/{item_id}/revoke")
def disable_invitation(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    return revoke_invitation(db, ctx, item_id)


@router.delete("/settings/users/{item_id}", status_code=204)
def disable_user(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, User, item_id, ctx.tenant_id); item.status = "disabled"; add_audit(db, ctx, "停用用户", "user", item.id, item.name, {}); db.commit()
