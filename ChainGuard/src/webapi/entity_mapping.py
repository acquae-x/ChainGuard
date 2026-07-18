"""Phase 5B / C2 共用映射边界（唯一映射源 adapter）。

契约来源：codex_landing_spec/11_Phase5B_前置产出.md v2 §②。
本模块是 CSV 导入与 ERP 同步（scripts/erp_sync.py 编排 + RestErpConnector 规范化）
共同消费 `config/erp_mapping.yaml` 的持久化边界：源行（dict）→ 实体表 upsert。
- 幂等：按租户内业务键 upsert，二次执行不产生重复行；
- 未知源列进入 extra；sensitive_columns 一律拒绝；
- 缺业务主键/必填的行进入拒绝清单，不猜值；
- 运输方式在边界处把外部 `road` 归一为 canonical `truck`，不在引擎内部加分支。

本批只交付映射边界与租户配置激活助手；不接线到 import router / erp_sync（属后续 C2 落表）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml
from sqlalchemy import Boolean, DateTime, Float, Integer, UniqueConstraint, func, select
from sqlalchemy.orm import Session

from .models import (
    CustomerEntity,
    DataRecord,
    ImportRejection,
    InventoryEntity,
    Material,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    TenantConfig,
    utcnow,
)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "erp_mapping.yaml"

MODEL_BY_TABLE = {
    "materials": Material,
    "suppliers": SupplierEntity,
    "supplier_materials": SupplierMaterial,
    "customers": CustomerEntity,
    "sales_orders": SalesOrder,
    "sales_order_lines": SalesOrderLine,
    "inventory": InventoryEntity,
}

REQUIRED_RULE_FIELDS = {
    "source_table", "source_key", "target_table", "target_key", "fields",
    "required", "unknown_columns", "aggregation",
}
ALLOWED_CONVERSIONS = {"string", "float", "integer", "bool", "bool_level", "datetime", "transport_mode"}


class MappingValidationError(ValueError):
    """The single mapping source is malformed and persistence must stop."""


def normalize_transport_mode(mode: Any, spec: Mapping[str, Any] | None = None) -> str | None:
    if mode is None:
        return None
    mapping = spec or load_mapping()
    transport = mapping["transport"]
    text = str(mode).strip().lower()
    normalized = str(transport.get("aliases", {}).get(text, text))
    if normalized not in set(transport["canonical_modes"]):
        raise ValueError(f"unsupported transport mode: {mode!r}")
    return normalized


def load_mapping(path: str | Path | None = None, *, validate: bool = True) -> dict[str, Any]:
    target = Path(path) if path else _CONFIG_PATH
    loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise MappingValidationError("mapping root must be an object")
    if validate:
        problems = validate_mapping(loaded)
        if problems:
            raise MappingValidationError("invalid ERP mapping: " + "; ".join(problems))
    return loaded


def validate_mapping(spec: Mapping[str, Any]) -> list[str]:
    """Return all template/model contract violations; empty means valid."""
    problems: list[str] = []
    if not isinstance(spec, Mapping):
        return ["mapping root must be an object"]
    if not isinstance(spec.get("version"), int) or int(spec["version"]) < 1:
        problems.append("version must be a positive integer")
    if spec.get("unknown_columns") not in {"extra", "reject"}:
        problems.append("unknown_columns must be 'extra' or 'reject'")
    if not isinstance(spec.get("sensitive_columns"), list) or not spec.get("sensitive_columns"):
        problems.append("sensitive_columns must be a non-empty list")
    transport = spec.get("transport")
    if not isinstance(transport, Mapping):
        problems.append("transport mapping is required")
    else:
        canonical = set(transport.get("canonical_modes") or [])
        if canonical != {"air", "truck", "rail", "sea"}:
            problems.append("transport.canonical_modes must be air/truck/rail/sea")
        aliases = transport.get("aliases")
        if not isinstance(aliases, Mapping) or aliases.get("road") != "truck":
            problems.append("transport.aliases must map road to truck")
        elif any(value not in canonical for value in aliases.values()):
            problems.append("transport alias target must be canonical")

    resources = spec.get("resources")
    if not isinstance(resources, Mapping) or not resources:
        return problems + ["no resources declared"]
    declared_tables: set[str] = set()
    for resource_type, rule in resources.items():
        if not isinstance(rule, Mapping):
            problems.append(f"{resource_type}: rule must be an object")
            continue
        missing = sorted(REQUIRED_RULE_FIELDS - set(rule))
        if missing:
            problems.append(f"{resource_type}: missing declarations {missing}")
        table = rule.get("target_table")
        if table not in MODEL_BY_TABLE:
            problems.append(f"{resource_type}: unknown target_table {table!r}")
            continue
        declared_tables.add(str(table))
        model = MODEL_BY_TABLE[str(table)]
        columns = _column_types(model)
        source_keys = _as_list(rule.get("source_key"))
        target_keys = _as_list(rule.get("target_key"))
        required = _as_list(rule.get("required"))
        fields = rule.get("fields") or {}
        converts = rule.get("converts") or {}
        if not rule.get("source_table"):
            problems.append(f"{resource_type}: source_table is empty")
        if not source_keys:
            problems.append(f"{resource_type}: source_key is empty")
        if not target_keys:
            problems.append(f"{resource_type}: target_key is empty")
        if rule.get("unknown_columns") not in {"extra", "reject"}:
            problems.append(f"{resource_type}: unknown_columns must be 'extra' or 'reject'")
        if not rule.get("aggregation"):
            problems.append(f"{resource_type}: aggregation is empty")
        if not isinstance(fields, Mapping):
            problems.append(f"{resource_type}: fields must be an object")
            fields = {}
        if not isinstance(converts, Mapping):
            problems.append(f"{resource_type}: converts must be an object")
            converts = {}
        for source_key in source_keys:
            if source_key not in required:
                problems.append(f"{resource_type}: source_key {source_key!r} must be required")
        mapped_targets = set(fields.values()) | set(converts)
        for target_key in target_keys:
            if target_key not in columns:
                problems.append(f"{resource_type}: target_key {target_key!r} is not a column of {table}")
            if target_key not in mapped_targets:
                problems.append(f"{resource_type}: target_key {target_key!r} is not mapped")
        expected_unique = ["tenant_id", *target_keys]
        has_unique = any(
            isinstance(constraint, UniqueConstraint)
            and [column.name for column in constraint.columns] == expected_unique
            for constraint in model.__table__.constraints
        )
        if target_keys and not has_unique:
            problems.append(f"{resource_type}: target_key {target_keys!r} lacks tenant business unique constraint")
        for source, target in fields.items():
            if not source:
                problems.append(f"{resource_type}: empty source field")
            if target not in columns:
                problems.append(f"{resource_type}: field target {target!r} is not a column of {table}")
        for target, conversion in converts.items():
            if target not in columns:
                problems.append(f"{resource_type}: convert target {target!r} is not a column of {table}")
            if not isinstance(conversion, Mapping) or not conversion.get("from"):
                problems.append(f"{resource_type}: convert {target!r} is missing 'from'")
                continue
            if conversion.get("type") not in ALLOWED_CONVERSIONS:
                problems.append(f"{resource_type}: convert {target!r} has unsupported type {conversion.get('type')!r}")
            if ("source_unit" in conversion) != ("target_unit" in conversion):
                problems.append(f"{resource_type}: convert {target!r} must declare both source_unit and target_unit")
            if conversion.get("scale") is not None:
                try:
                    float(conversion["scale"])
                except (TypeError, ValueError):
                    problems.append(f"{resource_type}: convert {target!r} scale must be numeric")
    missing_tables = sorted(set(MODEL_BY_TABLE) - declared_tables)
    if missing_tables:
        problems.append(f"resources missing target tables {missing_tables}")
    return problems


def _column_types(model: Any) -> dict[str, Any]:
    return {column.name: column.type for column in model.__table__.columns}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(item) for item in value] if isinstance(value, (list, tuple)) else [str(value)]


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t", "是", "真"}


def _to_bool_level(value: Any) -> bool:
    return str(value).strip().lower() in {"critical", "a", "high", "1", "true", "yes", "是", "关键", "核心"}


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce(value: Any, sqltype: Any) -> Any:
    if _is_empty(value):
        return None
    if isinstance(sqltype, Float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(sqltype, Integer):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
    if isinstance(sqltype, Boolean):
        return _to_bool(value)
    if isinstance(sqltype, DateTime):
        return _parse_dt(value)
    return str(value)


def _convert(raw: Any, conversion: Mapping[str, Any], sqltype: Any, spec: Mapping[str, Any]) -> Any:
    if _is_empty(raw) and "default" in conversion:
        raw = conversion["default"]
    kind = conversion.get("type")
    if kind == "bool":
        value: Any = _to_bool(raw)
    elif kind == "bool_level":
        value = _to_bool_level(raw)
    elif kind == "datetime":
        value = _parse_dt(raw)
    elif kind == "transport_mode":
        value = normalize_transport_mode(raw, spec)
    elif kind == "float":
        value = _coerce(raw, Float())
    elif kind == "integer":
        value = _coerce(raw, Integer())
    elif kind == "string":
        value = None if _is_empty(raw) else str(raw)
    else:
        value = _coerce(raw, sqltype)
    if value is not None and conversion.get("scale") is not None:
        value = float(value) * float(conversion["scale"])
    return value


def map_row(resource_type: str, row: Mapping[str, Any], spec: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Map one row; sensitive/invalid rows are rejected without guessing."""
    rule = spec["resources"][resource_type]
    model = MODEL_BY_TABLE[rule["target_table"]]
    columns = _column_types(model)
    sensitive = {str(column).casefold() for column in spec.get("sensitive_columns") or []}
    sensitive_found = sorted(str(key) for key, value in row.items() if str(key).casefold() in sensitive and not _is_empty(value))
    if sensitive_found:
        return None, f"含安全敏感列，整行拒绝: {sensitive_found}"
    fields: dict[str, str] = rule.get("fields") or {}
    converts: dict[str, dict] = rule.get("converts") or {}
    required: list[str] = rule.get("required") or []

    missing = [key for key in required if _is_empty(row.get(key))]
    if missing:
        return None, f"缺业务主键/必填字段: {missing}"

    forbidden = [key for key in _as_list(rule.get("forbidden_columns")) if not _is_empty(row.get(key))]
    if forbidden:
        return None, f"字段不允许落入该实体: {forbidden}"

    used_source: set[str] = set(fields.keys())
    target: dict[str, Any] = {}
    for src, tgt in fields.items():
        if tgt in columns:
            target[tgt] = _coerce(row.get(src), columns[tgt])
    for tgt, conv in converts.items():
        src = conv["from"]
        used_source.add(src)
        raw = row.get(src)
        target[tgt] = _convert(raw, conv, columns[tgt], spec)
        if not _is_empty(raw) and target[tgt] is None:
            return None, f"字段类型/格式非法: {src}"

    missing_targets = [key for key in _as_list(rule["target_key"]) if _is_empty(target.get(key))]
    if missing_targets:
        return None, f"映射后业务键为空: {missing_targets}"

    extra: dict[str, Any] = {}
    for key, value in row.items():
        if key in used_source:
            continue
        extra[key] = value
    policy = rule.get("unknown_columns", spec.get("unknown_columns"))
    if extra and policy == "reject":
        return None, f"含未声明列: {sorted(extra)}"
    target["extra"] = extra if policy == "extra" else {}
    return target, None


