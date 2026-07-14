from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
import csv
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.orm import Session

from ..auth import AuthContext, can_view_data, get_current_user, require_permission
from ..config import settings
from ..database import get_db
from ..errors import ApiError
from ..models import CustomField, DataRecord, ImportJob, Role, Tenant, User
from ..jobs import enqueue_import_job
from ..repository import add_audit, get_tenant_record, list_tenant_records, serialize
from ..schemas import PatchRequest


router = APIRouter(tags=["imports-settings"])


def _camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


def camelize_report(report: Any) -> dict[str, Any]:
    """P1-4：preflight 结果统一转 camelCase，与前端 estimatedRows/canProceed 契约对齐。"""
    data = asdict(report) if hasattr(report, "__dataclass_fields__") else dict(report)
    return {_camel(key): value for key, value in data.items()}


def normalize_xlsx_to_csv(source: str | Path) -> Path:
    """P1-4：XLSX 先解析归一化为 CSV，预检必须基于真实行而不是二进制字节估算。

    解析失败必须抛出异常（由调用方转红灯），不允许吞异常后继续绿灯。
    """
    from openpyxl import load_workbook

    path = Path(source)
    sheet = load_workbook(path, read_only=True, data_only=True).active
    values = sheet.iter_rows(values_only=True)
    headers = [str(value or "").strip() for value in next(values, ())]
    if not any(headers):
        raise ValueError("XLSX 首行没有可用表头")
    target = path.with_suffix(".csv")
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in values:
            writer.writerow(["" if value is None else value for value in row[: len(headers)]])
    return target


def normalized_preview(path: str | Path, limit: int = 20) -> dict[str, Any]:
    """Return a bounded, structured preview of the server-side normalized file."""
    source = Path(path)
    rows: list[dict[str, Any]] = []
    if source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if len(rows) < limit:
                    rows.append(dict(row))
                else:
                    break
    elif source.suffix.lower() == ".xlsx":
        try:
            from openpyxl import load_workbook
            sheet = load_workbook(source, read_only=True, data_only=True).active
            values = sheet.iter_rows(values_only=True)
            headers = [str(value or "").strip() for value in next(values, ())]
            for values_row in values:
                if len(rows) >= limit:
                    break
                rows.append({headers[index]: value for index, value in enumerate(values_row) if index < len(headers) and headers[index]})
        except Exception:
            rows = []
    return {"table": source.stem, "previewRows": rows, "previewLimit": limit}


@router.post("/imports/upload", status_code=201)
async def upload_import(file: UploadFile, import_type: str = Query(..., alias="type"), ctx: Annotated[AuthContext, Depends(require_permission("data:import"))] = None, db: Annotated[Session, Depends(get_db)] = None):
    job_id = f"import-{uuid.uuid4().hex}"
    safe_name = Path(file.filename or "upload.csv").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg"}:
        raise ApiError(422, "CG-2603", "仅支持 csv、xlsx、pdf、png、jpg 或 jpeg 文件")
    directory = Path(".workspace") / "imports" / ctx.tenant_id / job_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / safe_name
    size = 0
    with path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_import_bytes:
                output.close()
                path.unlink(missing_ok=True)
                directory.rmdir()
                raise ApiError(413, "CG-2604", "上传文件超过大小限制")
            output.write(chunk)
    job = ImportJob(id=job_id, tenant_id=ctx.tenant_id, file_name=safe_name, import_type=import_type, status="uploaded", progress=0, options={"size": size, "path": str(path.resolve())}, result={})
    db.add(job); add_audit(db, ctx, "上传导入", "import", job.id, job.file_name, {"type": import_type, "size": size}); db.commit()
    payload = serialize(job); payload["options"].pop("path", None); return payload


