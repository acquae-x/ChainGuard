from __future__ import annotations

import uuid
from typing import Any
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import NotificationMessage, NotificationRule, User

FIXED_RULES: dict[str, list[str]] = {
    "decision_succeeded": ["trigger"], "decision_failed": ["trigger"],
    "approval_submitted": ["approver", "finance_if_required"], "countersign_requested": ["finance"],
    "countersign_completed": ["boss", "submitter"], "countersign_rejected": ["boss", "submitter", "scm_lead"],
    "countersign_timeout_release": ["boss", "submitter", "finance"],
    "countersign_ratified": ["boss", "submitter"],
    "task_assigned": ["assignee"], "task_urged": ["assignee"], "task_overdue": ["assignee", "scm_lead"],
    "import_succeeded": ["trigger"], "import_failed": ["trigger"], "risk_high": ["scm_lead", "boss"],
    "drift_detected": ["admin"],
    # 账户完善：通道未配置时的重置申请与账号锁定都必须让管理员看得见，否则兜底无从发起。
    "password_reset_requested": ["admin"],
    "account_locked": ["admin"],
}


def ensure_rules(db: Session, tenant_id: str) -> None:
    existing = {item.event_type: item for item in db.scalars(select(NotificationRule).where(NotificationRule.tenant_id == tenant_id)).all()}
    for event_type, recipients in FIXED_RULES.items():
        if event_type not in existing:
            db.add(NotificationRule(id=f"rule-{uuid.uuid4().hex}", tenant_id=tenant_id, event_type=event_type, recipient_strategy={"recipients": recipients, "aggregateMinutes": 5}, channels=["in_app", "webhook"], enabled=True))
        else:
            # Phase rules are fixed decisions; keep upgraded tenants aligned too.
            existing[event_type].recipient_strategy = {"recipients": recipients, "aggregateMinutes": 5}


def notify_event(db: Session, tenant_id: str, event_type: str, context: dict[str, Any]) -> int:
    """Consume the enabled rule and emit deduplicated in-app messages."""
    rule = db.scalar(select(NotificationRule).where(
        NotificationRule.tenant_id == tenant_id,
        NotificationRule.event_type == event_type,
        NotificationRule.enabled.is_(True),
    ))
    if rule is None:
        return 0
    strategy = rule.recipient_strategy if isinstance(rule.recipient_strategy, dict) else {}
    recipients = strategy.get("recipients", [])
    if not isinstance(recipients, list):
        return 0
    user_ids = _resolve_recipients(db, tenant_id, [str(item) for item in recipients], context)
    title = str(context.get("title") or event_type)
    target = str(context.get("target") or "/notifications")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(int(strategy.get("aggregateMinutes", 5) or 5), 0))
    created = 0
    for user_id in user_ids:
        duplicate = db.scalar(select(NotificationMessage).where(
            NotificationMessage.tenant_id == tenant_id,
            NotificationMessage.user_id == user_id,
            NotificationMessage.kind == event_type,
            NotificationMessage.target == target,
            NotificationMessage.created_at >= cutoff,
            NotificationMessage.read.is_(False),
        ))
        if duplicate:
            duplicate.title = title
        else:
            db.add(NotificationMessage(id=f"notification-{uuid.uuid4().hex}", tenant_id=tenant_id, user_id=user_id, kind=event_type, title=title, target=target))
            created += 1
    return created


def _resolve_recipients(db: Session, tenant_id: str, strategies: list[str], context: dict[str, Any]) -> set[str]:
    users = list(db.scalars(select(User).where(User.tenant_id == tenant_id, User.status == "active")).all())
    by_id = {item.id: item for item in users}
    resolved: set[str] = set()
    for strategy in strategies:
        if strategy in {"trigger", "assignee", "submitter"}:
            user_id = context.get(f"{strategy}_user_id")
            if user_id in by_id:
                resolved.add(user_id)
            elif strategy == "submitter":
                resolved.update(item.id for item in users if item.name == context.get("submitter"))
        elif strategy == "approver":
            role = "boss" if context.get("risk_level") == "high" else "scm_lead"
            resolved.update(item.id for item in users if item.role_code == role)
        elif strategy == "finance_if_required":
            # 成本未知（None）按保守口径通知财务，与提交时的抄送判断保持一致（P0-2）
            cost_impact = context.get("cost_impact")
            if context.get("risk_level") == "high" or (context.get("risk_level") == "medium" and (cost_impact is None or float(cost_impact or 0) > 50000)):
                resolved.update(item.id for item in users if item.role_code == "finance")
        else:
            resolved.update(item.id for item in users if item.role_code == strategy)
    return resolved