def _foreign_key_reason(db: Session, tenant_id: str, resource_type: str, target: Mapping[str, Any]) -> str | None:
    """Validate every entity relationship with tenant_id in the lookup."""

    requirements: dict[str, list[tuple[Any, str, str]]] = {
        "supplier_material": [
            (SupplierEntity, "supplier_id", "supplier_id"),
            (Material, "material_id", "material_id"),
        ],
        "order": [(CustomerEntity, "customer_id", "customer_id")],
        "order_line": [
            (SalesOrder, "sales_order_id", "sales_order_id"),
            (Material, "material_id", "material_id"),
        ],
        "inventory": [(Material, "material_id", "material_id")],
    }
    for model, model_key, target_key in requirements.get(resource_type, []):
        value = target.get(target_key)
        exists = db.scalar(
            select(model.id).where(model.tenant_id == tenant_id, getattr(model, model_key) == value)
        )
        if exists is None:
            return f"非法外键（租户内不存在）: {target_key}={value}"
    return None


def upsert_entities(db: Session, tenant_id: str, resource_type: str, rows: Iterable[Mapping[str, Any]], spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """按租户内业务键幂等 upsert；返回 {inserted, updated, rejected:[{row,reason,source}]}。"""
    spec = spec or load_mapping()
    problems = validate_mapping(spec)
    if problems:
        raise MappingValidationError("invalid ERP mapping: " + "; ".join(problems))
    if resource_type not in spec["resources"]:
        raise KeyError(f"unknown resource_type: {resource_type}")
    rule = spec["resources"][resource_type]
    model = MODEL_BY_TABLE[rule["target_table"]]
    business_keys = _as_list(rule["target_key"])
    inserted = updated = 0
    rejected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        target, reason = map_row(resource_type, row, spec)
        if reason:
            rejected.append({"row": index, "reason": reason, "source": row})
            continue
        assert target is not None
        fk_reason = _foreign_key_reason(db, tenant_id, resource_type, target)
        if fk_reason:
            rejected.append({"row": index, "reason": fk_reason, "source": row})
            continue
        filters = [model.tenant_id == tenant_id] + [getattr(model, key) == target[key] for key in business_keys]
        existing = db.scalar(select(model).where(*filters))
        if existing is not None:
            for column, value in target.items():
                setattr(existing, column, value)
            updated += 1
        else:
            db.add(model(id=f"{rule['target_table']}-{uuid.uuid4().hex}", tenant_id=tenant_id, **target))
            inserted += 1
    db.flush()
    return {"inserted": inserted, "updated": updated, "rejected": rejected}


def persist_rejection(
    db: Session,
    tenant_id: str,
    resource_type: str,
    source_table: str,
    reason: str,
    payload: Mapping[str, Any],
    *,
    code: str = "CG-2610",
    import_job_id: str | None = None,
    source_record_id: str | None = None,
    row_number: int | None = None,
) -> ImportRejection:
    """Persist one rejection; legacy source rows are idempotent across reruns."""

    existing = None
    if source_record_id is not None:
        existing = db.scalar(
            select(ImportRejection).where(
                ImportRejection.tenant_id == tenant_id,
                ImportRejection.source_record_id == source_record_id,
                ImportRejection.resource_type == resource_type,
                ImportRejection.code == code,
            )
        )
    if existing is not None:
        existing.reason = reason
        existing.payload = dict(payload)
        existing.row_number = row_number
        return existing
    item = ImportRejection(
        id=f"import-rejection-{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        import_job_id=import_job_id,
        source_record_id=source_record_id,
        resource_type=resource_type,
        source_table=source_table,
        row_number=row_number,
        code=code,
        reason=reason,
        payload=dict(payload),
    )
    db.add(item)
    return item


def _legacy_source_row(item: DataRecord) -> dict[str, Any]:
    """Adapt the old product-row JSON shape into the shared YAML source shape."""

    payload = dict(item.payload or {})
    name = item.name
    aliases: dict[str, dict[str, Any]] = {
        "material": {
            "material_id": payload.get("material_id") or payload.get("materialId") or payload.get("code"),
            "material_name": payload.get("material_name") or payload.get("name") or name,
            "standard_cost": payload.get("standard_cost", payload.get("cost")),
            "daily_consumption": payload.get("daily_consumption", payload.get("dailyConsumption")),
            "criticality": payload.get("criticality", payload.get("isCritical")),
        },
        "supplier": {
            "supplier_id": payload.get("supplier_id") or payload.get("supplierId") or payload.get("code"),
            "supplier_name": payload.get("supplier_name") or payload.get("name") or name,
            "reliability_score": payload.get("reliability_score", payload.get("reliabilityScore")),
        },
        "customer": {
            "customer_id": payload.get("customer_id") or payload.get("customerId") or payload.get("code"),
            "customer_name": payload.get("customer_name") or payload.get("name") or name,
            "customer_level": payload.get("customer_level", payload.get("customerLevel")),
        },
        "order": {
            "sales_order_id": payload.get("sales_order_id") or payload.get("orderNo") or payload.get("code"),
            "customer_id": payload.get("customer_id") or payload.get("customerId"),
            "promised_delivery_at": payload.get("promised_delivery_at", payload.get("dueAt")),
            "order_amount": payload.get("order_amount", payload.get("amount")),
            "gross_profit": payload.get("gross_profit", payload.get("profit")),
            "order_status": payload.get("order_status", payload.get("status")),
        },
        "inventory": {
            "inventory_id": payload.get("inventory_id") or payload.get("inventoryId") or payload.get("code"),
            "material_id": payload.get("material_id") or payload.get("materialId"),
            "warehouse_id": payload.get("warehouse_id") or payload.get("warehouseId"),
            "warehouse_name": payload.get("warehouse_name") or payload.get("warehouse"),
            "available_qty": payload.get("available_qty", payload.get("quantity")),
            "on_hand_qty": payload.get("on_hand_qty", payload.get("stock")),
            "safety_stock_qty": payload.get("safety_stock_qty", payload.get("safety")),
        },
    }
    source = {**payload, **{key: value for key, value in aliases[item.resource_type].items() if value is not None}}
    return source


def migrate_data_records(db: Session, tenant_id: str | None = None) -> dict[str, Any]:
    """Idempotently migrate legacy data_records without deleting or mutating them."""

    supported = ("material", "supplier", "customer", "order", "inventory")
    query = select(DataRecord).where(DataRecord.resource_type.in_(supported))
    if tenant_id is not None:
        query = query.where(DataRecord.tenant_id == tenant_id)
    records = list(db.scalars(query.order_by(DataRecord.tenant_id, DataRecord.resource_type, DataRecord.id)))
    # Parents must be available before tenant-aware children.
    order = {name: index for index, name in enumerate(supported)}
    records.sort(key=lambda item: (item.tenant_id, order[item.resource_type], item.id))
    summary = {"source": len(records), "inserted": 0, "updated": 0, "rejected": 0}
    spec = load_mapping()
    for item in records:
        source = _legacy_source_row(item)
        result = upsert_entities(db, item.tenant_id, item.resource_type, [source], spec)
        summary["inserted"] += result["inserted"]
        summary["updated"] += result["updated"]
        for rejection in result["rejected"]:
            persist_rejection(
                db,
                item.tenant_id,
                item.resource_type,
                "data_records",
                rejection["reason"],
                source,
                code="CG-2611",
                source_record_id=item.id,
            )
            summary["rejected"] += 1
    db.flush()
    return summary


def normalize_transport_options(payload: Any, spec: Mapping[str, Any] | None = None) -> Any:
    """Preserve payload shape while enforcing canonical mode and multiplier."""
    mapping = spec or load_mapping()
    if isinstance(payload, list):
        options = payload
        wrapper: dict[str, Any] | None = None
    elif isinstance(payload, dict) and isinstance(payload.get("options"), list):
        wrapper = dict(payload)
        options = payload["options"]
    else:
        raise ValueError("transport_options payload must be a list or {'options': [...]} object")
    normalized_options: list[dict[str, Any]] = []
    for index, raw in enumerate(options):
        if not isinstance(raw, Mapping):
            raise ValueError(f"transport option {index} must be an object")
        option = dict(raw)
        option["mode"] = normalize_transport_mode(option.get("mode"), mapping)
        if _is_empty(option.get("cost_multiplier")):
            raise ValueError(f"transport option {index} missing cost_multiplier")
        try:
            option["cost_multiplier"] = float(option["cost_multiplier"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"transport option {index} cost_multiplier must be numeric") from exc
        if option["cost_multiplier"] <= 0:
            raise ValueError(f"transport option {index} cost_multiplier must be positive")
        if not _is_empty(option.get("estimated_hours")):
            option["estimated_hours"] = float(option["estimated_hours"])
        normalized_options.append(option)
    if wrapper is None:
        return normalized_options
    wrapper["options"] = normalized_options
    return wrapper


def activate_tenant_config(db: Session, tenant_id: str, config_type: str, payload: dict[str, Any] | list[Any], *, source: str = "calibrated", approved_by: str | None = None, version: int | None = None) -> TenantConfig:
    """事务级"先停用旧 active 再插入新 active"，保证同一 (tenant, config_type) 单 active。"""
    if source not in {"expert", "calibrated"}:
        raise ValueError("tenant config source must be expert or calibrated")
    if config_type == "transport_options":
        payload = normalize_transport_options(payload)
    current = db.scalar(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id, TenantConfig.config_type == config_type, TenantConfig.is_active.is_(True)))
    if version is None:
        max_version = db.scalar(select(func.max(TenantConfig.version)).where(TenantConfig.tenant_id == tenant_id, TenantConfig.config_type == config_type)) or 0
        version = int(max_version) + 1
    if version <= 0:
        raise ValueError("tenant config version must be positive")
    if current is not None:
        current.is_active = False
        db.flush()  # 先落停用，避免部分唯一索引 (tenant_id, config_type) WHERE is_active 冲突
    config = TenantConfig(
        id=f"tenant-config-{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        config_type=config_type,
        payload=payload,
        version=version,
        source=source,
        is_active=True,
        approved_by=approved_by,
        approved_at=utcnow() if approved_by else None,
    )
    db.add(config)
    db.flush()
    return config


def active_tenant_config(db: Session, tenant_id: str, config_type: str) -> TenantConfig | None:
    return db.scalar(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id, TenantConfig.config_type == config_type, TenantConfig.is_active.is_(True)))


