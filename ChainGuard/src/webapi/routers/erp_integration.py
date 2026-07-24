from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.security.encryption import encryption_status

from ..auth import AuthContext, require_permission
from ..database import get_db
from ..errors import ApiError
from ..models import ImportJob
from ..erp_integration import connector_for_config, get_config as get_erp_config, public_config as public_erp_config, record_test_result, safe_erp_error, save_config as save_erp_config
from ..erp_mapping_config import mapping_view as erp_mapping_view, reset_mapping as reset_erp_mapping, resolve_mapping as resolve_erp_mapping, review as review_erp_mapping, save_mapping as save_erp_mapping
from ..enterprise_import_catalog import IMPORT_TYPE_CATALOG
from ..onboarding import activate_tenant_after_business_data
from ..repository import add_audit
from ..notifications import ensure_rules, notify_event
from ..schemas import PatchRequest
from .import_workflow import _public_job


router = APIRouter(tags=["imports-settings"])

def _erp_connector(values: dict[str, Any]):
    from src.connectors.rest_connector import RestErpConnector
    base_url = str(values.get("baseUrl") or "").strip()
    if not base_url.startswith(("http://", "https://")):
        raise ApiError(422, "CG-2610", "ERP 地址必须是 http:// 或 https:// URL")
    return RestErpConnector(base_url, api_key=str(values.get("apiKey") or ""), timeout=8.0, retries=1)


def _legacy_erp_connector(values: dict[str, Any]):
    from . import imports_settings

    return imports_settings._erp_connector(values)


@router.post("/imports/erp/test")
def test_erp_connection(body: PatchRequest, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))]):
    try:
        return _legacy_erp_connector(body.values).test_connection()
    except Exception as error:
        raise ApiError(502, "CG-2611", safe_erp_error(error)) from error


@router.post("/imports/erp/preview")
def preview_erp_import(body: PatchRequest, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))]):
    connector = _legacy_erp_connector(body.values)
    selected = body.values.get("types") or list(IMPORT_TYPE_CATALOG)
    unknown = sorted(set(selected) - set(IMPORT_TYPE_CATALOG))
    if unknown:
        raise ApiError(422, "CG-2603", f"未知资料类型：{', '.join(unknown)}")
    resources = []
    try:
        for value in selected:
            definition = IMPORT_TYPE_CATALOG[value]
            rows = connector.fetch_resource(definition["erp_resource"])
            resources.append({"type": value, "label": definition["label"], "rows": len(rows), "preview": rows[:3]})
    except Exception as error:
        raise ApiError(502, "CG-2611", safe_erp_error(error)) from error
    return {"resources": resources, "totalRows": sum(item["rows"] for item in resources), "requiresConfirmation": True}


