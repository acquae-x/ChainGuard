"""账户生命周期：账号级锁定、找回密码、企业邀请码。

三条共同的纪律：
1. 任何密钥（临时密码、重置令牌、邀请码明文）只在生成的那一次响应里出现，库内只留 sha256。
2. 一切状态落库可审计，不放内存；跨租户查询一律带 tenant_id 谓词。
3. 对外消息不区分"账号存在/不存在"，避免登录页变成账号枚举器。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .auth import AuthContext
from .config import settings
from .errors import ApiError
from .models import InvitationCode, InvitationRedemption, PasswordResetRequest, Role, Tenant, User
from .notifications import ensure_rules, notify_event
from .repository import add_audit


# 去掉 0/O/1/I/L 等易混字符，邀请码要能靠电话口述转达
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 12


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def mask_account(value: str) -> str:
    """把账号脱敏成可辨识但不可还原的形式，用于管理员列表与审计。"""
    value = (value or "").strip()
    if not value:
        return ""
    if "@" in value:
        local, _, domain = value.partition("@")
        head = local[:1] or "*"
        return f"{head}{'*' * max(len(local) - 1, 1)}@{domain}"
    if len(value) >= 7:
        return f"{value[:3]}{'*' * (len(value) - 7)}{value[-4:]}"
    return f"{value[:1]}{'*' * max(len(value) - 1, 1)}"


def find_user_by_account(db: Session, account: str) -> User | None:
    account = (account or "").strip()
    if not account:
        return None
    return db.scalar(select(User).where(or_(
        User.account == account.lower(),
        User.phone == account,
        User.email == account.lower(),
    )))


# --------------------------------------------------------------------------
# 账号级锁定
# --------------------------------------------------------------------------

def lock_state(user: User) -> dict[str, Any]:
    """当前锁定状态；仅供管理员视图与测试使用，不进入登录响应。"""
    locked = bool(user.locked_until and user.locked_until > _now())
    return {
        "locked": locked,
        "lockedUntil": user.locked_until.isoformat() if locked and user.locked_until else None,
        "failedLoginCount": user.failed_login_count,
    }


def assert_not_locked(user: User) -> None:
    if user.locked_until and user.locked_until > _now():
        remaining = max(int((user.locked_until - _now()).total_seconds() // 60) + 1, 1)
        raise ApiError(423, "CG-1011", f"账号已锁定，请在 {remaining} 分钟后重试，或联系企业管理员解锁")


def register_login_failure(db: Session, user: User, request_ip: str = "") -> None:
    """记一次失败；达到阈值即锁定，并抛出对应错误（调用方负责 commit）。"""
    # 锁窗过期后从零开始计数，避免历史失败无限累积把正常用户锁死
    if user.locked_until and user.locked_until <= _now():
        user.failed_login_count = 0
        user.locked_until = None
    user.failed_login_count = (user.failed_login_count or 0) + 1
    user.last_failed_login_at = _now()
    if user.failed_login_count >= settings.account_lock_threshold:
        user.locked_until = _now() + timedelta(minutes=settings.account_lock_minutes)
        ctx = AuthContext(user.id, user.tenant_id, user.name, user.role_code, ())
        add_audit(db, ctx, "账号锁定", "user", user.id, mask_account(user.account),
                  {"failedLoginCount": user.failed_login_count, "lockMinutes": settings.account_lock_minutes}, request_ip)
        ensure_rules(db, user.tenant_id)
        notify_event(db, user.tenant_id, "account_locked", {
            "title": f"账号 {mask_account(user.account)} 连续登录失败已锁定 {settings.account_lock_minutes} 分钟",
            "target": "/settings/users",
        })
        db.commit()
        raise ApiError(423, "CG-1011", f"连续 {settings.account_lock_threshold} 次登录失败，账号已锁定 {settings.account_lock_minutes} 分钟")
    db.commit()
    raise ApiError(401, "CG-1004", "账号或密码错误")


def clear_login_failures(user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None


def unlock_account(db: Session, ctx: AuthContext, user: User) -> dict[str, Any]:
    clear_login_failures(user)
    add_audit(db, ctx, "解锁账号", "user", user.id, mask_account(user.account), {"unlockedBy": ctx.user_id})
    return {"ok": True, "id": user.id, **lock_state(user)}


# --------------------------------------------------------------------------
# 找回密码
# --------------------------------------------------------------------------

def channel_status() -> dict[str, Any]:
    """通道是否真的可用。只有 smtp 且必填项齐全才算配置好。"""
    channel = settings.password_reset_channel
    if channel == "smtp":
        configured = bool(settings.smtp_host and settings.smtp_sender)
        return {"channel": "smtp", "configured": configured}
    return {"channel": "none", "configured": False}


def _send_reset_email(user: User, token: str) -> None:
    import smtplib
    from email.message import EmailMessage

    link = f"{settings.password_reset_link_base}?token={token}"
    message = EmailMessage()
    message["Subject"] = "ChainGuard 密码重置"
    message["From"] = settings.smtp_sender
    message["To"] = user.email
    message.set_content(
        f"你正在重置 ChainGuard 账号密码。\n\n重置链接（{settings.password_reset_token_minutes} 分钟内有效，仅可使用一次）：\n{link}\n\n"
        "若不是你本人操作，请忽略本邮件并联系企业管理员。"
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def request_password_reset(db: Session, account: str, request_ip: str = "") -> dict[str, Any]:
    """受理找回申请。

    响应对"账号存在/不存在"完全一致（措辞为条件句），因此不能用于枚举账号；
    通道未配置时明确告知无法自助，并生成管理员待办 —— 绝不谎称已发送。
    """
    status = channel_status()
    user = find_user_by_account(db, account)
    delivered = False
    delivery_error = ""

    if user is not None and user.status == "active":
        # 同一账号的旧待办作废，避免多条 pending 令牌同时有效
        for stale in db.scalars(select(PasswordResetRequest).where(
            PasswordResetRequest.user_id == user.id, PasswordResetRequest.status == "pending"
        )).all():
            stale.status = "superseded"

        record = PasswordResetRequest(
            id=f"reset-{uuid.uuid4().hex}", tenant_id=user.tenant_id, user_id=user.id,
            expires_at=_now() + timedelta(minutes=settings.password_reset_token_minutes),
            request_ip=request_ip, channel=status["channel"],
        )
        if status["configured"] and user.email:
            token = secrets.token_urlsafe(32)
            record.mode, record.token_hash = "self_service", _digest(token)
            try:
                _send_reset_email(user, token)
                delivered = True
            except Exception as error:  # 投递失败就如实降级，不写"已发送"
                delivery_error = type(error).__name__
                record.mode, record.token_hash, record.channel = "manual_admin", "", "none"
        db.add(record)

        if record.mode == "manual_admin":
            ensure_rules(db, user.tenant_id)
            notify_event(db, user.tenant_id, "password_reset_requested", {
                "title": f"账号 {mask_account(user.account)} 申请重置密码，请在用户管理中代为重置",
                "target": "/settings/users",
            })
        ctx = AuthContext(user.id, user.tenant_id, user.name, user.role_code, ())
        add_audit(db, ctx, "申请找回密码", "user", user.id, mask_account(user.account),
                  {"mode": record.mode, "channel": record.channel, "delivered": delivered, "deliveryError": delivery_error}, request_ip)
    db.commit()

    if delivered:
        return {
            "mode": "self_service", "channelConfigured": True, "channel": status["channel"],
            "message": f"若该账号存在且已绑定可用邮箱，重置链接已发送，{settings.password_reset_token_minutes} 分钟内有效。",
        }
    if status["configured"]:
        return {
            "mode": "manual_admin", "channelConfigured": True, "channel": status["channel"], "deliveryFailed": bool(delivery_error),
            "message": "邮件通道当前不可用，未能发送重置链接。请联系企业管理员在「系统设置 → 用户管理」中重置密码。",
        }
    return {
        "mode": "manual_admin", "channelConfigured": False, "channel": "none",
        "message": "本系统尚未配置邮件/短信通道，无法自助发送重置链接。若该账号存在，已生成管理员待办；请联系企业管理员在「系统设置 → 用户管理」中重置密码。",
    }


def confirm_password_reset(db: Session, token: str, new_password: str, request_ip: str = "") -> dict[str, Any]:
    from .auth.security import hash_password, revoke_refresh_tokens

    if len(new_password) < 8:
        raise ApiError(422, "CG-1006", "密码至少需要 8 位")
    token = (token or "").strip()
    record = db.scalar(select(PasswordResetRequest).where(
        PasswordResetRequest.token_hash == _digest(token),
        PasswordResetRequest.status == "pending",
        PasswordResetRequest.mode == "self_service",
    )) if token else None
    if record is None or record.expires_at <= _now():
        if record is not None:
            record.status = "expired"
            db.commit()
        raise ApiError(400, "CG-1013", "重置链接无效或已过期，请重新申请")
    user = db.get(User, record.user_id)
    if user is None or user.tenant_id != record.tenant_id or user.status != "active":
        raise ApiError(400, "CG-1013", "重置链接无效或已过期，请重新申请")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    clear_login_failures(user)  # 自助改密成功即解除锁定：持有邮箱控制权已证明是本人
    revoke_refresh_tokens(db, user)
    record.status, record.used_at, record.token_hash = "used", _now(), ""
    ctx = AuthContext(user.id, user.tenant_id, user.name, user.role_code, ())
    add_audit(db, ctx, "自助重置密码", "user", user.id, mask_account(user.account), {"requestId": record.id}, request_ip)
    db.commit()
    return {"ok": True, "reloginRequired": True}


def resolve_pending_resets(db: Session, ctx: AuthContext, user: User) -> int:
    """管理员代为重置后，关掉该用户的重置待办。"""
    pending = list(db.scalars(select(PasswordResetRequest).where(
        PasswordResetRequest.tenant_id == ctx.tenant_id,
        PasswordResetRequest.user_id == user.id,
        PasswordResetRequest.status == "pending",
    )).all())
    for item in pending:
        item.status, item.used_at, item.resolved_by, item.token_hash = "resolved_by_admin", _now(), ctx.user_id, ""
    return len(pending)


def list_password_resets(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(select(PasswordResetRequest).where(
        PasswordResetRequest.tenant_id == tenant_id
    ).order_by(PasswordResetRequest.created_at.desc()).limit(50)).all()
    result: list[dict[str, Any]] = []
    for item in rows:
        user = db.get(User, item.user_id)
        expired = item.status == "pending" and item.expires_at <= _now()
        result.append({
            "id": item.id, "userId": item.user_id,
            "userName": user.name if user else "",
            "account": mask_account(user.account if user else ""),
            "mode": item.mode, "channel": item.channel,
            "status": "expired" if expired else item.status,
            "expiresAt": item.expires_at.isoformat(),
            "createdAt": item.created_at.isoformat(),
        })
    return result


# --------------------------------------------------------------------------
# 企业邀请码
# --------------------------------------------------------------------------

def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def _invitation_view(item: InvitationCode, db: Session) -> dict[str, Any]:
    """列表视图：只有前 4 位提示 + 掩码，永不回显完整邀请码。"""
    # 失效是终态；用尽/过期在库里可能已落成终态，也可能还挂着 active 由此处推导。
    if item.status == "revoked":
        status = "revoked"
    elif item.status == "exhausted" or item.used_count >= item.max_uses:
        status = "exhausted"
    elif item.expires_at <= _now():
        status = "expired"
    else:
        status = "active"
    redemptions = db.scalars(select(InvitationRedemption).where(
        InvitationRedemption.tenant_id == item.tenant_id, InvitationRedemption.invitation_id == item.id
    ).order_by(InvitationRedemption.created_at.desc())).all()
    return {
        "id": item.id,
        "codeMasked": f"{item.code_prefix}{'*' * (_CODE_LENGTH - len(item.code_prefix))}",
        "roleCode": item.role_code, "deptId": item.dept_id, "dataScope": item.data_scope,
        "note": item.note, "status": status,
        "maxUses": item.max_uses, "usedCount": item.used_count,
        "expiresAt": item.expires_at.isoformat(), "createdAt": item.created_at.isoformat(),
        "createdBy": item.created_by, "revokedBy": item.revoked_by,
        "revokedAt": item.revoked_at.isoformat() if item.revoked_at else None,
        "redemptions": [{
            "userId": row.user_id, "userName": row.user_name, "roleCode": row.role_code,
            "createdAt": row.created_at.isoformat(),
        } for row in redemptions],
    }


def create_invitation(db: Session, ctx: AuthContext, values: dict[str, Any]) -> dict[str, Any]:
    role_code = str(values.get("roleCode") or "").strip()
    role = db.scalar(select(Role).where(Role.tenant_id == ctx.tenant_id, Role.code == role_code))
    if role is None:
        raise ApiError(422, "CG-1012", "邀请角色不存在或不属于当前企业")
    try:
        max_uses = int(values.get("maxUses", 1))
        valid_hours = int(values.get("validHours", 72))
    except (TypeError, ValueError):
        raise ApiError(422, "CG-1012", "有效期与使用次数必须为整数") from None
    if not 1 <= max_uses <= 200:
        raise ApiError(422, "CG-1012", "使用次数需在 1–200 之间")
    if not 1 <= valid_hours <= 24 * 30:
        raise ApiError(422, "CG-1012", "有效期需在 1 小时至 30 天之间")

    code = _generate_code()
    item = InvitationCode(
        id=f"invite-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id,
        code_hash=_digest(code), code_prefix=code[:4],
        role_id=role.id, role_code=role.code,
        dept_id=str(values.get("deptId") or "dept-1"),
        data_scope=str(values.get("dataScope") or "custom"),
        note=str(values.get("note") or "")[:200],
        max_uses=max_uses, used_count=0, status="active",
        expires_at=_now() + timedelta(hours=valid_hours),
        created_by=ctx.user_id,
    )
    db.add(item)
    add_audit(db, ctx, "生成邀请码", "invitation", item.id, f"{item.code_prefix}****",
              {"roleCode": role.code, "maxUses": max_uses, "validHours": valid_hours})
    db.commit()
    # code 明文只在这一次返回，之后任何接口都取不到
    return {"invitation": _invitation_view(item, db), "code": code}


def list_invitations(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(select(InvitationCode).where(
        InvitationCode.tenant_id == tenant_id
    ).order_by(InvitationCode.created_at.desc())).all()
    return [_invitation_view(item, db) for item in rows]


def revoke_invitation(db: Session, ctx: AuthContext, invitation_id: str) -> dict[str, Any]:
    item = db.scalar(select(InvitationCode).where(
        InvitationCode.id == invitation_id, InvitationCode.tenant_id == ctx.tenant_id
    ))
    if item is None:
        raise ApiError(404, "CG-2001", "邀请码不存在")
    item.status, item.revoked_by, item.revoked_at = "revoked", ctx.user_id, _now()
    add_audit(db, ctx, "失效邀请码", "invitation", item.id, f"{item.code_prefix}****", {"usedCount": item.used_count})
    db.commit()
    return _invitation_view(item, db)


def redeem_invitation(db: Session, values: dict[str, Any], request_ip: str = "") -> tuple[User, Tenant, InvitationCode]:
    """凭邀请码加入 **邀请码所属租户**；租户由服务端从码解析，客户端无从指定。"""
    from .auth.security import hash_password

    code = str(values.get("code") or "").strip().upper()
    name = str(values.get("name") or "").strip()
    phone = str(values.get("phone") or "").strip()
    email = str(values.get("email") or "").strip().lower()
    password = str(values.get("password") or "")
    if not code or not name or not (phone or email):
        raise ApiError(422, "CG-1012", "请填写邀请码、姓名与手机号/邮箱")
    if len(password) < 8:
        raise ApiError(422, "CG-1006", "密码至少需要 8 位")

    item = db.scalar(select(InvitationCode).where(InvitationCode.code_hash == _digest(code)))
    # 无效/过期/用尽/已失效一律同一条提示，避免探测哪些码存在
    if item is None or item.status != "active" or item.expires_at <= _now() or item.used_count >= item.max_uses:
        raise ApiError(400, "CG-1012", "邀请码无效、已失效或已达使用上限，请向企业管理员索取新的邀请码")

    account = (phone or email).lower()
    if db.scalar(select(User).where(User.tenant_id == item.tenant_id, User.account == account)):
        raise ApiError(409, "CG-1007", "该手机号/邮箱已在本企业注册，请直接登录")

    role = db.scalar(select(Role).where(Role.id == item.role_id, Role.tenant_id == item.tenant_id))
    if role is None:
        raise ApiError(409, "CG-1012", "邀请码对应的角色已被删除，请联系管理员重新生成")

    user = User(
        id=f"u-{uuid.uuid4().hex}", tenant_id=item.tenant_id, account=account,
        password_hash=hash_password(password), name=name, phone=phone, email=email,
        dept_id=item.dept_id, role_id=role.id, role_code=role.code,
        status="active", data_scope=item.data_scope,
    )
    db.add(user)
    item.used_count += 1
    if item.used_count >= item.max_uses:
        item.status = "exhausted"
    db.add(InvitationRedemption(
        id=f"redeem-{uuid.uuid4().hex}", tenant_id=item.tenant_id, invitation_id=item.id,
        user_id=user.id, user_name=user.name, role_code=role.code, request_ip=request_ip,
    ))
    ctx = AuthContext(user.id, item.tenant_id, user.name, role.code, ())
    add_audit(db, ctx, "邀请码加入企业", "invitation", item.id, f"{item.code_prefix}****",
              {"userId": user.id, "account": mask_account(account), "roleCode": role.code}, request_ip)
    db.commit()
    tenant = db.get(Tenant, item.tenant_id)
    assert tenant is not None
    return user, tenant, item
