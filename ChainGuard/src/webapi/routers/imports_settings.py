from __future__ import annotations

import os
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import csv
import hashlib
import uuid
import zipfile
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import AuthContext, can_view_data, get_current_user, require_permission
from ..config import settings
from ..database import get_db
from ..errors import ApiError
from ..models import CustomField, DataRecord, ImportJob, Role, Tenant, User
from ..entity_import import DuplicateImportError, reserve_import_signature
from ..entity_repository import MODEL_BY_RESOURCE, list_product_rows, save_product_entity
from ..enterprise_import_catalog import IMPORT_TYPE_CATALOG, catalog_payload
from ..import_classifier import recognize_import_type
from ..jobs import enqueue_import_job
from ..repository import add_audit, get_tenant_record, list_tenant_records, serialize
from ..schemas import PatchRequest


router = APIRouter(tags=["imports-settings"])

STRUCTURED_SUFFIXES = {".csv", ".xlsx"}
OCR_SUFFIXES = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
ARCHIVE_SUFFIXES = {".zip"}


def _headers_for_path(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(next(csv.reader(handle), []))
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        sheet = load_workbook(path, read_only=True, data_only=True).active
        return [str(value or "").strip() for value in next(sheet.iter_rows(values_only=True), ())]
    return []


def _recognize_path(path: Path) -> dict[str, Any]:
    try:
        return recognize_import_type(path.name, _headers_for_path(path))
    except Exception:
        return recognize_import_type(path.name)


def _public_job(job: ImportJob) -> dict[str, Any]:
    payload = serialize(job)
    options = dict(payload.get("options") or {})
    options.pop("path", None)
    raw_result = dict(payload.get("result") or {})
    streaming = raw_result.get("streaming") if isinstance(raw_result.get("streaming"), dict) else {}

    def count(*keys: str) -> int:
        for source in (raw_result, streaming, payload):
            for key in keys:
                if source.get(key) is not None:
                    try:
                        return int(source[key])
                    except (TypeError, ValueError):
                        continue
        return 0

    source_rows = count("total", "sourceRows")
    success_rows = count("success", "successRows", "imported")
    rejected_rows = count("failed", "rejectedRows")
    reports = raw_result.get("reports") or raw_result.get("tableReports") or streaming.get("reports") or streaming.get("tableReports") or []
    normalized_result = {
        **raw_result,
        "total": source_rows,
        "sourceRows": source_rows,
        "success": success_rows,
        "successRows": success_rows,
        "failed": rejected_rows,
        "rejectedRows": rejected_rows,
        "reports": reports,
        "tableReports": reports,
    }
    operator = payload.get("operator") or options.get("operator") or "-"
    updated_at = job.updated_at.isoformat() if job.updated_at is not None else payload.get("createdAt")
    payload.update({
        "options": options,
        "result": normalized_result,
        "total": source_rows,
        "sourceRows": source_rows,
        "success": success_rows,
        "successRows": success_rows,
        "failed": rejected_rows,
        "rejectedRows": rejected_rows,
        "reports": reports,
        "operator": operator,
        "updatedAt": updated_at,
    })
    return payload


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


@router.get("/imports/catalog")
def import_catalog(ctx: Annotated[AuthContext, Depends(require_permission("data:import"))]):
    return catalog_payload()


@router.post("/imports/upload", status_code=201)
async def upload_import(
    file: UploadFile,
    import_type: str = Query("auto", alias="type"),
    mode: str = Query("structured"),
    ctx: Annotated[AuthContext, Depends(require_permission("data:import"))] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    job_id = f"import-{uuid.uuid4().hex}"
    safe_name = Path(file.filename or "upload.csv").name
    suffix = Path(safe_name).suffix.lower()
    if mode not in {"structured", "ocr"}:
        raise ApiError(422, "CG-2603", "文件上传仅支持 structured 或 ocr 通道")
    allowed = STRUCTURED_SUFFIXES if mode == "structured" else OCR_SUFFIXES
    if suffix not in allowed:
        channel = "CSV/XLSX" if mode == "structured" else "PDF/Word/图片"
        raise ApiError(422, "CG-2603", f"当前通道仅支持 {channel}")
    if import_type != "auto" and import_type not in IMPORT_TYPE_CATALOG:
        raise ApiError(422, "CG-2603", "资料类型不存在")
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
    recognition = _recognize_path(path)
    job = ImportJob(
        id=job_id, tenant_id=ctx.tenant_id, file_name=safe_name, import_type=import_type,
        status="uploaded", progress=0,
        options={"size": size, "path": str(path.resolve()), "mode": mode, "recognition": recognition, "operator": ctx.name}, result={},
    )
    db.add(job); add_audit(db, ctx, "上传导入", "import", job.id, job.file_name, {"type": import_type, "mode": mode, "size": size}); db.commit()
    return _public_job(job)


@router.post("/imports/batch/classify", status_code=201)
async def classify_import_batch(
    files: list[UploadFile],
    ctx: Annotated[AuthContext, Depends(require_permission("data:import"))] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    """Upload a folder selection or ZIP and create one classified job per supported file."""

    candidates: list[tuple[str, bytes]] = []
    total_bytes = 0
    for uploaded in files:
        name = Path(uploaded.filename or "upload").name
        data = await uploaded.read()
        if Path(name).suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(BytesIO(data)) as archive:
                    members = [member for member in archive.infolist() if not member.is_dir()]
                    if len(members) > 200:
                        raise ApiError(413, "CG-2604", "压缩包文件数超过 200")
                    for member in members:
                        member_path = Path(member.filename.replace("\\", "/"))
                        if member_path.is_absolute() or ".." in member_path.parts:
                            raise ApiError(422, "CG-2606", "压缩包包含不安全路径")
                        if ((member.external_attr >> 16) & 0o170000) == 0o120000:
                            raise ApiError(422, "CG-2606", "压缩包不允许包含符号链接")
                        suffix = member_path.suffix.lower()
                        if suffix not in STRUCTURED_SUFFIXES | OCR_SUFFIXES:
                            continue
                        if member.file_size > settings.max_import_bytes:
                            raise ApiError(413, "CG-2604", f"{member_path.name} 超过单文件大小限制")
                        content = archive.read(member)
                        candidates.append((member_path.name, content))
                        total_bytes += len(content)
            except zipfile.BadZipFile as error:
                raise ApiError(422, "CG-2606", "ZIP 文件损坏或格式无效") from error
        else:
            suffix = Path(name).suffix.lower()
            if suffix not in STRUCTURED_SUFFIXES | OCR_SUFFIXES:
                continue
            candidates.append((name, data))
            total_bytes += len(data)
    if total_bytes > settings.max_import_bytes * 10:
        raise ApiError(413, "CG-2604", "批量上传总大小超过限制")
    if not candidates:
        raise ApiError(422, "CG-2603", "没有发现可导入的 CSV、XLSX、PDF、Word 或图片")

    batch_id = f"batch-{uuid.uuid4().hex}"
    jobs: list[dict[str, Any]] = []
    for index, (name, data) in enumerate(candidates, 1):
        job_id = f"import-{uuid.uuid4().hex}"
        directory = Path(".workspace") / "imports" / ctx.tenant_id / job_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / Path(name).name
        path.write_bytes(data)
        mode = "structured" if path.suffix.lower() in STRUCTURED_SUFFIXES else "ocr"
        recognition = _recognize_path(path)
        job = ImportJob(
            id=job_id, tenant_id=ctx.tenant_id, file_name=path.name, import_type="auto",
            status="uploaded", progress=0,
            options={"size": len(data), "path": str(path.resolve()), "mode": mode, "batchId": batch_id, "recognition": recognition, "operator": ctx.name},
            result={},
        )
        db.add(job)
        jobs.append({"jobId": job_id, "fileName": path.name, "mode": mode, "recognition": recognition, "sequence": index})
    add_audit(db, ctx, "批量上传并分类", "import", batch_id, batch_id, {"files": len(jobs), "bytes": total_bytes})
    db.commit()
    return {"batchId": batch_id, "files": jobs, "total": len(jobs), "requiresConfirmation": True}


def _erp_connector(values: dict[str, Any]):
    from src.connectors.rest_connector import RestErpConnector
    base_url = str(values.get("baseUrl") or "").strip()
    if not base_url.startswith(("http://", "https://")):
        raise ApiError(422, "CG-2610", "ERP 地址必须是 http:// 或 https:// URL")
    return RestErpConnector(base_url, api_key=str(values.get("apiKey") or ""), timeout=8.0, retries=1)


@router.post("/imports/erp/test")
def test_erp_connection(body: PatchRequest, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))]):
    try:
        return _erp_connector(body.values).test_connection()
    except Exception as error:
        raise ApiError(502, "CG-2611", f"ERP 连接失败：{error}") from error