@router.post("/imports/erp/sync", status_code=201)
def sync_erp_import(
    body: PatchRequest,
    ctx: Annotated[AuthContext, Depends(require_permission("data:import"))],
    db: Annotated[Session, Depends(get_db)],
    connector: Any | None = None,
):
    """Run an explicitly confirmed, tenant-scoped ERP sync through the shared adapter."""

    if not bool(body.values.get("confirmed")):
        raise ApiError(409, "CG-2612", "必须确认 ERP 同步范围后才能执行")
    selected = list(dict.fromkeys(body.values.get("types") or []))
    if not selected or any(value not in IMPORT_TYPE_CATALOG for value in selected):
        raise ApiError(422, "CG-2603", "请选择有效的 ERP 资料类型")
    connector = connector or _legacy_erp_connector(body.values)
    from ..entity_import import aggregate_shipments, import_audit_rows, import_entity_rows

    # Resolve before any row is fetched: an unusable mapping must stop the sync,
    # never fall back to the shipped baseline behind the operator's back.
    spec, mapping_meta = resolve_erp_mapping(db, ctx.tenant_id)
    missing = [value for value in selected if IMPORT_TYPE_CATALOG[value]["entity"] and value not in spec["resources"]]
    if missing:
        raise ApiError(409, "CG-2810", f"当前 ERP 字段映射未声明资料类型：{', '.join(missing)}")

    order = [value for value in ("material", "supplier", "customer", "supplier_material", "order", "order_line", "inventory") if value in selected]
    order += [value for value in selected if value not in order]
    job_id = f"erp-{uuid.uuid4().hex}"
    job_options = {
        "mode": "erp",
        "baseUrl": str(getattr(connector, "base_url", body.values.get("baseUrl") or "")),
        "types": selected,
        "operator": ctx.name,
        "mappingSource": mapping_meta["source"],
        "mappingVersion": mapping_meta["version"],
        "mappingUpdatedAt": mapping_meta["updatedAt"],
        "mappingUpdatedBy": mapping_meta["updatedBy"],
    }
    job = ImportJob(
        id=job_id, tenant_id=ctx.tenant_id, file_name="ERP 接口同步", import_type="erp",
        status="running", progress=10, options=job_options, result={},
    )
    db.add(job)
    reports: list[dict[str, Any]] = []
    fetched: dict[str, list[dict[str, Any]]] = {}
    try:
        for value in order:
            definition = IMPORT_TYPE_CATALOG[value]
            rows = connector.fetch_resource(definition["erp_resource"])
            fetched[value] = rows
            if definition["entity"]:
                report = import_entity_rows(db, ctx.tenant_id, job_id, rows, value, spec=spec)
            else:
                report = import_audit_rows(db, ctx.tenant_id, job_id, rows, definition["source_table"])
            reports.append({"type": value, "label": definition["label"], **report})
        if "shipment" in fetched:
            po_lines = fetched.get("purchase_order_line") or connector.fetch_resource("purchase-order-lines")
            aggregate = aggregate_shipments(db, ctx.tenant_id, job_id, fetched["shipment"], po_lines)
            next(report for report in reports if report["type"] == "shipment")["aggregation"] = aggregate
        total = sum(int(report["sourceRows"]) for report in reports)
        rejected = sum(int(report["rejectedRows"]) for report in reports)
        job.status, job.progress = "succeeded", 100
        job.result = {"total": total, "success": total - rejected, "failed": rejected, "reports": reports}
        activate_tenant_after_business_data(db, ctx.tenant_id)
        add_audit(db, ctx, "ERP 接口导入", "import", job_id, "ERP 接口同步", {
            "types": selected, "total": total,
            "mappingSource": mapping_meta["source"], "mappingVersion": mapping_meta["version"],
        })
        ensure_rules(db, ctx.tenant_id)
        notify_event(db, ctx.tenant_id, "import_succeeded", {"trigger_user_id": ctx.user_id, "title": "ERP 同步完成", "target": "/settings/integration"})
        db.commit()
        return _public_job(job)
    except Exception as error:
        db.rollback()
        failed = ImportJob(
            id=job_id, tenant_id=ctx.tenant_id, file_name="ERP 接口同步", import_type="erp",
            status="failed", progress=100, options=job_options,
            result={"total": 0, "success": 0, "failed": 0, "reports": [], "errorSummary": safe_erp_error(error)},
        )
        db.add(failed)
        ensure_rules(db, ctx.tenant_id)
        notify_event(db, ctx.tenant_id, "import_failed", {"trigger_user_id": ctx.user_id, "title": "ERP 同步失败", "target": "/settings/integration"})
        db.commit()
        raise ApiError(502, "CG-2613", safe_erp_error(error)) from error


@router.get("/settings/encryption")
def encryption_settings(ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))]):
    """凭证静态加密的只读状态。

    加密是否可用是部署级事实（依赖库 + CHAINGUARD_ENCRYPTION_KEY），不是租户数据，
    因此这里不查库、不带 tenant 维度。此前它只在 Streamlit 演示（app.py 经
    src/security/posture.py）里可见，Web 端管理员看不到——凭证保存被拒时无从判断
    是部署没配密钥还是自己填错了。

    只回状态与派生方式，绝不回任何密钥材料：encryption_status() 本身就是只读探针，
    不做加解密、不抛异常，返回值里没有密钥或密文。
    """
    return encryption_status()


@router.get("/settings/integrations/erp")
def erp_integration_settings(
    ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))],
    db: Annotated[Session, Depends(get_db)],
):
    """Return only tenant-owned, credential-masked ERP integration state."""
    return public_erp_config(get_erp_config(db, ctx.tenant_id))


@router.patch("/settings/integrations/erp")
def save_erp_integration_settings(
    body: PatchRequest,
    ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))],
    db: Annotated[Session, Depends(get_db)],
):
    item = save_erp_config(db, ctx.tenant_id, body.values)
    add_audit(db, ctx, "保存 ERP 集成配置", "erp_integration", item.id, "ERP 集成", {"baseUrl": item.base_url, "credentialConfigured": bool(item.credential_ciphertext)})
    db.commit()
    return public_erp_config(item)


@router.post("/settings/integrations/erp/test")
def test_saved_erp_integration(
    ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))],
    db: Annotated[Session, Depends(get_db)],
):
    item = get_erp_config(db, ctx.tenant_id)
    if item is None:
        raise ApiError(409, "CG-2803", "请先保存 ERP 集成配置")
    try:
        result = connector_for_config(item).test_connection()
        record_test_result(item, result=result)
        db.commit()
        return {"ok": True, **public_erp_config(item)}
    except Exception as error:
        record_test_result(item, error=error)
        db.commit()
        raise ApiError(502, "CG-2804", item.last_test_error or safe_erp_error(error)) from error


