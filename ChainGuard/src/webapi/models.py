from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


class TenantRecord:
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Risk(TenantRecord, Base):
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


class Incident(TenantRecord, Base):
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


class Proposal(TenantRecord, Base):
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


class Task(TenantRecord, Base):
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
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending")


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
