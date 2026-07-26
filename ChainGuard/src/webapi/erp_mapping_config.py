"""Tenant-scoped ERP field mapping configuration.

The file `config/erp_mapping.yaml` stays the shipped baseline.  A tenant may
override it from 系统设置 → 集成 → ERP; the override is stored as a versioned
`TenantConfig` row so the mapping that drove any sync stays traceable.

Hard rules enforced here:
- an override is used by the next ERP sync, or the sync fails loudly — there is
  never a silent fallback to the baseline once an override exists;
- an invalid mapping (structural, duplicate target, missing required) is
  rejected on save AND on read, with the concrete reason;
- credentials never enter the mapping payload, audit detail or sync history.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from sqlalchemy.orm import Session

from .entity_mapping import (
    ALLOWED_CONVERSIONS,
    MODEL_BY_TABLE,
    MappingValidationError,
    active_tenant_config,
    activate_tenant_config,
    load_mapping,
    validate_mapping,
)
from .errors import ApiError
from .models import TenantConfig

MAPPING_CONFIG_TYPE = "erp_field_mapping"

# Infrastructure columns are owned by the platform and are never mapping targets.
_RESERVED_COLUMNS = {"id", "tenant_id", "created_at", "updated_at", "extra"}

_RESOURCE_LABELS = {
    "material": "物料主数据",
    "supplier": "供应商主数据",
    "supplier_material": "供应商物料关系",
    "customer": "客户主数据",
    "order": "销售订单",
    "order_line": "销售订单行",
    "inventory": "实时库存",
}


def baseline_mapping() -> dict[str, Any]:
    """The shipped YAML baseline, loaded without validation so problems surface as data."""
    return load_mapping(validate=False)


def _record(db: Session, tenant_id: str) -> TenantConfig | None:
    return active_tenant_config(db, tenant_id, MAPPING_CONFIG_TYPE)


def _meta(item: TenantConfig | None) -> dict[str, Any]:
    if item is None:
        return {
            "source": "file",
            "version": None,
            "updatedAt": None,
            "updatedBy": None,
            "filePath": "config/erp_mapping.yaml",
        }
    return {
        "source": "tenant",
        "version": int(item.version),
        "updatedAt": (item.approved_at or item.updated_at).isoformat() if (item.approved_at or item.updated_at) else None,
        "updatedBy": item.approved_by,
        "filePath": "config/erp_mapping.yaml",
    }


def resolve_mapping(db: Session, tenant_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the mapping the next sync must use, plus where it came from.

    Raises instead of degrading: an unusable override or an unusable baseline is
    an operator-visible failure, never a quiet switch to the other one.
    """

    item = _record(db, tenant_id)
    spec = copy.deepcopy(item.payload) if item is not None else baseline_mapping()
    if not isinstance(spec, dict):
        raise ApiError(409, "CG-2810", "ERP 字段映射配置结构非法，请在集成设置中修复后再同步")
    problems = validate_mapping(spec)
    if problems:
        origin = f"租户映射 v{item.version}" if item is not None else "内置映射文件"
        raise ApiError(409, "CG-2810", f"{origin}校验未通过，已停止同步：{problems[0]}")
    return spec, _meta(item)