@router.post("/settings/integrations/erp/sync", status_code=201)
def sync_saved_erp_integration(
    body: PatchRequest,
    ctx: Annotated[AuthContext, Depends(require_permission("data:import"))],
    db: Annotated[Session, Depends(get_db)],
):
    item = get_erp_config(db, ctx.tenant_id)
    if item is None:
        raise ApiError(409, "CG-2803", "请先保存 ERP 集成配置")
    values = {"confirmed": True, "types": body.values.get("types") or []}
    return sync_erp_import(PatchRequest(values=values), ctx, db, connector_for_config(item))


@router.get("/settings/integrations/erp/mapping")
def get_erp_mapping(
    ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the mapping this tenant's next ERP sync will use, with its provenance."""
    return erp_mapping_view(db, ctx.tenant_id)


@router.post("/settings/integrations/erp/mapping:validate")
def validate_erp_mapping(
    body: PatchRequest,
    ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))],
):
    """Dry-run a draft mapping; blocking errors and dangerous-but-allowed warnings are separate."""
    verdict = review_erp_mapping(body.values.get("spec") if isinstance(body.values.get("spec"), dict) else body.values)
    return {"valid": not verdict["errors"], **verdict}


@router.put("/settings/integrations/erp/mapping")
def put_erp_mapping(
    body: PatchRequest,
    ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))],
    db: Annotated[Session, Depends(get_db)],
):
    spec = body.values.get("spec") if isinstance(body.values.get("spec"), dict) else body.values
    meta = save_erp_mapping(db, ctx.tenant_id, spec, operator=ctx.name)
    add_audit(db, ctx, "保存 ERP 字段映射", "erp_field_mapping", f"{ctx.tenant_id}:{meta['version']}", "ERP 字段映射", {
        "version": meta["version"], "resources": sorted((spec.get("resources") or {}).keys()),
        "warnings": meta["warnings"],
    })
    db.commit()
    return {**erp_mapping_view(db, ctx.tenant_id), "warnings": meta["warnings"]}


@router.post("/settings/integrations/erp/mapping:reset")
def reset_erp_mapping_endpoint(
    ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))],
    db: Annotated[Session, Depends(get_db)],
):
    """Deactivate the tenant override so the shipped baseline applies again."""
    reset_erp_mapping(db, ctx.tenant_id)
    add_audit(db, ctx, "恢复 ERP 内置字段映射", "erp_field_mapping", ctx.tenant_id, "ERP 字段映射", {})
    db.commit()
    return erp_mapping_view(db, ctx.tenant_id)


@router.get("/settings/integrations/erp/mapping/source-fields")
def erp_mapping_source_fields(
    ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))],
    db: Annotated[Session, Depends(get_db)],
    resource: Annotated[str, Query(min_length=1, max_length=60)],
):
    """Discover real source columns from ERP; every unavailable path names its reason."""
    if resource not in IMPORT_TYPE_CATALOG:
        raise ApiError(422, "CG-2603", "请选择有效的 ERP 资料类型")
    item = get_erp_config(db, ctx.tenant_id)
    if item is None:
        raise ApiError(409, "CG-2803", "请先保存 ERP 集成配置后再读取字段目录")
    if item.last_test_status != "available":
        raise ApiError(409, "CG-2813", "ERP 连接尚未通过测试，无法读取字段目录")
    try:
        rows = connector_for_config(item).sample_resource(IMPORT_TYPE_CATALOG[resource]["erp_resource"], limit=5)
    except Exception as error:
        raise ApiError(502, "CG-2814", safe_erp_error(error)) from error
    if not rows:
        raise ApiError(409, "CG-2814", "ERP 该资料类型没有可采样的数据，字段目录不可用")
    spec, _ = resolve_erp_mapping(db, ctx.tenant_id)
    rule = spec["resources"].get(resource) or {}
    mapped = {str(key) for key in (rule.get("fields") or {})}
    mapped |= {str(entry.get("from")) for entry in (rule.get("converts") or {}).values() if isinstance(entry, dict)}
    sensitive = {str(name).casefold() for name in spec.get("sensitive_columns") or []}
    fields: list[dict[str, Any]] = []
    for name in dict.fromkeys(key for row in rows for key in row):
        sample = next((row[name] for row in rows if row.get(name) not in (None, "")), None)
        fields.append({
            "name": str(name),
            "sample": None if str(name).casefold() in sensitive else str(sample)[:80] if sample is not None else None,
            "mapped": str(name) in mapped,
            "sensitive": str(name).casefold() in sensitive,
        })
    return {"resource": resource, "sampledRows": len(rows), "fields": fields}
