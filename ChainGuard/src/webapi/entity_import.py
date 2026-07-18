"""C2 second-batch import execution, reconciliation, and shipment aggregation."""

from __future__ import annotations

import codecs
import csv
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from src.signature_history import tabular_file_signature

from .entity_mapping import MODEL_BY_TABLE, load_mapping, persist_rejection, upsert_entities
from .models import ImportSignature, ImportSourceRow, InventoryEntity, Material, utcnow


RESOURCE_BY_SOURCE_TABLE = {
    "materials": "material",
    "suppliers": "supplier",
    "supplier_materials": "supplier_material",
    "customers": "customer",
    "sales_orders": "order",
    "sales_order_lines": "order_line",
    "inventory": "inventory",
}
ENTITY_IMPORT_ORDER = (
    "materials", "suppliers", "customers", "supplier_materials",
    "sales_orders", "sales_order_lines", "inventory",
)
FINISHED_SHIPMENT_STATUSES = {"delivered", "completed", "complete", "cancelled", "canceled"}


class DuplicateImportError(RuntimeError):
    def __init__(self, history: ImportSignature):
        super().__init__(f"duplicate import signature: {history.signature}")
        self.history = history


def reserve_import_signature(db: Session, tenant_id: str, import_job_id: str, file_name: str, path: str | Path, resource_type: str) -> ImportSignature:
    """Reserve a normalized signature before any entity write (D04)."""

    signature, row_count = tabular_file_signature(path, resource_type)
    existing = db.scalar(
        select(ImportSignature).where(
            ImportSignature.tenant_id == tenant_id,
            ImportSignature.signature == signature,
        )
    )
    if existing is not None and existing.status != "failed":
        raise DuplicateImportError(existing)
    if existing is not None:
        existing.import_job_id = import_job_id
        existing.file_name = file_name
        existing.status = "reserved"
        existing.row_count = row_count
        return existing
    history = ImportSignature(
        id=f"signature-{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        signature=signature,
        import_job_id=import_job_id,
        file_name=file_name,
        status="reserved",
        row_count=row_count,
    )
    db.add(history)
    return history


def update_import_signature(db: Session, tenant_id: str, import_job_id: str, status: str, row_count: int | None = None) -> None:
    history = db.scalar(
        select(ImportSignature).where(
            ImportSignature.tenant_id == tenant_id,
            ImportSignature.import_job_id == import_job_id,
        )
    )
    if history is not None:
        history.status = status
        if row_count is not None:
            history.row_count = row_count


def _detect_encoding(path: Path) -> str:
    sample = path.read_bytes()[:65536]
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            codecs.getincrementaldecoder(encoding)().decode(sample, final=False)
            return encoding
        except UnicodeDecodeError as error:
            last_error = error
    assert last_error is not None
    raise last_error


def iter_csv_rows(path: str | Path) -> Iterable[dict[str, Any]]:
    source = Path(path)
    with source.open("r", encoding=_detect_encoding(source), newline="") as handle:
        yield from (dict(row) for row in csv.DictReader(handle))


def _audit_rows(db: Session, tenant_id: str, import_job_id: str, source_table: str, rows: list[Mapping[str, Any]], start_row: int) -> None:
    now = utcnow()
    db.execute(
        insert(ImportSourceRow),
        [
            {
                "id": f"source-row-{uuid.uuid4().hex}",
                "tenant_id": tenant_id,
                "import_job_id": import_job_id,
                "source_table": source_table,
                "row_number": start_row + index,
                "payload": dict(row),
                "created_at": now,
                "updated_at": now,
            }
            for index, row in enumerate(rows)
        ],
    )


def _entity_count(db: Session, tenant_id: str, resource_type: str) -> int:
    rule = load_mapping()["resources"][resource_type]
    model = MODEL_BY_TABLE[rule["target_table"]]
    return int(db.scalar(select(func.count()).select_from(model).where(model.tenant_id == tenant_id)) or 0)


def _mapped_row(row: Mapping[str, Any], field_mapping: Mapping[str, str] | None) -> dict[str, Any]:
    if not field_mapping:
        return dict(row)
    return {
        target: value
        for source, value in row.items()
        if (target := field_mapping.get(source))
    }