def review(spec: Mapping[str, Any]) -> dict[str, list[str]]:
    """Split mapping problems into blocking errors and dangerous-but-allowed warnings."""

    errors = validate_mapping(spec) if isinstance(spec, Mapping) else ["mapping root must be an object"]
    warnings: list[str] = []
    if not isinstance(spec, Mapping):
        return {"errors": errors, "warnings": warnings}

    baseline = baseline_mapping()
    sensitive = {str(name).casefold() for name in spec.get("sensitive_columns") or []}
    dropped = sorted(
        str(name) for name in baseline.get("sensitive_columns") or []
        if str(name).casefold() not in sensitive
    )
    if dropped:
        warnings.append(f"移除了内置敏感列保护：{dropped}，这些列将不再被强制拒绝")

    resources = spec.get("resources") if isinstance(spec.get("resources"), Mapping) else {}
    base_resources = baseline.get("resources") or {}
    for resource_type, rule in resources.items():
        if not isinstance(rule, Mapping):
            continue
        base_rule = base_resources.get(resource_type) or {}
        label = _RESOURCE_LABELS.get(str(resource_type), str(resource_type))
        fields = rule.get("fields") if isinstance(rule.get("fields"), Mapping) else {}
        converts = rule.get("converts") if isinstance(rule.get("converts"), Mapping) else {}

        mapped_sources = {str(key) for key in fields} | {
            str(item.get("from")) for item in converts.values() if isinstance(item, Mapping)
        }
        hit = sorted(name for name in mapped_sources if name.casefold() in sensitive)
        if hit:
            warnings.append(f"{label}：映射了敏感列 {hit}，命中该列的源行会被整行拒绝")

        if rule.get("unknown_columns") == "reject":
            warnings.append(f"{label}：未声明列策略为 reject，任何新增源列都会导致整行拒绝")

        base_forbidden = {str(name) for name in base_rule.get("forbidden_columns") or []}
        lost = sorted(base_forbidden - {str(name) for name in rule.get("forbidden_columns") or []})
        if lost:
            warnings.append(f"{label}：解除了禁止落入的字段 {lost}，订单头财务值可能被行级重复累计")

        base_fields = base_rule.get("fields") or {}
        base_converts = base_rule.get("converts") or {}

        def source_of(target: str, current_fields: Mapping[str, Any], current_converts: Mapping[str, Any]) -> str | None:
            for source, mapped in current_fields.items():
                if mapped == target:
                    return str(source)
            entry = current_converts.get(target)
            return str(entry.get("from")) if isinstance(entry, Mapping) and entry.get("from") else None

        for target_key in rule.get("target_key") if isinstance(rule.get("target_key"), list) else [rule.get("target_key")]:
            if not target_key:
                continue
            current = source_of(str(target_key), fields, converts)
            previous = source_of(str(target_key), base_fields, base_converts)
            if previous and current and current != previous:
                warnings.append(
                    f"{label}：业务键 {target_key} 的来源由 {previous} 改为 {current}，"
                    "历史数据将无法按原键匹配，同步会新增而非更新"
                )
    return {"errors": errors, "warnings": warnings}


def _target_columns(target_table: str) -> list[dict[str, Any]]:
    model = MODEL_BY_TABLE[target_table]
    return [
        {"name": column.name, "type": type(column.type).__name__.lower(), "nullable": bool(column.nullable)}
        for column in model.__table__.columns
        if column.name not in _RESERVED_COLUMNS
    ]


