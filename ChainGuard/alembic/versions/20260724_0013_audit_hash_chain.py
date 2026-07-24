"""Add tenant-scoped, tamper-evident hash chains to audit logs."""

import hashlib
import json
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260724_0013"
down_revision = "20260723_0012"
branch_labels = None
depends_on = None

_FORMAT = "chainguard.audit.chain.v1"


def _genesis_hash(tenant_id: str) -> str:
    return hashlib.sha256(f"{_FORMAT}|genesis|{tenant_id}".encode("utf-8")).hexdigest()


def _normalise_detail(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _entry_hash(row: dict[str, Any], previous: str) -> str:
    payload = {
        "format": _FORMAT,
        "tenant_id": row["tenant_id"],
        "time": row["time"],
        "id": row["id"],
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "role_code": row["role_code"],
        "action": row["action"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "target_name": row["target_name"],
        "detail": _normalise_detail(row["detail"]),
        "ip": row["ip"],
        "prev_hash": previous,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _backfill_existing_chains() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, tenant_id, time, user_id, user_name, role_code, action, "
        "target_type, target_id, target_name, detail, ip "
        "FROM audit_logs ORDER BY tenant_id ASC, time ASC, id ASC"
    )).mappings()

    current_tenant: str | None = None
    previous = ""
    count = 0
    for mapping in rows:
        row = dict(mapping)
        tenant_id = str(row["tenant_id"])
        if tenant_id != current_tenant:
            if current_tenant is not None:
                bind.execute(sa.text(
                    "INSERT INTO audit_chain_states (tenant_id, head_hash, entry_count) "
                    "VALUES (:tenant_id, :head_hash, :entry_count)"
                ), {"tenant_id": current_tenant, "head_hash": previous, "entry_count": count})
            current_tenant = tenant_id
            previous = _genesis_hash(tenant_id)
            count = 0

        current_hash = _entry_hash(row, previous)
        bind.execute(sa.text(
            "UPDATE audit_logs SET prev_hash = :prev_hash, entry_hash = :entry_hash WHERE id = :id"
        ), {"prev_hash": previous, "entry_hash": current_hash, "id": row["id"]})
        previous = current_hash
        count += 1

    if current_tenant is not None:
        bind.execute(sa.text(
            "INSERT INTO audit_chain_states (tenant_id, head_hash, entry_count) "
            "VALUES (:tenant_id, :head_hash, :entry_count)"
        ), {"tenant_id": current_tenant, "head_hash": previous, "entry_count": count})


def upgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(sa.Column("prev_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("entry_hash", sa.String(length=64), nullable=True))
    op.create_table(
        "audit_chain_states",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("head_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    _backfill_existing_chains()
    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column("prev_hash", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("entry_hash", existing_type=sa.String(length=64), nullable=False)


def downgrade() -> None:
    op.drop_table("audit_chain_states")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("entry_hash")
        batch.drop_column("prev_hash")
