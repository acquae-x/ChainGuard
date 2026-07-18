"""Phase 5B / C2 import execution and a frozen legacy-data backfill.

The backfill deliberately uses only SQLAlchemy Core and declarations in this
revision.  Historical Alembic revisions must not import current application
models, mapping YAML, or service code: those can drift after this revision has
shipped and would make a fresh database impossible to reproduce.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from alembic import op
import sqlalchemy as sa


revision = "20260718_0005"
down_revision = "20260717_0004"
branch_labels = None
depends_on = None


_SENSITIVE_COLUMNS = {
    "password", "secret", "token", "api_key", "credential",
    "access_key", "id_card", "ssn", "bank_account",
}

# Frozen snapshot of the v1 legacy -> entity mapping used by this revision.
# Shape: target column -> (normalized source column, conversion).
_FROZEN_RULES: dict[str, dict[str, Any]] = {
    "material": {
        "table": "materials", "keys": ("material_id",), "required": ("material_id",),
        "columns": {
            "material_id": ("material_id", "string"),
            "material_name": ("material_name", "string"),
            "category": ("category", "string"),
            "unit": ("unit", "string"),
            "daily_consumption": ("daily_consumption", "float"),
            "unit_cost": ("standard_cost", "float"),
            "is_critical": ("criticality", "bool_level"),
        },
    },
    "supplier": {
        "table": "suppliers", "keys": ("supplier_id",), "required": ("supplier_id",),
        "columns": {
            "supplier_id": ("supplier_id", "string"),
            "supplier_name": ("supplier_name", "string"),
            "region": ("region", "string"),
            "status": ("status", "string"),
            "reliability_score": ("reliability_score", "float"),
        },
    },
    "customer": {
        "table": "customers", "keys": ("customer_id",), "required": ("customer_id",),
        "columns": {
            "customer_id": ("customer_id", "string"),
            "customer_name": ("customer_name", "string"),
            "customer_level": ("customer_level", "string"),
            "region": ("region", "string"),
            "contract": ("contract", "string"),
            "owner": ("owner", "string"),
        },
    },
    "order": {
        "table": "sales_orders", "keys": ("sales_order_id",),
        "required": ("sales_order_id", "customer_id"),
        "columns": {
            "sales_order_id": ("sales_order_id", "string"),
            "customer_id": ("customer_id", "string"),
            "order_status": ("order_status", "string"),
            "promised_delivery_at": ("promised_delivery_at", "datetime"),
            "order_amount": ("order_amount", "float"),
            "gross_profit": ("gross_profit", "float"),
            "penalty_cost": ("penalty_cost", "float"),
        },
    },
    "inventory": {
        "table": "inventory", "keys": ("inventory_id",),
        "required": ("inventory_id", "material_id"),
        "columns": {
            "inventory_id": ("inventory_id", "string"),
            "material_id": ("material_id", "string"),
            "warehouse_id": ("warehouse_id", "string"),
            "warehouse_name": ("warehouse_name", "string"),
            "on_hand_qty": ("on_hand_qty", "float"),
            "available_qty": ("available_qty", "float"),
            "safety_stock_qty": ("safety_stock_qty", "float"),
        },
    },
}


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _first(payload: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = payload.get(name)
        if not _is_empty(value):
            return value
    return None


def _legacy_source(resource_type: str, name: str, raw_payload: Any) -> dict[str, Any]:
    payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else {}
    aliases: dict[str, dict[str, Any]] = {
        "material": {
            "material_id": _first(payload, "material_id", "materialId", "code"),
            "material_name": _first(payload, "material_name", "name") or name,
            "standard_cost": _first(payload, "standard_cost", "cost"),
            "daily_consumption": _first(payload, "daily_consumption", "dailyConsumption"),
            "criticality": _first(payload, "criticality", "isCritical"),
        },
        "supplier": {
            "supplier_id": _first(payload, "supplier_id", "supplierId", "code"),
            "supplier_name": _first(payload, "supplier_name", "name") or name,
            "reliability_score": _first(payload, "reliability_score", "reliabilityScore"),
        },
        "customer": {
            "customer_id": _first(payload, "customer_id", "customerId", "code"),
            "customer_name": _first(payload, "customer_name", "name") or name,
            "customer_level": _first(payload, "customer_level", "customerLevel"),
        },
        "order": {
            "sales_order_id": _first(payload, "sales_order_id", "orderNo", "code"),
            "customer_id": _first(payload, "customer_id", "customerId"),
            "promised_delivery_at": _first(payload, "promised_delivery_at", "dueAt"),
            "order_amount": _first(payload, "order_amount", "amount"),
            "gross_profit": _first(payload, "gross_profit", "profit"),
            "penalty_cost": _first(payload, "penalty_cost"),
            "order_status": _first(payload, "order_status", "status"),
        },
        "inventory": {
            "inventory_id": _first(payload, "inventory_id", "inventoryId", "code"),
            "material_id": _first(payload, "material_id", "materialId"),
            "warehouse_id": _first(payload, "warehouse_id", "warehouseId"),
            "warehouse_name": _first(payload, "warehouse_name", "warehouse"),
            "available_qty": _first(payload, "available_qty", "quantity"),
            "on_hand_qty": _first(payload, "on_hand_qty", "stock"),
            "safety_stock_qty": _first(payload, "safety_stock_qty", "safety"),
        },
    }
    return {**payload, **{key: value for key, value in aliases[resource_type].items() if value is not None}}


def _convert(value: Any, kind: str) -> Any:
    if kind == "bool_level":
        return str(value).strip().lower() in {
            "critical", "a", "high", "1", "true", "yes", "是", "关键", "核心",
        }
    if _is_empty(value):
        return None
    if kind == "string":
        return str(value)
    if kind == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if kind == "datetime":
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise RuntimeError(f"unknown frozen conversion: {kind}")


def _map_legacy_row(resource_type: str, source: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    sensitive = sorted(
        str(key) for key, value in source.items()
        if str(key).casefold() in _SENSITIVE_COLUMNS and not _is_empty(value)
    )
    if sensitive:
        return None, f"含安全敏感列，整行拒绝: {sensitive}"
    rule = _FROZEN_RULES[resource_type]
    missing = [key for key in rule["required"] if _is_empty(source.get(key))]
    if missing:
        return None, f"缺业务主键/必填字段: {missing}"
    target: dict[str, Any] = {}
    used: set[str] = set()
    for target_name, (source_name, kind) in rule["columns"].items():
        used.add(source_name)
        raw = source.get(source_name)
        converted = _convert(raw, kind)
        if not _is_empty(raw) and converted is None:
            return None, f"字段类型/格式非法: {source_name}"
        target[target_name] = converted
    target["extra"] = {key: value for key, value in source.items() if key not in used}
    return target, None


def _record_rejection(
    bind: sa.Connection,
    rejections: sa.Table,
    record: Mapping[str, Any],
    reason: str,
    source: Mapping[str, Any],
) -> None:
    identity = (
        rejections.c.tenant_id == record["tenant_id"],
        rejections.c.source_record_id == record["id"],
        rejections.c.resource_type == record["resource_type"],
        rejections.c.code == "CG-2611",
    )
    existing = bind.execute(sa.select(rejections.c.id).where(*identity)).scalar_one_or_none()
    values = {"reason": reason, "payload": dict(source), "updated_at": datetime.now(timezone.utc)}
    if existing is not None:
        bind.execute(rejections.update().where(rejections.c.id == existing).values(**values))
        return
    bind.execute(
        rejections.insert().values(
            id=f"import-rejection-{uuid.uuid4().hex}",
            tenant_id=record["tenant_id"],
            import_job_id=None,
            source_record_id=record["id"],
            resource_type=record["resource_type"],
            source_table="data_records",
            row_number=None,
            code="CG-2611",
            created_at=datetime.now(timezone.utc),
            **values,
        )
    )


def _frozen_backfill_data_records(bind: sa.Connection) -> None:
    """Backfill using only this revision's frozen Core-level contract."""

    metadata = sa.MetaData()
    data_records = sa.Table("data_records", metadata, autoload_with=bind)
    rejections = sa.Table("import_rejections", metadata, autoload_with=bind)
    tables = {
        rule["table"]: sa.Table(rule["table"], metadata, autoload_with=bind)
        for rule in _FROZEN_RULES.values()
    }
    supported = tuple(_FROZEN_RULES)
    resource_order = sa.case(
        {name: index for index, name in enumerate(supported)},
        value=data_records.c.resource_type,
        else_=len(supported),
    )
    records = bind.execute(
        sa.select(data_records)
        .where(data_records.c.resource_type.in_(supported))
        .order_by(data_records.c.tenant_id, resource_order, data_records.c.id)
    ).mappings()
    for record in records:
        resource_type = str(record["resource_type"])
        source = _legacy_source(resource_type, str(record["name"]), record["payload"])
        target, reason = _map_legacy_row(resource_type, source)
        if reason is None and target is not None and resource_type == "order":
            customers = tables["customers"]
            exists = bind.execute(
                sa.select(customers.c.id).where(
                    customers.c.tenant_id == record["tenant_id"],
                    customers.c.customer_id == target["customer_id"],
                )
            ).scalar_one_or_none()
            if exists is None:
                reason = f"非法外键（租户内不存在）: customer_id={target['customer_id']}"
        if reason is None and target is not None and resource_type == "inventory":
            materials = tables["materials"]
            exists = bind.execute(
                sa.select(materials.c.id).where(
                    materials.c.tenant_id == record["tenant_id"],
                    materials.c.material_id == target["material_id"],
                )
            ).scalar_one_or_none()
            if exists is None:
                reason = f"非法外键（租户内不存在）: material_id={target['material_id']}"
        if reason is not None or target is None:
            _record_rejection(bind, rejections, record, reason or "未知映射错误", source)
            continue

        rule = _FROZEN_RULES[resource_type]
        table = tables[rule["table"]]
        identity = [table.c.tenant_id == record["tenant_id"]]
        identity.extend(table.c[key] == target[key] for key in rule["keys"])
        existing = bind.execute(sa.select(table.c.id).where(*identity)).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing is not None:
            bind.execute(table.update().where(table.c.id == existing).values(**target, updated_at=now))
        else:
            bind.execute(
                table.insert().values(
                    id=f"{rule['table']}-{uuid.uuid4().hex}",
                    tenant_id=record["tenant_id"],
                    created_at=now,
                    updated_at=now,
                    **target,
                )
            )