def _resource_view(resource_type: str, rule: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    fields = rule.get("fields") if isinstance(rule.get("fields"), Mapping) else {}
    converts = rule.get("converts") if isinstance(rule.get("converts"), Mapping) else {}
    required = [str(name) for name in rule.get("required") or []]
    target_keys = rule.get("target_key")
    keys = [str(name) for name in (target_keys if isinstance(target_keys, list) else [target_keys] if target_keys else [])]
    sensitive = {str(name).casefold() for name in spec.get("sensitive_columns") or []}

    rows: list[dict[str, Any]] = []
    for source, target in fields.items():
        rows.append({
            "sourceField": str(source),
            "targetField": str(target),
            "kind": "field",
            "convertType": None,
            "sourceUnit": None,
            "targetUnit": None,
            "required": str(source) in required,
            "businessKey": str(target) in keys,
            "sensitive": str(source).casefold() in sensitive,
        })
    for target, conversion in converts.items():
        entry = conversion if isinstance(conversion, Mapping) else {}
        source = str(entry.get("from") or "")
        rows.append({
            "sourceField": source,
            "targetField": str(target),
            "kind": "convert",
            "convertType": entry.get("type"),
            "sourceUnit": entry.get("source_unit"),
            "targetUnit": entry.get("target_unit"),
            "required": source in required,
            "businessKey": str(target) in keys,
            "sensitive": source.casefold() in sensitive,
        })
    rows.sort(key=lambda item: (not item["businessKey"], item["targetField"]))
    return {
        "resourceType": str(resource_type),
        "label": _RESOURCE_LABELS.get(str(resource_type), str(resource_type)),
        "sourceTable": rule.get("source_table"),
        "targetTable": rule.get("target_table"),
        "aggregation": rule.get("aggregation"),
        "unknownColumns": rule.get("unknown_columns") or spec.get("unknown_columns"),
        "forbiddenColumns": [str(name) for name in rule.get("forbidden_columns") or []],
        "requiredSources": required,
        "businessKeys": keys,
        "rows": rows,
        "targetColumns": _target_columns(str(rule.get("target_table"))) if rule.get("target_table") in MODEL_BY_TABLE else [],
    }


def mapping_view(db: Session, tenant_id: str) -> dict[str, Any]:
    """Read-side payload for the mapping editor; degradation is data, not an exception."""

    item = _record(db, tenant_id)
    meta = _meta(item)
    raw = item.payload if item is not None else baseline_mapping()
    if not isinstance(raw, dict):
        return {
            **meta,
            "usable": False,
            "degraded": True,
            "degradeReason": "映射配置结构非法（根节点不是对象），同步已停用",
            "errors": ["mapping root must be an object"],
            "warnings": [],
            "resources": [],
            "spec": {},
            "conversionTypes": sorted(ALLOWED_CONVERSIONS),
            "sensitiveColumns": [],
        }
    spec = copy.deepcopy(raw)
    verdict = review(spec)
    resources = spec.get("resources") if isinstance(spec.get("resources"), Mapping) else {}
    return {
        **meta,
        "usable": not verdict["errors"],
        "degraded": bool(verdict["errors"]),
        "degradeReason": (
            f"当前映射校验未通过，ERP 同步会被拒绝：{verdict['errors'][0]}" if verdict["errors"] else None
        ),
        "errors": verdict["errors"],
        "warnings": verdict["warnings"],
        "resources": [
            _resource_view(name, rule, spec)
            for name, rule in resources.items()
            if isinstance(rule, Mapping)
        ],
        "spec": spec,
        "conversionTypes": sorted(ALLOWED_CONVERSIONS),
        "sensitiveColumns": [str(name) for name in spec.get("sensitive_columns") or []],
    }


def save_mapping(db: Session, tenant_id: str, spec: Any, *, operator: str) -> dict[str, Any]:
    """Validate then activate a new tenant mapping version; invalid payloads never persist."""

    if not isinstance(spec, dict):
        raise ApiError(422, "CG-2811", "映射配置必须是对象")
    verdict = review(spec)
    if verdict["errors"]:
        # The editor calls :validate for the full list; the message still names the concrete blockers.
        summary = "；".join(verdict["errors"][:3])
        more = f"（共 {len(verdict['errors'])} 项）" if len(verdict["errors"]) > 3 else ""
        raise ApiError(422, "CG-2811", f"映射校验未通过，未保存{more}：{summary}")
    try:
        item = activate_tenant_config(
            db, tenant_id, MAPPING_CONFIG_TYPE, copy.deepcopy(spec),
            source="expert", approved_by=operator,
        )
    except (ValueError, MappingValidationError) as error:
        raise ApiError(422, "CG-2811", str(error)) from error
    return {**_meta(item), "warnings": verdict["warnings"]}


def reset_mapping(db: Session, tenant_id: str) -> dict[str, Any]:
    """Drop the tenant override so the shipped baseline applies again."""
    item = _record(db, tenant_id)
    if item is None:
        raise ApiError(409, "CG-2812", "当前租户没有自定义映射，无需恢复")
    item.is_active = False
    db.flush()
    return _meta(None)


__all__ = [
    "MAPPING_CONFIG_TYPE", "baseline_mapping", "mapping_view", "reset_mapping",
    "resolve_mapping", "review", "save_mapping",
]
