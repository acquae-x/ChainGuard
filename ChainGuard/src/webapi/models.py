from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """Keep UTC tzinfo when SQLite returns timezone columns as naive values."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str] = mapped_column(String(100), default="电子制造")
    scale: Mapped[str] = mapped_column(String(50), default="200-1000")
    status: Mapped[str] = mapped_column(String(30), default="active")
    plan: Mapped[str] = mapped_column(String(30), default="trial")
    trial_end_at: Mapped[str] = mapped_column(String(40), default="")
    demo_data_flag: Mapped[bool] = mapped_column(Boolean, default=False)


class Department(Base):
    """租户部门树。行级数据范围的 `dept`（本部门及子部门）依赖这张表求值。

    此前部门只是 /settings/departments 端点里的 5 个硬编码字符串，没有层级也不可配置，
    导致「本部门及子部门」这一档数据范围在后端根本无从计算。
    """

    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_departments_tenant_code"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    # 自引用父节点；根部门 parent_id 为空。层级深度不设限，遍历时按 tenant 内闭包展开。
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "account"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    account: Mapped[str] = mapped_column(String(160), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    dept_id: Mapped[str] = mapped_column(String(64), default="dept-1")
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"))
    role_code: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="active")
    data_scope: Mapped[str] = mapped_column(String(30), default="all")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # 账号维度防爆破：与 IP 限流互补而非互替——IP 限流挡单机高频，账号锁定挡分布式撞库。
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_failed_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # SSO 账号匹配依据；本地账号为空。租户内唯一由 sso.py 在写入前校验。
    sso_subject: Mapped[str] = mapped_column(String(255), default="")


class TenantRecord:
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ScopedRecord:
    """带行级归属的业务记录：数据范围（dept / own）按这两列求值。

    与既有的 `owner` / `assignee` 自由文本并存——那两个是展示用的姓名快照，
    权限判定只认这里的 id 外键。历史行由迁移按姓名尽力回填。

    两列皆空 = 未归属，对全租户可见（系统自动重算的风险没有天然负责人，
    藏起来比多露出来危险得多）。详细取舍见 data_scope.py 模块注释。
    """

    dept_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class OnboardingState(TenantRecord, Base):
    """Tenant-owned C3 resume state; business-data truth remains the entity tables."""

    __tablename__ = "onboarding_states"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_onboarding_states_tenant"),)
    last_step: Mapped[str] = mapped_column(String(40), default="welcome")
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Risk(ScopedRecord, TenantRecord, Base):
    __tablename__ = "risks"
    code: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[str] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(50))
    object_type: Mapped[str] = mapped_column(String(50))
    object_name: Mapped[str] = mapped_column(String(200))
    score: Mapped[float] = mapped_column(Float)
    rule: Mapped[str] = mapped_column(String(255))
    found_at: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="new")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    incident_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Incident(ScopedRecord, TenantRecord, Base):
    __tablename__ = "incidents"
    code: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(60), default="supplier_shutdown")
    level: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    owner: Mapped[str] = mapped_column(String(100), default="")
    source_risk_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    loss: Mapped[float] = mapped_column(Float, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class Proposal(ScopedRecord, TenantRecord, Base):
    __tablename__ = "proposals"
    incident_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    tag: Mapped[str] = mapped_column(String(30))
    # P0-2：未知业务指标必须落 NULL（前端显示"数据缺失"），禁止伪装成 0
    total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    lead_time_impact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    residual_risk: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_impact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    high_value_customers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    views: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    constraints: Mapped[list[Any]] = mapped_column(JSON, default=list)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    modified: Mapped[bool] = mapped_column(Boolean, default=False)
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    # P1-10：被审批引用的旧方案在重新推演时归档保留（审计追溯），列表默认不展示
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Approval(TenantRecord, Base):
    __tablename__ = "approvals"
    proposal_id: Mapped[str] = mapped_column(String(64), index=True)
    incident_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    risk_level: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(String(255))
    cost_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitter: Mapped[str] = mapped_column(String(100))
    waiting_hours: Mapped[float] = mapped_column(Float, default=0)
    cc_role_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    transferred_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    countersigned: Mapped[bool] = mapped_column(Boolean, default=False)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class Task(ScopedRecord, TenantRecord, Base):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(100))
    incident_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    assignee: Mapped[str] = mapped_column(String(100))
    role_code: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    due_at: Mapped[str] = mapped_column(String(40), default="")
    priority: Mapped[str] = mapped_column(String(20), default="中")
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class AuditLog(TenantRecord, Base):
    __tablename__ = "audit_logs"
    time: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[str] = mapped_column(String(64))
    user_name: Mapped[str] = mapped_column(String(100))
    role_code: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(50), index=True)
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    target_name: Mapped[str] = mapped_column(String(255))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")


class ExperienceCard(TenantRecord, Base):
    __tablename__ = "experience_cards"
    __table_args__ = (UniqueConstraint("tenant_id", "source_job_id", name="uq_experience_cards_tenant_source_job"),)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    source_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_incident_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_proposal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    references: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class Job(TenantRecord, Base):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(40), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(30), nullable=True)


class ImportJob(TenantRecord, Base):
    __tablename__ = "import_jobs"
    file_name: Mapped[str] = mapped_column(String(255))
    import_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ErpIntegrationConfig(TenantRecord, Base):
    """One tenant-owned ERP connection; credentials are ciphertext only."""

    __tablename__ = "erp_integration_configs"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_erp_integration_configs_tenant"),)
    base_url: Mapped[str] = mapped_column(String(500))
    credential_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    connection_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str] = mapped_column(String(30), default="not_tested")
    last_test_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    available_resources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ImportSignature(TenantRecord, Base):
    """D04 tenant-scoped, transactional duplicate-import reservation/history."""

    __tablename__ = "signature_history"
    __table_args__ = (UniqueConstraint("tenant_id", "signature", name="uq_signature_history_tenant_signature"),)
    signature: Mapped[str] = mapped_column(String(64), index=True)
    import_job_id: Mapped[str] = mapped_column(String(64), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="reserved", index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)


class ImportRejection(TenantRecord, Base):
    """Persistent row rejection ledger for imports and legacy data migration."""

    __tablename__ = "import_rejections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_record_id", "resource_type", "code",
            name="uq_import_rejections_legacy_source",
        ),
    )
    import_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), index=True)
    source_table: Mapped[str] = mapped_column(String(80))
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ImportSourceRow(TenantRecord, Base):
    """Immutable row-level source audit used for complete enterprise reconciliation."""

    __tablename__ = "import_source_rows"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "import_job_id", "source_table", "row_number",
            name="uq_import_source_rows_batch_row",
        ),
    )
    import_job_id: Mapped[str] = mapped_column(String(64), index=True)
    source_table: Mapped[str] = mapped_column(String(80), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class NotificationMessage(TenantRecord, Base):
    __tablename__ = "notification_messages"
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(255))
    target: Mapped[str] = mapped_column(String(255), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class DecisionDetail(TenantRecord, Base):
    """The full, tenant-scoped decision trace.  The orchestrator stays untouched."""
    __tablename__ = "decision_details"
    incident_id: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DecisionAudit(TenantRecord, Base):
    __tablename__ = "decision_audits"
    incident_id: Mapped[str] = mapped_column(String(64), index=True)
    decision_id: Mapped[str] = mapped_column(String(100), index=True)
    entry: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class NotificationRule(TenantRecord, Base):
    __tablename__ = "notification_rules"
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    recipient_strategy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    """Issued refresh-token registry lets password changes revoke every device."""
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordResetRequest(Base):
    """自助找回密码申请。令牌只存哈希，明文仅在可用通道上投递一次。"""
    __tablename__ = "password_reset_requests"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    # self_service：令牌已投递，用户可自助重置；manual_admin：通道未配置，等管理员兜底重置
    mode: Mapped[str] = mapped_column(String(20), default="manual_admin")
    channel: Mapped[str] = mapped_column(String(20), default="none")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_by: Mapped[str] = mapped_column(String(64), default="")
    request_ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class InvitationCode(Base):
    """企业邀请码。明文只在生成时返回一次，库内与后续接口一律只有哈希与掩码前缀。"""
    __tablename__ = "invitation_codes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_prefix: Mapped[str] = mapped_column(String(8), default="")
    role_id: Mapped[str] = mapped_column(String(64))
    role_code: Mapped[str] = mapped_column(String(40))
    dept_id: Mapped[str] = mapped_column(String(64), default="dept-1")
    data_scope: Mapped[str] = mapped_column(String(30), default="custom")
    note: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    revoked_by: Mapped[str] = mapped_column(String(64), default="")
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class InvitationRedemption(Base):
    """每次成功使用邀请码的留痕，供管理员核对"谁用这个码进了企业"。"""
    __tablename__ = "invitation_redemptions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    invitation_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    user_name: Mapped[str] = mapped_column(String(100), default="")
    role_code: Mapped[str] = mapped_column(String(40), default="")
    request_ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SsoConfig(Base):
    """租户级 OIDC 配置。client_secret 加密存储，任何读接口只回显"是否已设置"。"""
    __tablename__ = "sso_configs"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    issuer: Mapped[str] = mapped_column(String(255), default="")
    client_id: Mapped[str] = mapped_column(String(255), default="")
    client_secret_encrypted: Mapped[str] = mapped_column(Text, default="")
    authorization_endpoint: Mapped[str] = mapped_column(String(500), default="")
    token_endpoint: Mapped[str] = mapped_column(String(500), default="")
    redirect_uri: Mapped[str] = mapped_column(String(500), default="")
    scopes: Mapped[str] = mapped_column(String(200), default="openid email profile")
    email_claim: Mapped[str] = mapped_column(String(80), default="email")
    subject_claim: Mapped[str] = mapped_column(String(80), default="sub")
    allowed_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 首次登录规则：false 时只允许匹配到既有账号，杜绝 IdP 侧任意账号自动进入租户
    auto_provision: Mapped[bool] = mapped_column(Boolean, default=False)
    default_role_code: Mapped[str] = mapped_column(String(40), default="auditor")
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class SsoLoginState(Base):
    """一次性 state/nonce，防 CSRF 与 id_token 重放；回调消费后立即删除。"""
    __tablename__ = "sso_login_states"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    nonce: Mapped[str] = mapped_column(String(64))
    redirect_uri: Mapped[str] = mapped_column(String(500), default="")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CustomField(TenantRecord, Base):
    __tablename__ = "custom_fields"
    object_type: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(100))
    field_type: Mapped[str] = mapped_column(String(30), default="string")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DataRecord(TenantRecord, Base):
    __tablename__ = "data_records"
    resource_type: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5B / C2 第一批：结构化业务实体表（7 张业务表 + tenant_configs）
# 契约来源：codex_landing_spec/11_Phase5B_前置产出.md v2 §②。
# 公共列继承 TenantRecord（id/tenant_id/created_at/updated_at）并附加 extra JSON；
# 未知源列进入 extra；跨业务表关联一律带 tenant_id（tenant-aware 复合外键）。
# ─────────────────────────────────────────────────────────────────────────────


class EntityRecord(TenantRecord):
    """5B 实体表公共列：TenantRecord + extra（未映射源列落此）。"""

    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Material(EntityRecord, Base):
    __tablename__ = "materials"
    __table_args__ = (UniqueConstraint("tenant_id", "material_id", name="uq_materials_biz"),)
    material_id: Mapped[str] = mapped_column(String(64), index=True)
    material_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    daily_consumption: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)


class SupplierEntity(EntityRecord, Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", name="uq_suppliers_biz"),)
    supplier_id: Mapped[str] = mapped_column(String(64), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reliability_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class SupplierMaterial(EntityRecord, Base):
    __tablename__ = "supplier_materials"
    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "material_id", name="uq_supplier_materials_biz"),
        ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.supplier_id"], name="fk_supplier_materials_supplier"),
        ForeignKeyConstraint(["tenant_id", "material_id"], ["materials.tenant_id", "materials.material_id"], name="fk_supplier_materials_material"),
    )
    supplier_material_id: Mapped[str] = mapped_column(String(64), index=True)
    supplier_id: Mapped[str] = mapped_column(String(64))
    material_id: Mapped[str] = mapped_column(String(64))
    qualified: Mapped[bool] = mapped_column(Boolean, default=True)
    supplier_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_emergency_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    lead_time_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    emergency_cost_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    supplier_price: Mapped[float | None] = mapped_column(Float, nullable=True)


class CustomerEntity(EntityRecord, Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("tenant_id", "customer_id", name="uq_customers_biz"),)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contract: Mapped[str | None] = mapped_column(String(120), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)


class SalesOrder(EntityRecord, Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sales_order_id", name="uq_sales_orders_biz"),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.customer_id"], name="fk_sales_orders_customer"),
    )
    sales_order_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(64))
    order_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    promised_delivery_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    order_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    penalty_cost: Mapped[float | None] = mapped_column(Float, nullable=True)


class SalesOrderLine(EntityRecord, Base):
    __tablename__ = "sales_order_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sales_order_id", "line_no", name="uq_sales_order_lines_biz"),
        ForeignKeyConstraint(["tenant_id", "sales_order_id"], ["sales_orders.tenant_id", "sales_orders.sales_order_id"], name="fk_sales_order_lines_order"),
        ForeignKeyConstraint(["tenant_id", "material_id"], ["materials.tenant_id", "materials.material_id"], name="fk_sales_order_lines_material"),
    )
    sales_order_line_id: Mapped[str] = mapped_column(String(64), index=True)
    sales_order_id: Mapped[str] = mapped_column(String(64))
    line_no: Mapped[int] = mapped_column(Integer)
    material_id: Mapped[str] = mapped_column(String(64))
    ordered_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)


class InventoryEntity(EntityRecord, Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("tenant_id", "inventory_id", name="uq_inventory_biz"),
        ForeignKeyConstraint(["tenant_id", "material_id"], ["materials.tenant_id", "materials.material_id"], name="fk_inventory_material"),
    )
    inventory_id: Mapped[str] = mapped_column(String(64), index=True)
    material_id: Mapped[str] = mapped_column(String(64))
    warehouse_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    on_hand_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    available_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    safety_stock_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_transit_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_arrival_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    estimated_arrival_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class TenantConfig(EntityRecord, Base):
    __tablename__ = "tenant_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "config_type", "version", name="uq_tenant_configs_version"),
        CheckConstraint("version > 0", name="ck_tenant_configs_version_positive"),
        CheckConstraint("source IN ('expert', 'calibrated')", name="ck_tenant_configs_source"),
        # 同一 (tenant, config_type) 只能有一个 active 版本；SQLite/PostgreSQL 均支持部分唯一索引，
        # 仓储层另做事务级"先停用旧 active 再插入新 active"以避免违约（双保险）。
        Index("uq_tenant_config_active", "tenant_id", "config_type", unique=True, sqlite_where=text("is_active = 1"), postgresql_where=text("is_active")),
    )
    config_type: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(30), default="expert")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