def import_entity_rows(
    db: Session,
    tenant_id: str,
    import_job_id: str,
    rows: Iterable[Mapping[str, Any]],
    resource_type: str,
    *,
    field_mapping: Mapping[str, str] | None = None,
    batch_size: int = 1000,
) -> dict[str, Any]:
    """Import an iterable from CSV, OCR, or ERP through the same YAML adapter."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    spec = load_mapping()
    if resource_type not in spec["resources"]:
        raise KeyError(f"unknown resource_type: {resource_type}")
    source_table = str(spec["resources"][resource_type]["source_table"])
    started = time.perf_counter()
    source_rows = inserted = updated = rejected_rows = 0
    batch: list[dict[str, Any]] = []

    def consume(current: list[dict[str, Any]], first_row: int) -> None:
        nonlocal source_rows, inserted, updated, rejected_rows
        _audit_rows(db, tenant_id, import_job_id, source_table, current, first_row)
        result = upsert_entities(db, tenant_id, resource_type, current, spec)
        inserted += int(result["inserted"])
        updated += int(result["updated"])
        rejected_rows += len(result["rejected"])
        for rejection in result["rejected"]:
            persist_rejection(
                db, tenant_id, resource_type, source_table, str(rejection["reason"]),
                dict(rejection["source"]), import_job_id=import_job_id,
                row_number=first_row + int(rejection["row"]),
            )
        source_rows += len(current)

    for row in rows:
        batch.append(_mapped_row(row, field_mapping))
        if len(batch) >= batch_size:
            consume(batch, source_rows + 1)
            batch = []
    if batch:
        consume(batch, source_rows + 1)
    db.flush()
    return {
        "table": source_table,
        "sourceRows": source_rows,
        "successRows": source_rows - rejected_rows,
        "rejectedRows": rejected_rows,
        "inserted": inserted,
        "updated": updated,
        "entityRows": _entity_count(db, tenant_id, resource_type),
        "elapsedSeconds": round(time.perf_counter() - started, 6),
    }


def import_entity_file(
    db: Session,
    tenant_id: str,
    import_job_id: str,
    path: str | Path,
    resource_type: str,
    *,
    batch_size: int = 1000,
) -> dict[str, Any]:
    """Stream normalized CSV into one entity table and persist every source/reject row."""
    return import_entity_rows(db, tenant_id, import_job_id, iter_csv_rows(path), resource_type, batch_size=batch_size)


def import_audit_rows(
    db: Session,
    tenant_id: str,
    import_job_id: str,
    rows: Iterable[Mapping[str, Any]],
    source_table: str,
    *,
    field_mapping: Mapping[str, str] | None = None,
    batch_size: int = 2000,
) -> dict[str, Any]:
    """Persist non-entity rows from any channel as immutable source audit rows."""

    started = time.perf_counter()
    source_rows = 0
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(_mapped_row(row, field_mapping))
        if len(batch) >= batch_size:
            _audit_rows(db, tenant_id, import_job_id, source_table, batch, source_rows + 1)
            source_rows += len(batch)
            batch = []
    if batch:
        _audit_rows(db, tenant_id, import_job_id, source_table, batch, source_rows + 1)
        source_rows += len(batch)
    db.flush()
    return {
        "table": source_table, "sourceRows": source_rows, "successRows": source_rows,
        "rejectedRows": 0, "inserted": 0, "updated": 0, "entityRows": 0,
        "elapsedSeconds": round(time.perf_counter() - started, 6),
    }


def import_audit_file(db: Session, tenant_id: str, import_job_id: str, path: str | Path, *, batch_size: int = 2000) -> dict[str, Any]:
    """Persist a non-C2 ERP source table for complete row-level reconciliation."""

    source_table = Path(path).stem.lower()
    return import_audit_rows(db, tenant_id, import_job_id, iter_csv_rows(path), source_table, batch_size=batch_size)


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def aggregate_shipments(
    db: Session,
    tenant_id: str,
    import_job_id: str,
    shipment_rows: Iterable[Mapping[str, Any]],
    purchase_order_line_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate unfinished PO remaining quantity by material into inventory."""

    unfinished_by_po: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for shipment in shipment_rows:
        status = str(shipment.get("shipment_status") or "").strip().lower()
        if status not in FINISHED_SHIPMENT_STATUSES:
            unfinished_by_po[str(shipment.get("purchase_order_id") or "")].append(shipment)

    quantity_by_material: dict[str, float] = defaultdict(float)
    nearest_by_material: dict[str, Mapping[str, Any]] = {}
    invalid_lines = 0
    for line_number, line in enumerate(purchase_order_line_rows, 1):
        purchase_order_id = str(line.get("purchase_order_id") or "")
        shipments = unfinished_by_po.get(purchase_order_id)
        if not shipments:
            continue
        material_id = str(line.get("material_id") or "").strip()
        ordered = _as_number(line.get("ordered_qty"))
        received = _as_number(line.get("received_qty"))
        if not material_id or ordered is None or received is None:
            persist_rejection(
                db, tenant_id, "shipment", "purchase_order_lines",
                "shipments 聚合行缺物料或数量非法", line,
                import_job_id=import_job_id, row_number=line_number,
            )
            invalid_lines += 1
            continue
        quantity_by_material[material_id] += max(ordered - received, 0.0)
        nearest = min(
            shipments,
            key=lambda row: _as_utc(row.get("estimated_arrival_at") or row.get("planned_arrival_at")) or datetime.max.replace(tzinfo=timezone.utc),
        )
        current = nearest_by_material.get(material_id)
        if current is None:
            nearest_by_material[material_id] = nearest
        else:
            current_at = _as_utc(current.get("estimated_arrival_at") or current.get("planned_arrival_at")) or datetime.max.replace(tzinfo=timezone.utc)
            nearest_at = _as_utc(nearest.get("estimated_arrival_at") or nearest.get("planned_arrival_at")) or datetime.max.replace(tzinfo=timezone.utc)
            if nearest_at < current_at:
                nearest_by_material[material_id] = nearest

    inventory_rows = list(db.scalars(select(InventoryEntity).where(InventoryEntity.tenant_id == tenant_id)))
    by_material: dict[str, list[InventoryEntity]] = defaultdict(list)
    for inventory in inventory_rows:
        by_material[inventory.material_id].append(inventory)
        inventory.in_transit_qty = 0.0
        inventory.planned_arrival_at = None
        inventory.estimated_arrival_at = None

    updated = missing = 0
    for material_id, quantity in quantity_by_material.items():
        inventories = sorted(by_material.get(material_id, []), key=lambda row: row.inventory_id)
        material_exists = db.scalar(
            select(Material.id).where(Material.tenant_id == tenant_id, Material.material_id == material_id)
        )
        if material_exists is None or not inventories:
            persist_rejection(
                db, tenant_id, "shipment", "shipments",
                f"shipments 聚合目标非法外键/库存不存在: material_id={material_id}",
                {"material_id": material_id, "in_transit_qty": quantity},
                import_job_id=import_job_id,
            )
            missing += 1
            continue
        nearest = nearest_by_material[material_id]
        warehouse_id = str(nearest.get("destination_warehouse_id") or "")
        target = next((row for row in inventories if row.warehouse_id == warehouse_id), inventories[0])
        target.in_transit_qty = quantity
        target.planned_arrival_at = _as_utc(nearest.get("planned_arrival_at"))
        target.estimated_arrival_at = _as_utc(nearest.get("estimated_arrival_at"))
        updated += 1
    db.flush()
    return {
        "materialsAggregated": len(quantity_by_material),
        "inventoryRowsUpdated": updated,
        "rejectedRows": invalid_lines + missing,
    }