def _tenant_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    # This revision includes a row-by-row ORM data migration and therefore
    # cannot produce a complete, truthful offline SQL artifact.  Fail before
    # emitting any 0005 DDL instead of crashing later on Alembic's
    # MockConnection after a partial script has already been generated.
    if op.get_context().as_sql:
        raise RuntimeError(
            "revision 20260718_0005 requires online migration mode because it "
            "backfills data_records; run `alembic upgrade 20260718_0005` against "
            "a disposable/backup-verified database"
        )

    op.create_table(
        "signature_history",
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("import_job_id", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="reserved"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        *_tenant_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "signature", name="uq_signature_history_tenant_signature"),
    )
    op.create_index("ix_signature_history_tenant_id", "signature_history", ["tenant_id"])
    op.create_index("ix_signature_history_signature", "signature_history", ["signature"])
    op.create_index("ix_signature_history_import_job_id", "signature_history", ["import_job_id"])
    op.create_index("ix_signature_history_status", "signature_history", ["status"])

    op.create_table(
        "import_rejections",
        sa.Column("import_job_id", sa.String(length=64), nullable=True),
        sa.Column("source_record_id", sa.String(length=64), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("source_table", sa.String(length=80), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_tenant_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "source_record_id", "resource_type", "code",
            name="uq_import_rejections_legacy_source",
        ),
    )
    for name in ("tenant_id", "import_job_id", "source_record_id", "resource_type"):
        op.create_index(f"ix_import_rejections_{name}", "import_rejections", [name])

    op.create_table(
        "import_source_rows",
        sa.Column("import_job_id", sa.String(length=64), nullable=False),
        sa.Column("source_table", sa.String(length=80), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_tenant_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "import_job_id", "source_table", "row_number",
            name="uq_import_source_rows_batch_row",
        ),
    )
    for name in ("tenant_id", "import_job_id", "source_table"):
        op.create_index(f"ix_import_source_rows_{name}", "import_source_rows", [name])

    # data_records remains untouched and readable.  This frozen migration-local
    # adapter performs tenant-scoped upserts and records unconvertible rows.
    _frozen_backfill_data_records(op.get_bind())


def downgrade() -> None:
    # The legacy source is never deleted or rewritten.  Downgrade only removes
    # second-batch support state; revision 0004 owns the eight entity tables.
    for name in ("source_table", "import_job_id", "tenant_id"):
        op.drop_index(f"ix_import_source_rows_{name}", table_name="import_source_rows")
    op.drop_table("import_source_rows")
    for name in ("resource_type", "source_record_id", "import_job_id", "tenant_id"):
        op.drop_index(f"ix_import_rejections_{name}", table_name="import_rejections")
    op.drop_table("import_rejections")
    for name in ("status", "import_job_id", "signature", "tenant_id"):
        op.drop_index(f"ix_signature_history_{name}", table_name="signature_history")
    op.drop_table("signature_history")