@router.post("/imports/erp/preview")
def preview_erp_import(body: PatchRequest, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))]):
    connector = _erp_connector(body.values)
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
        raise ApiError(502, "CG-2611", f"ERP 目录读取失败：{error}") from error
    return {"resources": resources, "totalRows": sum(item["rows"] for item in resources), "requiresConfirmation": True}


@router.post("/imports/erp/sync", status_code=201)
def sync_erp_import(
    body: PatchRequest,
    ctx: Annotated[AuthContext, Depends(require_permission("data:import"))],
    db: Annotated[Session, Depends(get_db)],
):
    """Run an explicitly confirmed, tenant-scoped ERP sync through the shared adapter."""

    if not bool(body.values.get("confirmed")):
        raise ApiError(409, "CG-2612", "必须确认 ERP 同步范围后才能执行")
    selected = list(dict.fromkeys(body.values.get("types") or []))
    if not selected or any(value not in IMPORT_TYPE_CATALOG for value in selected):
        raise ApiError(422, "CG-2603", "请选择有效的 ERP 资料类型")
    connector = _erp_connector(body.values)
    from ..entity_import import aggregate_shipments, import_audit_rows, import_entity_rows

    order = [value for value in ("material", "supplier", "customer", "supplier_material", "order", "order_line", "inventory") if value in selected]
    order += [value for value in selected if value not in order]
    job_id = f"erp-{uuid.uuid4().hex}"
    job = ImportJob(
        id=job_id, tenant_id=ctx.tenant_id, file_name="ERP 接口同步", import_type="erp",
        status="running", progress=10,
        options={"mode": "erp", "baseUrl": str(body.values.get("baseUrl")), "types": selected, "operator": ctx.name}, result={},
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
                report = import_entity_rows(db, ctx.tenant_id, job_id, rows, value)
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
        add_audit(db, ctx, "ERP 接口导入", "import", job_id, "ERP 接口同步", {"types": selected, "total": total})
        db.commit()
        return _public_job(job)
    except Exception as error:
        db.rollback()
        raise ApiError(502, "CG-2613", f"ERP 同步失败，未提交本批次：{error}") from error


@router.post("/imports/{item_id}/preflight")
def preflight(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    from src.import_preflight import run_preflight
    item = get_tenant_record(db, ImportJob, item_id, ctx.tenant_id)
    suffix = Path(item.file_name).suffix.lower()
    mode = str(item.options.get("mode") or ("ocr" if suffix in OCR_SUFFIXES else "structured"))
    if suffix in OCR_SUFFIXES:
        from src.ingestion_agent import ingest_files
        intake = ingest_files([item.options["path"]])
        extraction = intake.extractions[0]
        if extraction.needs_manual:
            item.status, item.progress = "manual_required", 25
            item.result = {
                "canProceed": False, "status": "manual_required",
                "message": "待人工处理：未提取到可校验内容，原始文件已保留。",
                "recognition": item.options.get("recognition"), "extraction": asdict(extraction),
                "manualReview": {"required": True, "confirmationLevel": "full", "firstImport": True},
            }
            db.commit(); payload = serialize(item); payload["options"].pop("path", None); return payload
        rows = next(iter(intake.normalized.values()), [])
        if rows and all(str(key).startswith("col_") for key in rows[0]):
            detected_headers = [str(value).strip() for value in rows[0].values()]
            if len(rows) > 1 and all(detected_headers):
                rows = [
                    {detected_headers[index]: value for index, value in enumerate(source.values()) if index < len(detected_headers)}
                    for source in rows[1:]
                ]
        if not rows:
            item.status, item.progress = "manual_required", 25
            item.result = {
                "canProceed": False, "status": "manual_required",
                "message": "已识别文档，但没有形成可导入的数据行；请人工处理原文。",
                "recognition": item.options.get("recognition"), "extraction": asdict(extraction),
                "manualReview": {"required": True, "confirmationLevel": "full", "firstImport": True},
            }
            db.commit(); return _public_job(item)
        normalized_path = Path(item.options["path"]).parent / "normalized.csv"
        with normalized_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader(); writer.writerows(rows)
        recognition = recognize_import_type(item.file_name, rows[0].keys() if rows else [])
        schema_signature = hashlib.sha256("|".join(sorted(rows[0].keys() if rows else [])).encode("utf-8")).hexdigest()
        previous = [
            job for job in db.query(ImportJob).filter(ImportJob.tenant_id == ctx.tenant_id, ImportJob.status == "succeeded").all()
            if job.options.get("mode") == "ocr" and job.options.get("schemaSignature") == schema_signature
        ]
        seen_count = len(previous)
        item.options = {
            **item.options, "originalPath": item.options["path"], "path": str(normalized_path.resolve()),
            "extraction": asdict(extraction), "recognition": recognition, "schemaSignature": schema_signature,
        }
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
    item.status = "manual_review" if mode == "ocr" and report.can_proceed else "preflighted" if report.can_proceed else "failed"
    item.progress = 25
    # camelCase 与前端 estimatedRows/canProceed 契约对齐（P1-4）；verdict 键名不变，confirm 闸门不受影响
    item.result = {
        **camelize_report(report), "normalized": normalized_preview(item.options["path"]),
        "recognition": item.options.get("recognition"),
    }
    if mode == "ocr":
        item.result["manualReview"] = {
            "required": True, "firstImport": seen_count == 0, "seenCount": seen_count,
            "familiarity": "novel" if seen_count == 0 else "familiar",
            "confirmationLevel": "full" if seen_count == 0 else "light",
            "confirmationPoints": ["识别出的资料类型", "关键业务字段", "低置信度/空值行"] if seen_count == 0 else ["本次差异与低置信度行"],
        }
    db.commit()
    payload = serialize(item); payload["options"].pop("path", None); return payload


@router.post("/imports/{item_id}/confirm")
def confirm_import(item_id: str, body: PatchRequest, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, ImportJob, item_id, ctx.tenant_id)
    force = bool(body.values.get("force"))
    confirmed_type = str(body.values.get("confirmedType") or item.import_type)
    if item.import_type == "auto" and confirmed_type not in IMPORT_TYPE_CATALOG:
        raise ApiError(409, "CG-2607", "必须人工确认识别出的资料类型后才能继续")
    if confirmed_type not in IMPORT_TYPE_CATALOG:
        raise ApiError(422, "CG-2603", "资料类型不存在")
    mode = str(item.options.get("mode") or "structured")
    if mode == "ocr" and not bool(body.values.get("manualConfirmed")):
        raise ApiError(409, "CG-2608", "OCR/文档导入必须完成人工确认，不能强制绕过")
    if item.status == "failed":
        # Disk shortage is a hard safety gate, not an override-able quality warning.
        if item.result.get("verdict") == "INSUFFICIENT_DISK":
            raise ApiError(409, "CG-2602", "磁盘空间不足，不能强制导入")
        # P1-4：解析失败没有可导入的归一化数据，同样不允许强制
        if item.result.get("verdict") == "PARSE_ERROR":
            raise ApiError(409, "CG-2602", "文件解析失败，不能强制导入")
        if not force:
            raise ApiError(409, "CG-2602", "预检未通过，需明确确认后才能继续导入")
    if item.status not in {"preflighted", "manual_review", "failed"}:
        raise ApiError(409, "CG-2601", "导入任务尚未完成预检")
    item.import_type = confirmed_type
    item.status = "confirmed"; item.options = {**item.options, **body.values, "typeConfirmed": True}; item.progress = 50; db.commit()
    payload = serialize(item); payload["options"].pop("path", None); return payload


@router.post("/imports/{item_id}/execute", status_code=202)
def execute_import(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, ImportJob, item_id, ctx.tenant_id)
    if item.status != "confirmed":
        raise ApiError(409, "CG-2601", "导入任务尚未确认")
    try:
        history = reserve_import_signature(
            db,
            ctx.tenant_id,
            item.id,
            item.file_name,
            item.options["path"],
            item.import_type,
        )
        db.flush()  # UNIQUE(tenant_id, signature) closes concurrent execute races.
    except DuplicateImportError as error:
        raise ApiError(409, "CG-2605", f"D04：相同签名文件已导入（批次 {error.history.import_job_id}）") from error
    except IntegrityError as error:
        db.rollback()
        raise ApiError(409, "CG-2605", "D04：相同签名文件已被其他导入任务占用") from error
    item.status = "pending"
    item.options = {**item.options, "signature": history.signature}
    db.commit()
    enqueue_import_job(item.id, ctx)
    return {"jobId": item.id, "status": item.status}


@router.get("/imports/{item_id}")
def import_progress(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    item = get_tenant_record(db, ImportJob, item_id, ctx.tenant_id); return _public_job(item)
@router.get("/imports")
def import_history(ctx: Annotated[AuthContext, Depends(require_permission("data:import"))], db: Annotated[Session, Depends(get_db)]):
    data = [_public_job(item) for item in list_tenant_records(db, ImportJob, ctx.tenant_id)]
    return {"data": data, "total": len(data), "success": True}
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
    if resource_type not in MODEL_BY_RESOURCE:
        raise ApiError(404, "CG-2804", "资料类型不存在")
    if not can_view_data(ctx, resource_type):
        raise ApiError(403, "CG-1003", "没有操作权限")
    items = list_product_rows(db, ctx.tenant_id, resource_type)
    return {"data": items, "total": len(items), "success": True}


@router.post("/data/{resource_type}", status_code=201)
def create_data_record(resource_type: str, body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("data:manage"))], db: Annotated[Session, Depends(get_db)]):
    if resource_type not in MODEL_BY_RESOURCE:
        raise ApiError(404, "CG-2804", "资料类型不存在")
    name = str(body.get("name") or "").strip()
    if not name and resource_type in {"material", "supplier", "customer"}:
        raise ApiError(422, "CG-2801", "名称不能为空")
    try:
        item = save_product_entity(db, ctx.tenant_id, resource_type, body)
    except ValueError as error:
        raise ApiError(422, "CG-2802", str(error)) from error
    rows = list_product_rows(db, ctx.tenant_id, resource_type)
    business_id = getattr(item, {"material": "material_id", "supplier": "supplier_id", "customer": "customer_id", "order": "sales_order_id", "inventory": "inventory_id"}[resource_type])
    payload = next(row for row in rows if row["id"] == business_id)
    add_audit(db, ctx, "新建资料", resource_type, str(business_id), str(payload.get("name") or payload.get("orderNo") or payload.get("material") or business_id), payload)
    db.commit()
    return payload


@router.get("/data/{resource_type}/{item_id}")
def data_record_detail(item_id: str, resource_type: str, ctx: Annotated[AuthContext, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    if resource_type not in MODEL_BY_RESOURCE:
        raise ApiError(404, "CG-2804", "资料类型不存在")
    if not can_view_data(ctx, resource_type):
        raise ApiError(403, "CG-1003", "没有操作权限")
    item = next((row for row in list_product_rows(db, ctx.tenant_id, resource_type) if row["id"] == item_id), None)
    if item is None:
        raise ApiError(404, "CG-2804", "资料不存在")
    return item


@router.patch("/data/{resource_type}/{item_id}")
def update_data_record(item_id: str, resource_type: str, body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("data:manage"))], db: Annotated[Session, Depends(get_db)]):
    if resource_type not in MODEL_BY_RESOURCE:
        raise ApiError(404, "CG-2804", "资料类型不存在")
    try:
        save_product_entity(db, ctx.tenant_id, resource_type, body, business_key=item_id)
    except LookupError as error:
        raise ApiError(404, "CG-2804", "资料不存在") from error
    except ValueError as error:
        raise ApiError(422, "CG-2802", str(error)) from error
    payload = next(row for row in list_product_rows(db, ctx.tenant_id, resource_type) if row["id"] == item_id)
    add_audit(db, ctx, "更新资料", resource_type, item_id, str(payload.get("name") or payload.get("orderNo") or payload.get("material") or item_id), body)
    db.commit()
    return payload


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
