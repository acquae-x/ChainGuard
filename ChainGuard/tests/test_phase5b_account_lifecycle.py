"""「账户完善」后端锁定测试。

覆盖四件事及其安全边界：账号级锁定、找回密码（含通道未配置降级）、企业邀请码、OIDC SSO。
SSO 用例跑的是真实 HTTP 授权码交换（scripts/mock_oidc_server 起在环回地址），
不是把 _exchange_code 打桩，这样 id_token 校验、nonce、state 一次性都被真正执行到。
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from urllib import error as urlerror, parse, request as urlrequest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mock_oidc_server import MockOidcProvider, start_server  # noqa: E402

from src.api import app  # noqa: E402
from src.webapi import account_lifecycle  # noqa: E402
from src.webapi.auth.security import hash_password  # noqa: E402
from src.webapi.config import settings  # noqa: E402
from src.webapi.database import Base, SessionLocal, engine  # noqa: E402
from src.webapi.limits import limiter  # noqa: E402
from src.webapi.models import AuditLog, InvitationCode, PasswordResetRequest, Role, SsoConfig, SsoLoginState, Tenant, User  # noqa: E402


client = TestClient(app)
PASSWORD = "Account@2026!"

ADMIN_PERMISSIONS = ["dashboard:view", "risk:view", "incident:view", "settings:manage", "data:view"]
MEMBER_PERMISSIONS = ["dashboard:view", "risk:view", "incident:view", "decision:view"]


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _make_tenant(db, tenant_id: str, name: str) -> None:
    db.add(Tenant(id=tenant_id, name=name, industry="电子制造", scale="50-200",
                  status="active", plan="trial", trial_end_at="", demo_data_flag=False))
    db.flush()


def _make_role(db, tenant_id: str, code: str, permissions: list[str]) -> Role:
    role = Role(id=f"role-{tenant_id}-{code}", tenant_id=tenant_id, code=code, name=code,
                builtin=False, permissions=permissions)
    db.add(role)
    db.flush()
    return role


def _make_user(db, tenant_id: str, account: str, role: Role, *, email: str = "") -> User:
    user = User(id=f"u-{uuid.uuid4().hex}", tenant_id=tenant_id, account=account.lower(),
                password_hash=hash_password(PASSWORD), name=account, phone="",
                email=(email or account).lower(), dept_id="dept-1", role_id=role.id,
                role_code=role.code, status="active", data_scope="all")
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def tenant_fixture():
    """一个独立租户 + 一个管理员 + 一个普通成员，跨用例互不干扰。"""
    Base.metadata.create_all(engine)
    tenant_id = _unique("tenant-acct")
    admin_account = f"{_unique('admin')}@account.test"
    member_account = f"{_unique('member')}@account.test"
    with SessionLocal() as db:
        _make_tenant(db, tenant_id, "账户完善测试租户")
        admin_role = _make_role(db, tenant_id, "admin", ADMIN_PERMISSIONS)
        member_role = _make_role(db, tenant_id, "buyer", MEMBER_PERMISSIONS)
        _make_role(db, tenant_id, "auditor", MEMBER_PERMISSIONS)
        admin = _make_user(db, tenant_id, admin_account, admin_role)
        member = _make_user(db, tenant_id, member_account, member_role)
        db.commit()
        data = {"tenantId": tenant_id, "adminAccount": admin_account, "memberAccount": member_account,
                "adminId": admin.id, "memberId": member.id,
                # SSO 域名在全局唯一，每个租户必须用自己的域
                "ssoDomain": f"{tenant_id}.sso-test.example"}
    return data


@pytest.fixture
def no_ip_limit():
    """临时关掉 IP 限流，以便单独观测账号维度锁定。

    两条防线是独立的：本 fixture 只影响 IP 维度，账号锁定阈值不受影响；
    IP 限流本身由 test_ip_rate_limit_is_independent_of_account_lock 单独锁定。
    """
    limiter.enabled = False
    yield
    limiter.enabled = True


def _login(account: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"account": account, "password": password})


def _headers(account: str) -> dict[str, str]:
    response = _login(account)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


# --------------------------------------------------------------------------
# 账号级锁定
# --------------------------------------------------------------------------

def test_account_locks_after_five_failures_and_admin_can_unlock(tenant_fixture, no_ip_limit):
    account = tenant_fixture["memberAccount"]
    for attempt in range(settings.account_lock_threshold - 1):
        response = _login(account, "wrong-password")
        assert response.status_code == 401, f"第 {attempt + 1} 次失败应仍是凭证错误：{response.text}"

    locking = _login(account, "wrong-password")
    assert locking.status_code == 423
    assert "锁定" in locking.json()["message"]

    # 锁定期内即使密码正确也必须拒绝，否则锁定形同虚设
    correct = _login(account)
    assert correct.status_code == 423

    with SessionLocal() as db:
        user = db.get(User, tenant_fixture["memberId"])
        assert user.failed_login_count >= settings.account_lock_threshold
        assert user.locked_until is not None and user.locked_until > datetime.now(timezone.utc)

    admin_headers = _headers(tenant_fixture["adminAccount"])
    listed = client.get("/api/v1/settings/users", headers=admin_headers).json()["data"]
    locked_row = next(row for row in listed if row["id"] == tenant_fixture["memberId"])
    assert locked_row["locked"] is True and locked_row["lockedUntil"]
    # 登录标识脱敏回显，SSO subject 完全不出接口
    assert "*" in locked_row["account"] and locked_row["account"] != tenant_fixture["memberAccount"]
    assert "ssoSubject" not in locked_row

    unlocked = client.post(f"/api/v1/settings/users/{tenant_fixture['memberId']}/unlock", headers=admin_headers)
    assert unlocked.status_code == 200 and unlocked.json()["locked"] is False
    assert _login(account).status_code == 200

    with SessionLocal() as db:
        actions = {row.action for row in db.scalars(
            select(AuditLog).where(AuditLog.tenant_id == tenant_fixture["tenantId"])).all()}
    assert {"账号锁定", "解锁账号"} <= actions


def test_successful_login_resets_failure_counter(tenant_fixture, no_ip_limit):
    account = tenant_fixture["memberAccount"]
    for _ in range(settings.account_lock_threshold - 1):
        assert _login(account, "wrong-password").status_code == 401
    assert _login(account).status_code == 200

    with SessionLocal() as db:
        assert db.get(User, tenant_fixture["memberId"]).failed_login_count == 0

    # 计数已归零，因此下一轮又能失败 threshold-1 次而不被锁
    for _ in range(settings.account_lock_threshold - 1):
        assert _login(account, "wrong-password").status_code == 401
    assert _login(account).status_code == 200


def test_ip_rate_limit_is_independent_of_account_lock(tenant_fixture):
    """IP 限流与账号锁定并存：默认预算不变，且用不同账号也会被 IP 维度挡下。"""
    assert settings.login_ip_rate_limit == "5/minute"
    limiter.reset()
    statuses = [_login(f"{_unique('ghost')}@account.test", "wrong-password").status_code for _ in range(6)]
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429, "第 6 次不同账号的尝试仍应被 IP 限流拦下"
    limiter.reset()


def test_unknown_account_does_not_leak_existence(tenant_fixture, no_ip_limit):
    missing = _login(f"{_unique('nobody')}@account.test", "whatever-password")
    existing = _login(tenant_fixture["memberAccount"], "wrong-password")
    assert missing.status_code == existing.status_code == 401
    assert missing.json()["message"] == existing.json()["message"]


# --------------------------------------------------------------------------
# 找回密码
# --------------------------------------------------------------------------

def test_password_reset_degrades_to_admin_fallback_without_channel(tenant_fixture, no_ip_limit):
    response = client.post("/api/v1/auth/password-reset/request", json={"account": tenant_fixture["memberAccount"]})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "manual_admin" and body["channelConfigured"] is False
    # 明确不得出现"已发送"的表述
    assert "已发送" not in body["message"]
    assert "管理员" in body["message"] and "未配置" in body["message"]
    assert "token" not in response.text.lower()

    admin_headers = _headers(tenant_fixture["adminAccount"])
    pending = client.get("/api/v1/settings/password-resets", headers=admin_headers).json()["data"]
    entry = next(item for item in pending if item["userId"] == tenant_fixture["memberId"])
    assert entry["mode"] == "manual_admin" and entry["status"] == "pending"
    assert "*" in entry["account"], "管理员待办里的账号必须脱敏"

    reset = client.post(f"/api/v1/settings/users/{tenant_fixture['memberId']}/reset-password", headers=admin_headers)
    assert reset.status_code == 200 and reset.json()["resolvedResetRequests"] == 1
    temporary = reset.json()["temporaryPassword"]

    after = client.get("/api/v1/settings/password-resets", headers=admin_headers).json()["data"]
    assert next(item for item in after if item["userId"] == tenant_fixture["memberId"])["status"] == "resolved_by_admin"

    logged_in = _login(tenant_fixture["memberAccount"], temporary)
    assert logged_in.status_code == 200
    assert logged_in.json()["currentUser"]["mustChangePassword"] is True


def test_password_reset_request_is_identical_for_unknown_account(tenant_fixture, no_ip_limit):
    known = client.post("/api/v1/auth/password-reset/request", json={"account": tenant_fixture["memberAccount"]})
    unknown = client.post("/api/v1/auth/password-reset/request", json={"account": f"{_unique('nobody')}@account.test"})
    assert known.json() == unknown.json()


def test_self_service_reset_consumes_one_time_token(tenant_fixture, no_ip_limit, monkeypatch):
    delivered: list[str] = []
    monkeypatch.setattr(account_lifecycle, "channel_status", lambda: {"channel": "smtp", "configured": True})
    monkeypatch.setattr(account_lifecycle, "_send_reset_email", lambda user, token: delivered.append(token))

    response = client.post("/api/v1/auth/password-reset/request", json={"account": tenant_fixture["memberAccount"]})
    body = response.json()
    assert body["mode"] == "self_service" and body["channelConfigured"] is True
    assert delivered and delivered[0] not in response.text, "重置令牌绝不能出现在接口响应里"
    token = delivered[0]

    with SessionLocal() as db:
        record = db.scalar(select(PasswordResetRequest).where(
            PasswordResetRequest.user_id == tenant_fixture["memberId"],
            PasswordResetRequest.status == "pending"))
        assert record is not None and record.token_hash != token, "库内只能存令牌哈希"

    assert client.post("/api/v1/auth/password-reset/confirm",
                       json={"token": token, "newPassword": "short"}).status_code == 422

    new_password = "Renewed@2026!"
    confirmed = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "newPassword": new_password})
    assert confirmed.status_code == 200
    assert _login(tenant_fixture["memberAccount"], new_password).status_code == 200

    replay = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "newPassword": "Another@2026!"})
    assert replay.status_code == 400, "令牌必须一次性"


def test_expired_reset_token_is_rejected(tenant_fixture, no_ip_limit, monkeypatch):
    delivered: list[str] = []
    monkeypatch.setattr(account_lifecycle, "channel_status", lambda: {"channel": "smtp", "configured": True})
    monkeypatch.setattr(account_lifecycle, "_send_reset_email", lambda user, token: delivered.append(token))
    client.post("/api/v1/auth/password-reset/request", json={"account": tenant_fixture["memberAccount"]})

    with SessionLocal() as db:
        record = db.scalar(select(PasswordResetRequest).where(
            PasswordResetRequest.user_id == tenant_fixture["memberId"],
            PasswordResetRequest.status == "pending"))
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    response = client.post("/api/v1/auth/password-reset/confirm",
                           json={"token": delivered[0], "newPassword": "Renewed@2026!"})
    assert response.status_code == 400
    assert _login(tenant_fixture["memberAccount"]).status_code == 200, "原密码应仍然有效"


def test_member_cannot_reset_other_users_password(tenant_fixture, no_ip_limit):
    member_headers = _headers(tenant_fixture["memberAccount"])
    for path in (f"/api/v1/settings/users/{tenant_fixture['adminId']}/reset-password",
                 f"/api/v1/settings/users/{tenant_fixture['adminId']}/unlock"):
        assert client.post(path, headers=member_headers).status_code == 403
    assert client.get("/api/v1/settings/password-resets", headers=member_headers).status_code == 403


# --------------------------------------------------------------------------
# 企业邀请码
# --------------------------------------------------------------------------

def _create_invitation(headers: dict[str, str], **values):
    payload = {"roleCode": "buyer", "maxUses": 1, "validHours": 24, **values}
    response = client.post("/api/v1/settings/invitations", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_invitation_code_is_returned_once_and_never_echoed(tenant_fixture, no_ip_limit):
    admin_headers = _headers(tenant_fixture["adminAccount"])
    created = _create_invitation(admin_headers, note="给采购同事")
    code = created["code"]
    assert len(code) == 12 and created["invitation"]["codeMasked"].endswith("*")

    listed = client.get("/api/v1/settings/invitations", headers=admin_headers)
    assert code not in listed.text, "列表接口不得回显邀请码明文"
    row = next(item for item in listed.json()["data"] if item["id"] == created["invitation"]["id"])
    assert row["codeMasked"].startswith(code[:4]) and row["status"] == "active"

    with SessionLocal() as db:
        stored = db.get(InvitationCode, created["invitation"]["id"])
        assert stored.code_hash != code and len(stored.code_hash) == 64


def test_invitation_join_lands_in_the_issuing_tenant_with_preset_role(tenant_fixture, no_ip_limit):
    admin_headers = _headers(tenant_fixture["adminAccount"])
    created = _create_invitation(admin_headers, maxUses=2, roleCode="buyer")
    joiner = f"{_unique('joiner')}@account.test"

    response = client.post("/api/v1/auth/join", json={
        "code": created["code"], "name": "受邀同事", "email": joiner, "password": "Joined@2026!"})
    assert response.status_code == 201, response.text
    payload = response.json()
    # 租户由服务端从邀请码解析，客户端无从指定
    assert payload["tenant"]["id"] == tenant_fixture["tenantId"]
    assert payload["currentUser"]["roleCode"] == "buyer"

    detail = client.get("/api/v1/settings/invitations", headers=admin_headers).json()["data"]
    row = next(item for item in detail if item["id"] == created["invitation"]["id"])
    assert row["usedCount"] == 1 and row["status"] == "active"
    assert row["redemptions"][0]["userName"] == "受邀同事", "使用记录必须留痕"

    with SessionLocal() as db:
        actions = [entry.action for entry in db.scalars(select(AuditLog).where(
            AuditLog.tenant_id == tenant_fixture["tenantId"])).all()]
    assert "邀请码加入企业" in actions


def test_invitation_exhausts_and_can_be_revoked(tenant_fixture, no_ip_limit):
    admin_headers = _headers(tenant_fixture["adminAccount"])
    single = _create_invitation(admin_headers, maxUses=1)
    assert client.post("/api/v1/auth/join", json={
        "code": single["code"], "name": "首位", "email": f"{_unique('first')}@account.test",
        "password": "Joined@2026!"}).status_code == 201
    used_up = client.post("/api/v1/auth/join", json={
        "code": single["code"], "name": "第二位", "email": f"{_unique('second')}@account.test",
        "password": "Joined@2026!"})
    assert used_up.status_code == 400 and "邀请码" in used_up.json()["message"]

    # 用尽是终态：列表必须显示"已用尽"，不能因为落库状态已变而回退成"生效中"
    listed = client.get("/api/v1/settings/invitations", headers=admin_headers).json()["data"]
    assert next(item for item in listed if item["id"] == single["invitation"]["id"])["status"] == "exhausted"

    revocable = _create_invitation(admin_headers, maxUses=5)
    revoked = client.post(f"/api/v1/settings/invitations/{revocable['invitation']['id']}/revoke", headers=admin_headers)
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    after = client.post("/api/v1/auth/join", json={
        "code": revocable["code"], "name": "被拒", "email": f"{_unique('late')}@account.test",
        "password": "Joined@2026!"})
    assert after.status_code == 400


def test_expired_invitation_is_rejected(tenant_fixture, no_ip_limit):
    admin_headers = _headers(tenant_fixture["adminAccount"])
    created = _create_invitation(admin_headers)
    with SessionLocal() as db:
        item = db.get(InvitationCode, created["invitation"]["id"])
        item.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    response = client.post("/api/v1/auth/join", json={
        "code": created["code"], "name": "迟到者", "email": f"{_unique('late')}@account.test",
        "password": "Joined@2026!"})
    assert response.status_code == 400


def test_invitations_are_tenant_isolated(tenant_fixture, no_ip_limit):
    other_tenant = _unique("tenant-other")
    other_admin = f"{_unique('otheradmin')}@account.test"
    with SessionLocal() as db:
        _make_tenant(db, other_tenant, "另一家企业")
        role = _make_role(db, other_tenant, "admin", ADMIN_PERMISSIONS)
        _make_user(db, other_tenant, other_admin, role)
        db.commit()

    created = _create_invitation(_headers(tenant_fixture["adminAccount"]))
    other_headers = _headers(other_admin)

    visible = client.get("/api/v1/settings/invitations", headers=other_headers).json()["data"]
    assert all(item["id"] != created["invitation"]["id"] for item in visible), "跨租户不得看到别家邀请码"
    assert client.post(f"/api/v1/settings/invitations/{created['invitation']['id']}/revoke",
                       headers=other_headers).status_code == 404, "跨租户不得失效别家邀请码"

    # 用 A 家的码加入，落点必须是 A 家而不是调用者所属租户
    joined = client.post("/api/v1/auth/join", json={
        "code": created["code"], "name": "跨租户受邀", "email": f"{_unique('cross')}@account.test",
        "password": "Joined@2026!"})
    assert joined.json()["tenant"]["id"] == tenant_fixture["tenantId"]


def test_member_cannot_manage_invitations(tenant_fixture, no_ip_limit):
    member_headers = _headers(tenant_fixture["memberAccount"])
    assert client.get("/api/v1/settings/invitations", headers=member_headers).status_code == 403
    assert client.post("/api/v1/settings/invitations", json={"roleCode": "buyer"},
                       headers=member_headers).status_code == 403
    assert client.post("/api/v1/settings/invitations/whatever/revoke", headers=member_headers).status_code == 403


def test_invitation_role_must_belong_to_the_tenant(tenant_fixture, no_ip_limit):
    admin_headers = _headers(tenant_fixture["adminAccount"])
    response = client.post("/api/v1/settings/invitations",
                           json={"roleCode": "role-that-does-not-exist"}, headers=admin_headers)
    assert response.status_code == 422


# --------------------------------------------------------------------------
# OIDC SSO
# --------------------------------------------------------------------------

CLIENT_ID = "chainguard-test-client"
CLIENT_SECRET = "chainguard-test-client-secret-0123456789"


@pytest.fixture
def idp():
    provider = MockOidcProvider(issuer="", client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
                                subject="sso-subject-001", email="", name="SSO 测试用户")
    server, base = start_server(provider)
    provider.issuer = base  # issuer 必须与实际地址一致，否则 id_token 校验会失败
    yield provider, base
    server.shutdown()
    server.server_close()


def _enable_sso(admin_headers: dict[str, str], base: str, domain: str, **overrides):
    payload = {
        "enabled": True, "issuer": base, "clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET,
        "authorizationEndpoint": f"{base}/authorize", "tokenEndpoint": f"{base}/token",
        "redirectUri": "http://127.0.0.1:8100/user/sso-callback",
        "allowedDomains": [domain], "autoProvision": False, "defaultRoleCode": "auditor",
        **overrides,
    }
    response = client.put("/api/v1/settings/sso", json=payload, headers=admin_headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_sso_is_explicitly_unavailable_when_not_configured(tenant_fixture, no_ip_limit):
    discovered = client.get("/api/v1/auth/sso/discover",
                            params={"account": f"{_unique('someone')}@unconfigured.example"})
    assert discovered.status_code == 200
    assert discovered.json()["enabled"] is False
    assert "未配置" in discovered.json()["message"]

    authorize = client.post("/api/v1/auth/sso/authorize", json={"tenantId": tenant_fixture["tenantId"]})
    assert authorize.status_code == 409 and "未配置" in authorize.json()["message"]


def test_sso_config_never_echoes_the_client_secret(tenant_fixture, no_ip_limit, idp):
    provider, base = idp
    provider.email = f"sso.person@{tenant_fixture['ssoDomain']}"
    admin_headers = _headers(tenant_fixture["adminAccount"])
    saved = _enable_sso(admin_headers, base, tenant_fixture["ssoDomain"])
    assert saved["clientSecretSet"] is True and "clientSecret" not in saved

    fetched = client.get("/api/v1/settings/sso", headers=admin_headers)
    assert CLIENT_SECRET not in fetched.text
    assert fetched.json()["configured"] is True

    with SessionLocal() as db:
        stored = db.get(SsoConfig, tenant_fixture["tenantId"])
        assert stored.client_secret_encrypted and CLIENT_SECRET not in stored.client_secret_encrypted
        audits = db.scalars(select(AuditLog).where(AuditLog.tenant_id == tenant_fixture["tenantId"])).all()
        assert all(CLIENT_SECRET not in str(entry.detail) for entry in audits), "审计详情不得含密钥明文"


def test_member_cannot_read_or_write_sso_config(tenant_fixture, no_ip_limit):
    member_headers = _headers(tenant_fixture["memberAccount"])
    assert client.get("/api/v1/settings/sso", headers=member_headers).status_code == 403
    assert client.put("/api/v1/settings/sso", json={"enabled": True}, headers=member_headers).status_code == 403


def test_sso_enable_requires_complete_configuration(tenant_fixture, no_ip_limit):
    admin_headers = _headers(tenant_fixture["adminAccount"])
    response = client.put("/api/v1/settings/sso", json={"enabled": True, "issuer": "https://idp.example"},
                          headers=admin_headers)
    assert response.status_code == 422 and "必须填写" in response.json()["message"]


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    """拦住 302，好在测试里拿到回调 URL —— 浏览器里这一跳由浏览器自己走。"""

    def redirect_request(self, *_args, **_kwargs):
        return None


def _authorize_code(authorize_url: str) -> tuple[str, str]:
    # 关掉自动跟随后，urllib 把 302 当成 HTTPError 抛出；Location 就在异常头里
    try:
        location = urlrequest.build_opener(_NoRedirect).open(authorize_url, timeout=5).headers.get("Location", "")
    except urlerror.HTTPError as redirect:
        assert redirect.code == 302, f"授权端点应当 302 回调，实际 {redirect.code}"
        location = redirect.headers.get("Location", "")
    assert location, "mock IdP 未返回回调地址"
    query = parse.parse_qs(parse.urlparse(location).query)
    return (query.get("code") or [""])[0], (query.get("state") or [""])[0]


def test_sso_successful_callback_matches_existing_account(tenant_fixture, no_ip_limit, idp):
    provider, base = idp
    provider.email = f"sso.person@{tenant_fixture['ssoDomain']}"
    admin_headers = _headers(tenant_fixture["adminAccount"])
    _enable_sso(admin_headers, base, tenant_fixture["ssoDomain"])

    # 先在租户内建好与 IdP 邮箱对应的账号（autoProvision 关闭）
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.tenant_id == tenant_fixture["tenantId"],
                                            Role.code == "auditor"))
        _make_user(db, tenant_fixture["tenantId"], provider.email, role, email=provider.email)
        db.commit()

    discovered = client.get("/api/v1/auth/sso/discover",
                            params={"account": f"anyone@{tenant_fixture['ssoDomain']}"})
    assert discovered.json() == {"enabled": True, "tenantId": tenant_fixture["tenantId"],
                                 "tenantName": "账户完善测试租户", "issuer": base}

    started = client.post("/api/v1/auth/sso/authorize", json={"tenantId": tenant_fixture["tenantId"]})
    assert started.status_code == 200
    code, state = _authorize_code(started.json()["authorizeUrl"])
    assert code and state == started.json()["state"]

    callback = client.post("/api/v1/auth/sso/callback", json={"state": state, "code": code})
    assert callback.status_code == 200, callback.text
    body = callback.json()
    assert body["tenant"]["id"] == tenant_fixture["tenantId"]
    assert body["currentUser"]["email"] == provider.email
    assert "token" in body and "refreshToken" not in body

    replay = client.post("/api/v1/auth/sso/callback", json={"state": state, "code": code})
    assert replay.status_code == 400, "state 必须一次性，重放要失败"

    with SessionLocal() as db:
        actions = [entry.action for entry in db.scalars(select(AuditLog).where(
            AuditLog.tenant_id == tenant_fixture["tenantId"])).all()]
    assert "SSO 登录" in actions


def test_sso_rejects_unknown_account_when_auto_provision_is_off(tenant_fixture, no_ip_limit, idp):
    provider, base = idp
    provider.email = f"sso.person@{tenant_fixture['ssoDomain']}"
    admin_headers = _headers(tenant_fixture["adminAccount"])
    _enable_sso(admin_headers, base, tenant_fixture["ssoDomain"], autoProvision=False)

    started = client.post("/api/v1/auth/sso/authorize", json={"tenantId": tenant_fixture["tenantId"]}).json()
    code, state = _authorize_code(started["authorizeUrl"])
    response = client.post("/api/v1/auth/sso/callback", json={"state": state, "code": code})
    assert response.status_code == 403 and "尚无对应用户" in response.json()["message"]


def test_sso_first_login_can_join_when_auto_provision_is_on(tenant_fixture, no_ip_limit, idp):
    provider, base = idp
    provider.email = f"sso.person@{tenant_fixture['ssoDomain']}"
    admin_headers = _headers(tenant_fixture["adminAccount"])
    _enable_sso(admin_headers, base, tenant_fixture["ssoDomain"], autoProvision=True, defaultRoleCode="auditor")

    started = client.post("/api/v1/auth/sso/authorize", json={"tenantId": tenant_fixture["tenantId"]}).json()
    code, state = _authorize_code(started["authorizeUrl"])
    response = client.post("/api/v1/auth/sso/callback", json={"state": state, "code": code})
    assert response.status_code == 200, response.text
    assert response.json()["currentUser"]["roleCode"] == "auditor"
    assert response.json()["tenant"]["id"] == tenant_fixture["tenantId"]

    # 自动建号的账号只能走 SSO：密码登录必须失败而不是 500
    assert _login(provider.email, "any-password").status_code == 401


def test_sso_rejects_domain_outside_allowlist(tenant_fixture, no_ip_limit, idp):
    provider, base = idp
    provider.email = f"sso.person@{tenant_fixture['ssoDomain']}"
    admin_headers = _headers(tenant_fixture["adminAccount"])
    _enable_sso(admin_headers, base, tenant_fixture["ssoDomain"], autoProvision=True, allowedDomains=[f"only-this-{tenant_fixture['tenantId']}.example"])

    started = client.post("/api/v1/auth/sso/authorize", json={"tenantId": tenant_fixture["tenantId"]}).json()
    code, state = _authorize_code(started["authorizeUrl"])
    response = client.post("/api/v1/auth/sso/callback", json={"state": state, "code": code})
    assert response.status_code == 403 and "域名" in response.json()["message"]


def test_sso_domain_cannot_be_claimed_by_two_tenants(tenant_fixture, no_ip_limit, idp):
    """域名是邮箱→租户的唯一解析依据，被占用就必须拒绝，不能让登录落到错误租户。"""
    _provider, base = idp
    _enable_sso(_headers(tenant_fixture["adminAccount"]), base, tenant_fixture["ssoDomain"])

    other_tenant = _unique("tenant-rival")
    other_admin = f"{_unique('rivaladmin')}@account.test"
    with SessionLocal() as db:
        _make_tenant(db, other_tenant, "抢注域名的企业")
        role = _make_role(db, other_tenant, "admin", ADMIN_PERMISSIONS)
        _make_role(db, other_tenant, "auditor", MEMBER_PERMISSIONS)
        _make_user(db, other_tenant, other_admin, role)
        db.commit()

    response = client.put("/api/v1/settings/sso", json={
        "enabled": True, "issuer": base, "clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET,
        "authorizationEndpoint": f"{base}/authorize", "tokenEndpoint": f"{base}/token",
        "redirectUri": "http://127.0.0.1:8100/user/sso-callback",
        "allowedDomains": [tenant_fixture["ssoDomain"]],
    }, headers=_headers(other_admin))
    assert response.status_code == 409 and "占用" in response.json()["message"]

    # 解析结果仍然唯一地指向先注册的租户
    discovered = client.get("/api/v1/auth/sso/discover",
                            params={"account": f"anyone@{tenant_fixture['ssoDomain']}"})
    assert discovered.json()["tenantId"] == tenant_fixture["tenantId"]


def test_sso_rejects_forged_state(tenant_fixture, no_ip_limit, idp):
    _provider, base = idp
    _enable_sso(_headers(tenant_fixture["adminAccount"]), base, tenant_fixture["ssoDomain"])
    response = client.post("/api/v1/auth/sso/callback", json={"state": "not-a-real-state", "code": "whatever"})
    assert response.status_code == 400


def test_sso_state_is_tenant_scoped_and_expires(tenant_fixture, no_ip_limit, idp):
    _provider, base = idp
    _enable_sso(_headers(tenant_fixture["adminAccount"]), base, tenant_fixture["ssoDomain"])
    started = client.post("/api/v1/auth/sso/authorize", json={"tenantId": tenant_fixture["tenantId"]}).json()
    code, state = _authorize_code(started["authorizeUrl"])

    with SessionLocal() as db:
        record = db.get(SsoLoginState, state)
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    response = client.post("/api/v1/auth/sso/callback", json={"state": state, "code": code})
    assert response.status_code == 400 and "超时" in response.json()["message"]