def entity_to_product_row(resource_type: str, entity: Any, *, related: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Map entity names to the five existing product-page column contracts.

    This pure adapter is for the later repository switch; this batch does not
    change the current ``/data`` API read source.
    """
    related = related or {}

    def value(item: Any, name: str, default: Any = None) -> Any:
        if item is None:
            return default
        return item.get(name, default) if isinstance(item, Mapping) else getattr(item, name, default)

    if resource_type == "material":
        inventory = list(related.get("inventory") or [])
        return {
            "id": value(entity, "material_id"),
            "name": value(entity, "material_name"),
            "category": value(entity, "category"),
            "stock": sum(float(value(row, "on_hand_qty", 0) or 0) for row in inventory),
            "safety": sum(float(value(row, "safety_stock_qty", 0) or 0) for row in inventory),
            "cost": value(entity, "unit_cost"),
        }
    if resource_type == "supplier":
        relations = list(related.get("supplier_materials") or [])

        def relation_key(item: Any) -> tuple[Any, ...]:
            """Choose a deterministic list-page primary supply relationship.

            Qualified relationships win, then the lowest explicit supplier rank,
            followed by tenant-local business keys.  The final key prevents the
            database's unspecified row order from affecting the product page.
            """

            rank = value(item, "supplier_rank")
            try:
                normalized_rank = int(rank) if rank is not None else 2**31 - 1
            except (TypeError, ValueError):
                normalized_rank = 2**31 - 1
            return (
                0 if bool(value(item, "qualified", False)) else 1,
                normalized_rank,
                str(value(item, "material_id") or ""),
                str(value(item, "supplier_material_id") or ""),
            )

        relations.sort(key=relation_key)
        relation = relations[0] if relations else None
        lead_hours = value(relation, "lead_time_hours")
        material_names = related.get("material_names") or {}
        return {
            "id": value(entity, "supplier_id"),
            "name": value(entity, "supplier_name"),
            "status": value(entity, "status"),
            "leadTime": None if lead_hours is None else float(lead_hours) / 24.0,
            "supplierPrice": value(relation, "supplier_price"),
            "relations": [
                {
                    "supplierMaterialId": value(item, "supplier_material_id"),
                    "materialId": value(item, "material_id"),
                    "materialName": material_names.get(value(item, "material_id")),
                    "supplierRank": value(item, "supplier_rank"),
                    "leadTimeHours": value(item, "lead_time_hours"),
                    "supplierPrice": value(item, "supplier_price"),
                    "availableEmergencyQty": value(item, "available_emergency_qty"),
                    "qualified": value(item, "qualified"),
                    "isDefault": index == 0,
                }
                for index, item in enumerate(relations)
            ],
        }
    if resource_type == "customer":
        return {
            "id": value(entity, "customer_id"),
            "name": value(entity, "customer_name"),
            "customerLevel": value(entity, "customer_level"),
            "contract": value(entity, "contract"),
            "owner": value(entity, "owner"),
        }
    if resource_type == "order":
        customer = related.get("customer")
        return {
            "id": value(entity, "sales_order_id"),
            "orderNo": value(entity, "sales_order_id"),
            "customer": value(customer, "customer_name", value(entity, "customer_id")),
            "dueAt": value(entity, "promised_delivery_at"),
            "amount": value(entity, "order_amount"),
            "profit": value(entity, "gross_profit"),
            "status": value(entity, "order_status"),
        }
    if resource_type == "inventory":
        material = related.get("material")
        daily = value(material, "daily_consumption")
        available = value(entity, "available_qty")
        support_hours = None
        if daily is not None and float(daily) > 0 and available is not None:
            support_hours = float(available) / (float(daily) / 24.0)
        return {
            "id": value(entity, "inventory_id"),
            "warehouse": value(entity, "warehouse_name") or value(entity, "warehouse_id"),
            "material": value(material, "material_name") or value(entity, "material_id"),
            "quantity": available,
            "supportHours": support_hours,
            "status": related.get("status"),
        }
    raise KeyError(f"unsupported product resource_type: {resource_type}")