def import_enterprise_directory(db: Session, tenant_id: str, import_job_id: str, directory: str | Path) -> dict[str, Any]:
    """Import/audit every enterprise CSV and return exact per-table reconciliation."""

    root = Path(directory)
    paths = {path.stem.lower(): path for path in root.glob("*.csv")}
    started = time.perf_counter()
    reports: dict[str, dict[str, Any]] = {}
    for table in ENTITY_IMPORT_ORDER:
        path = paths.get(table)
        if path is not None:
            reports[table] = import_entity_file(db, tenant_id, import_job_id, path, RESOURCE_BY_SOURCE_TABLE[table])
            db.commit()
    for table, path in sorted(paths.items()):
        if table not in RESOURCE_BY_SOURCE_TABLE:
            reports[table] = import_audit_file(db, tenant_id, import_job_id, path)
            db.commit()
    if "shipments" in paths and "purchase_order_lines" in paths:
        aggregate = aggregate_shipments(
            db,
            tenant_id,
            import_job_id,
            iter_csv_rows(paths["shipments"]),
            iter_csv_rows(paths["purchase_order_lines"]),
        )
        reports["shipments"]["entityRows"] = aggregate["inventoryRowsUpdated"]
        reports["shipments"]["aggregation"] = aggregate
        reports["shipments"]["rejectedRows"] += aggregate["rejectedRows"]
        reports["shipments"]["successRows"] -= aggregate["rejectedRows"]
        db.commit()
    table_reports = [reports[table] for table in sorted(reports)]
    source_rows = sum(int(report["sourceRows"]) for report in table_reports)
    success_rows = sum(int(report["successRows"]) for report in table_reports)
    rejected_rows = sum(int(report["rejectedRows"]) for report in table_reports)
    audited_rows = int(
        db.scalar(
            select(func.count()).select_from(ImportSourceRow).where(
                ImportSourceRow.tenant_id == tenant_id,
                ImportSourceRow.import_job_id == import_job_id,
            )
        )
        or 0
    )
    return {
        "tenantId": tenant_id,
        "importJobId": import_job_id,
        "sourceRows": source_rows,
        "successRows": success_rows,
        "rejectedRows": rejected_rows,
        "auditedRows": audited_rows,
        "tableReports": table_reports,
        "elapsedSeconds": round(time.perf_counter() - started, 6),
    }