@router.post("/imports/{item_id}/preflight")
def preflight(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    from src.import_preflight import run_preflight
    item = get_tenant_record(db, ImportJob, item_id, ctx.tenant_id)
    suffix = Path(item.file_name).suffix.lower()
    if suffix in {".pdf", ".png", ".jpg", ".jpeg"}:
        from src.ingestion_agent import ingest_files
        intake = ingest_files([item.options["path"]])
        extraction = intake.extractions[0]
        if extraction.needs_manual:
            item.status, item.progress = "manual_required", 25
            item.result = {"canProceed": False, "status": "manual_required", "message": "待人工处理：未配置可用的 OCR/视觉提取能力，原始文件已保留在 staging。", "extraction": asdict(extraction)}
            db.commit(); payload = serialize(item); payload["options"].pop("path", None); return payload
        rows = next(iter(intake.normalized.values()), [])
        normalized_path = Path(item.options["path"]).parent / "normalized.csv"
        with normalized_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader(); writer.writerows(rows)
        item.options = {**item.options, "originalPath": item.options["path"], "path": str(normalized_path.resolve()), "extraction": asdict(extraction)}
    elif suffix == ".xlsx":
        # P1-4：XLSX 先归一化为 CSV 再做基于行的容量预检；解析失败必须红灯，禁止吞异常假绿灯
        try:
            normalized_path = normalize_xlsx_to_csv(item.options["path"])
        except Exception:
            item.status, item.progress = "failed", 25
            item.result = {
                "canProceed": False,
                "verdict": "PARSE_ERROR",
                "estimatedRows": None,
                "messages": ["XLSX 解析失败：文件可能损坏或不是有效的 Excel 工作簿，导入已阻止。"],
                "normalized": {"table": Path(item.file_name).stem, "previewRows": [], "previewLimit": 20},
            }
            db.commit(); payload = serialize(item); payload["options"].pop("path", None); return payload
        item.options = {**item.options, "originalPath": item.options["path"], "path": str(normalized_path.resolve())}
    report = run_preflight([item.options["path"]], Path(item.options["path"]).parent / "import.db")
    item.status = "preflighted" if report.can_proceed else "failed"
    item.progress = 25
    # camelCase 与前端 estimatedRows/canProceed 契约对齐（P1-4）；verdict 键名不变，confirm 闸门不受影响
    item.result = {**camelize_report(report), "normalized": normalized_preview(item.options["path"])}
    db.commit()
    payload = serialize(item); payload["options"].pop("path", None); return payload


@router.post("/imports/{item_id}/confirm")
def confirm_import(item_id: str, body: PatchRequest, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, ImportJob, item_id, ctx.tenant_id)
    force = bool(body.values.get("force"))
    if item.status == "failed":
        # Disk shortage is a hard safety gate, not an override-able quality warning.
        if item.result.get("verdict") == "INSUFFICIENT_DISK":
            raise ApiError(409, "CG-2602", "磁盘空间不足，不能强制导入")
        # P1-4：解析失败没有可导入的归一化数据，同样不允许强制
        if item.result.get("verdict") == "PARSE_ERROR":
            raise ApiError(409, "CG-2602", "文件解析失败，不能强制导入")
        if not force:
            raise ApiError(409, "CG-2602", "预检未通过，需明确确认后才能继续导入")
    if item.status not in {"preflighted", "failed"}:
        raise ApiError(409, "CG-2601", "导入任务尚未完成预检")
    item.status = "confirmed"; item.options = {**item.options, **body.values}; item.progress = 50; db.commit()
    payload = serialize(item); payload["options"].pop("path", None); return payload


@router.post("/imports/{item_id}/execute", status_code=202)
def execute_import(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, ImportJob, item_id, ctx.tenant_id)
    if item.status != "confirmed":
        from ..errors import ApiError
        raise ApiError(409, "CG-2601", "导入任务尚未确认")
    item.status = "pending"; db.commit(); enqueue_import_job(item.id, ctx); return {"jobId": item.id, "status": item.status}


@router.get("/imports/{item_id}")
def import_progress(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, ImportJob, item_id, ctx.tenant_id); payload = serialize(item); payload["options"].pop("path", None); return payload
@router.get("/imports")
def import_history(ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    data = []
    for item in list_tenant_records(db, ImportJob, ctx.tenant_id):
        payload = serialize(item); payload["options"].pop("path", None); data.append(payload)
    return {"data": data}
@router.post("/imports/{item_id}/rollback")
def rollback_import(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]): item = get_tenant_record(db, ImportJob, item_id, ctx.tenant_id); item.status = "rolled_back"; db.commit(); return {"ok": True, "id": item_id}


@router.get("/settings/users")
def users(ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    items = list_tenant_records(db, User, ctx.tenant_id)
    return {"data": [{**serialize(x, include={"account"}), "roleIds": [x.role_id]} for x in items], "total": len(items), "success": True}


@router.post("/settings/users", status_code=201)
def create_user(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    from ..auth.security import hash_password
    role = get_tenant_record(db, Role, body["roleId"], ctx.tenant_id)
    item = User(id=f"u-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, account=str(body.get("account") or body.get("phone") or body.get("email")).lower(), password_hash=hash_password(str(body.get("password") or uuid.uuid4().hex)), name=body["name"], phone=body.get("phone", ""), email=body.get("email", ""), dept_id=body.get("deptId", "dept-1"), role_id=role.id, role_code=role.code, status=body.get("status", "active"), data_scope=body.get("dataScope", "custom")); db.add(item); add_audit(db, ctx, "创建用户", "user", item.id, item.name, {"roleCode": role.code}); db.commit(); return {"ok": True, "id": item.id}


@router.patch("/settings/users/{item_id}")
def update_user(item_id: str, body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, User, item_id, ctx.tenant_id)
    before = {"name": item.name, "status": item.status, "roleCode": item.role_code}
    for field in ("name", "phone", "email", "status"):
        if field in body: setattr(item, field, body[field])
    if "dataScope" in body: item.data_scope = body["dataScope"]
    if "roleId" in body:
        role = get_tenant_record(db, Role, body["roleId"], ctx.tenant_id); item.role_id = role.id; item.role_code = role.code
    add_audit(db, ctx, "更新用户", "user", item.id, item.name, {"before": before, "after": body}); db.commit(); return {"ok": True, "id": item.id}


@router.post("/settings/users/{item_id}/reset-password")
def reset_user_password(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    from ..auth.security import hash_password, revoke_refresh_tokens
    import secrets
    item = get_tenant_record(db, User, item_id, ctx.tenant_id)
    temporary_password = f"Cg!{secrets.token_urlsafe(9)}"
    item.password_hash, item.must_change_password = hash_password(temporary_password), True
    revoke_refresh_tokens(db, item)
    add_audit(db, ctx, "重置密码", "user", item.id, item.name, {"mustChangePassword": True})
    db.commit()
    return {"ok": True, "temporaryPassword": temporary_password, "mustChangePassword": True}


@router.delete("/settings/users/{item_id}", status_code=204)
def disable_user(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, User, item_id, ctx.tenant_id); item.status = "disabled"; add_audit(db, ctx, "停用用户", "user", item.id, item.name, {}); db.commit()


@router.get("/settings/roles")
def roles(ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]): return [serialize(x) for x in list_tenant_records(db, Role, ctx.tenant_id)]
@router.post("/settings/roles", status_code=201)
def save_role(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = Role(id=body.get("id") or f"role-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, code=body["code"], name=body["name"], builtin=False, permissions=body.get("permissions", [])); db.merge(item); add_audit(db, ctx, "保存角色", "role", item.id, item.name, {"permissions": item.permissions}); db.commit(); return {"ok": True, "id": item.id}
@router.patch("/settings/roles/{item_id}")
def update_role(item_id: str, body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, Role, item_id, ctx.tenant_id)
    if item.builtin:
        from ..errors import ApiError
        raise ApiError(409, "CG-2701", "内置角色不可修改，请复制后编辑")
    if "name" in body: item.name = body["name"]
    if "permissions" in body: item.permissions = body["permissions"]
    add_audit(db, ctx, "更新角色", "role", item.id, item.name, body); db.commit(); return {"ok": True, "id": item.id}
@router.delete("/settings/roles/{item_id}", status_code=204)
def delete_role(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]): item = get_tenant_record(db, Role, item_id, ctx.tenant_id); db.delete(item); db.commit()


@router.get("/settings/tenant")
def tenant(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): return serialize(db.get(Tenant, ctx.tenant_id))
@router.get("/settings/departments")
def departments(ctx: Annotated[AuthContext, Depends(get_current_user)]): return [{"id": f"dept-{i+1}", "tenantId": ctx.tenant_id, "name": name} for i, name in enumerate(["采购部", "仓储部", "销售部", "财务部", "生产部"])]


@router.get("/settings/custom-fields")
def fields(object_type: str = Query(..., alias="objectType"), ctx: Annotated[AuthContext, Depends(get_current_user)] = None, db: Annotated[Session, Depends(get_db)] = None): return [serialize(x) for x in list_tenant_records(db, CustomField, ctx.tenant_id) if x.object_type == object_type]
@router.post("/settings/custom-fields", status_code=201)
def save_field(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]): item = CustomField(id=body.get("id") or f"field-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, object_type=body["objectType"], name=body["name"], label=body["label"], field_type=body.get("type", "string"), required=body.get("required", False), enabled=True, config=body.get("config", {})); db.merge(item); db.commit(); return {"ok": True, "id": item.id}
@router.delete("/settings/custom-fields/{item_id}")
def disable_field(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]): item = get_tenant_record(db, CustomField, item_id, ctx.tenant_id); item.enabled = False; db.commit(); return {"ok": True, "id": item.id}


@router.get("/data/{resource_type}")
def data_table(resource_type: str, ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    if not can_view_data(ctx, resource_type):
        raise ApiError(403, "CG-1003", "没有操作权限")
    items = [x for x in list_tenant_records(db, DataRecord, ctx.tenant_id) if x.resource_type == resource_type]
    return {"data": [{"id": x.id, "name": x.name, **x.payload} for x in items], "total": len(items), "success": True}


@router.post("/data/{resource_type}", status_code=201)
def create_data_record(resource_type: str, body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("data:manage"))], db: Annotated[Session, Depends(get_db)]):
    name = str(body.get("name") or "").strip()
    if not name:
        from ..errors import ApiError
        raise ApiError(422, "CG-2801", "名称不能为空")
    item = DataRecord(id=f"{resource_type}-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, resource_type=resource_type, name=name, payload={key: value for key, value in body.items() if key != "name"})
    db.add(item); add_audit(db, ctx, "新建资料", resource_type, item.id, item.name, item.payload); db.commit(); return {"id": item.id, "name": item.name, **item.payload}


@router.get("/risk-rules")
def risk_rules(ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    items = [x for x in list_tenant_records(db, DataRecord, ctx.tenant_id) if x.resource_type == "risk_rule"]
    if not items:
        return {"data": [{"id": "rule-1", "name": "安全库存预警线", "threshold": "20%", "enabled": True}]}
    return {"data": [{"id": x.id, "name": x.name, **x.payload} for x in items]}


@router.put("/risk-rules/{item_id}")
def update_risk_rule(item_id: str, body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("risk:manage"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, DataRecord, item_id, ctx.tenant_id); item.payload = {**item.payload, **body}; add_audit(db, ctx, "更新风险规则", "risk_rule", item.id, item.name, body); db.commit(); return {"ok": True, "id": item.id, **item.payload}


@router.get("/notifications/webhook-config")
def webhook_config(ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))]): return {"enabled": bool(os.getenv("WEBHOOK_URL")), "url": "***" if os.getenv("WEBHOOK_URL") else ""}
@router.put("/notifications/webhook-config")
def update_webhook_config(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))]): return {"enabled": bool(body.get("enabled")), "url": "***" if body.get("url") else ""}


@router.get("/reports/executive")
def executive_report(ctx: Annotated[AuthContext, Depends(require_permission("report:executive"))]): return {"netBenefit": 732000, "riskCount": 18, "avgResponseHours": 5.2}
@router.get("/reports/operation")
def operation_report(ctx: Annotated[AuthContext, Depends(require_permission("report:operation"))]): return {"funnel": [18, 8, 5, 4, 3], "overdueRate": 0.08}
@router.get("/reports/response")
def response_report(ctx: Annotated[AuthContext, Depends(require_permission("report:view"))]): return {"events": []}
@router.get("/onboarding/templates")
def templates(): return [{"id": "electronics", "name": "电子制造", "desc": "芯片、PCB、关键物料齐套与替代供应商模板"}]
@router.post("/onboarding/progress")
def save_progress(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(get_current_user)]): return {"ok": True, "progress": body}
@router.post("/onboarding/templates/{template_id}/apply")
def apply_template(template_id: str, ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]): item = db.get(Tenant, ctx.tenant_id); item.industry = template_id; db.commit(); return {"ok": True, "tenant": serialize(item)}
