from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditChainState, AuditLog


CHAIN_FORMAT_VERSION = "chainguard.audit.chain.v1"


def genesis_hash(tenant_id: str) -> str:
    """Return a tenant-scoped, domain-separated first-link value."""
    return hashlib.sha256(
        f"{CHAIN_FORMAT_VERSION}|genesis|{tenant_id}".encode("utf-8")
    ).hexdigest()


def _normalise_detail(value: Any) -> Any:
    """Make SQL JSON values and Python JSON values hash to the same payload."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _payload(log: AuditLog, prev_hash: str) -> dict[str, Any]:
    return {
        "format": CHAIN_FORMAT_VERSION,
        "tenant_id": log.tenant_id,
        "time": log.time,
        "id": log.id,
        "user_id": log.user_id,
        "user_name": log.user_name,
        "role_code": log.role_code,
        "action": log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "target_name": log.target_name,
        "detail": _normalise_detail(log.detail),
        "ip": log.ip,
        "prev_hash": prev_hash,
    }


def entry_hash(log: AuditLog, prev_hash: str) -> str:
    encoded = json.dumps(
        _payload(log, prev_hash), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AuditChainVerification:
    tenant_id: str
    valid: bool
    checked_entries: int
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenantId": self.tenant_id,
            "valid": self.valid,
            "checkedEntries": self.checked_entries,
            "errors": list(self.errors),
        }


def append_to_chain(db: Session, log: AuditLog) -> AuditLog:
    """Attach an audit row to its tenant's chain inside the caller transaction."""
    state = db.get(AuditChainState, log.tenant_id, with_for_update=True)
    if state is None:
        existing = db.scalar(
            select(AuditLog.id).where(AuditLog.tenant_id == log.tenant_id).limit(1)
        )
        if existing is not None:
            raise RuntimeError("audit chain state is missing for an existing tenant log")
        state = AuditChainState(
            tenant_id=log.tenant_id,
            head_hash=genesis_hash(log.tenant_id),
            entry_count=0,
        )
        db.add(state)

    log.prev_hash = state.head_hash
    log.entry_hash = entry_hash(log, log.prev_hash)
    state.head_hash = log.entry_hash
    state.entry_count += 1
    db.add(log)
    return log


def verify_audit_chain(db: Session, tenant_id: str) -> AuditChainVerification:
    """Verify field integrity, linkage, and the per-tenant chain anchor."""
    errors: list[str] = []
    state = db.get(AuditChainState, tenant_id)
    logs = list(db.scalars(select(AuditLog).where(AuditLog.tenant_id == tenant_id)))
    if state is None:
        if logs:
            errors.append("missing_chain_state")
        return AuditChainVerification(tenant_id, not errors, len(logs), tuple(errors))

    expected_genesis = genesis_hash(tenant_id)
    if state.entry_count < 0:
        errors.append("negative_entry_count")
    if state.entry_count != len(logs):
        errors.append("entry_count_mismatch")

    by_previous: dict[str, AuditLog] = {}
    for log in logs:
        if log.tenant_id != tenant_id:
            errors.append(f"tenant_mismatch:{log.id}")
        if entry_hash(log, log.prev_hash) != log.entry_hash:
            errors.append(f"entry_hash_mismatch:{log.id}")
        if log.prev_hash in by_previous:
            errors.append(f"forked_previous_hash:{log.prev_hash}")
        else:
            by_previous[log.prev_hash] = log

    visited: set[str] = set()
    current_hash = expected_genesis
    while current_hash in by_previous:
        log = by_previous[current_hash]
        if log.id in visited:
            errors.append(f"cycle:{log.id}")
            break
        visited.add(log.id)
        current_hash = log.entry_hash

    if len(visited) != len(logs):
        errors.append("broken_or_orphaned_link")
    if state.head_hash != current_hash:
        errors.append("head_hash_mismatch")
    if not logs and state.head_hash != expected_genesis:
        errors.append("empty_chain_head_mismatch")

    return AuditChainVerification(tenant_id, not errors, len(logs), tuple(errors))
