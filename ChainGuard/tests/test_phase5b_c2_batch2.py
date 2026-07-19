from __future__ import annotations

import csv
import asyncio
from io import BytesIO
import shutil
import uuid
import zipfile
from datetime import timezone
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from src.webapi.auth import AuthContext
from src.webapi.database import Base
from src.webapi.entity_import import (
    DuplicateImportError,
    aggregate_shipments,
    import_entity_file,
    reserve_import_signature,
    import_entity_rows,
)
from src.webapi.enterprise_import_catalog import IMPORT_MODES, IMPORT_TYPE_CATALOG, catalog_payload
from src.webapi.import_classifier import recognize_import_type
from src.webapi.entity_mapping import migrate_data_records, upsert_entities
from src.webapi.entity_repository import list_product_rows, save_product_entity
from src.webapi.errors import ApiError
from src.webapi.models import (
    CustomerEntity,
    DataRecord,
    ImportJob,
    ImportRejection,
    ImportSignature,
    ImportSourceRow,
    InventoryEntity,
    Material,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
)
from src.webapi.routers import imports_settings


@pytest.fixture
def runtime_dir():
    path = Path(__file__).resolve().parent / "_runtime_tmp" / "phase5b_c2_batch2" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def c2_session(runtime_dir: Path):
    from sqlalchemy import create_engine

    database = runtime_dir / "c2-batch2.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()
    engine.dispose()


def _write_csv(path: Path, rows: list[dict]) -> Path:
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_enterprise_import_catalog_exposes_three_channels_and_all_18_real_types():
    payload = catalog_payload()
    assert [mode["value"] for mode in IMPORT_MODES] == ["structured", "ocr", "erp"]
    assert len(IMPORT_TYPE_CATALOG) == len(payload["types"]) == 18
    assert {item["source_table"] for item in payload["types"]} == {
        "materials", "suppliers", "supplier_materials", "customers", "warehouses",
        "inventory", "inventory_snapshots", "inventory_movements", "shipments",
        "sales_orders", "sales_order_lines", "purchase_orders", "purchase_order_lines",
        "production_plans", "quality_inspections", "supplier_performance",
        "disruption_events", "historical_decisions",
    }


def test_erp_sync_router_uses_shared_entity_import_adapter(c2_session: Session, monkeypatch):
    class StubConnector:
        def fetch_resource(self, resource: str):
            assert resource == "materials"
            return [{"material_id": "MAT-ERP", "material_name": "ERP 物料", "standard_cost": "12.5"}]

    monkeypatch.setattr(imports_settings, "_erp_connector", lambda _values: StubConnector())
    context = AuthContext("u-a", "tenant-a", "A", "scm_lead", ("data:import",))
    response = imports_settings.sync_erp_import(
        imports_settings.PatchRequest(values={"confirmed": True, "types": ["material"], "baseUrl": "https://erp.invalid"}),
        context,
        c2_session,
    )
    assert response["status"] == "succeeded"
    material = c2_session.scalar(
        select(Material).where(Material.tenant_id == "tenant-a", Material.material_id == "MAT-ERP")
    )
    assert material is not None and material.material_name == "ERP 物料" and material.unit_cost == 12.5


def test_recognition_agent_uses_filename_and_headers_but_always_requires_confirmation():
    recognized = recognize_import_type("unknown-export.csv", ["shipment_id", "purchase_order_id", "tracking_number", "carrier"])
    assert recognized["recognizedType"] == "shipment"
    assert recognized["confidence"] >= 0.55
    assert recognized["requiresConfirmation"] is True
    uncertain = recognize_import_type("upload.csv", ["foo", "bar"])
    assert uncertain["recognizedType"] is None
    assert uncertain["label"] == "待人工指定"


def test_field_mapping_is_applied_before_shared_entity_adapter(c2_session: Session):
    result = import_entity_rows(
        c2_session, "tenant-a", "job-mapping",
        [{"物料编码": "MAT-MAP", "物料名称": "映射物料", "成本": "12.5"}],
        "material",
        field_mapping={"物料编码": "material_id", "物料名称": "material_name", "成本": "standard_cost"},
    )
    assert result["successRows"] == 1
    entity = c2_session.scalar(select(Material).where(Material.tenant_id == "tenant-a", Material.material_id == "MAT-MAP"))
    assert entity is not None and entity.material_name == "映射物料" and entity.unit_cost == 12.5


def test_entity_import_result_exposes_row_level_rejection_details(c2_session: Session):
    result = import_entity_rows(
        c2_session, "tenant-a", "job-rejection-details",
        [{"material_name": "缺少编号的物料", "standard_cost": "12.5"}],
        "material",
    )
    assert result["successRows"] == 0 and result["rejectedRows"] == 1
    assert result["rejections"] == [{
        "row": 1,
        "reason": "缺业务主键/必填字段: ['material_id']",
        "source": {"material_name": "缺少编号的物料", "standard_cost": "12.5"},
    }]


def test_ocr_confirm_requires_manual_confirmation_and_confirmed_type(c2_session: Session):
    context = AuthContext("u-a", "tenant-a", "A", "scm_lead", ("data:import",))
    item = ImportJob(
        id="job-ocr-review", tenant_id="tenant-a", file_name="scan.pdf", import_type="auto",
        status="manual_review", progress=25,
        options={"mode": "ocr", "path": "scan.pdf", "recognition": {"recognizedType": "material"}},
        result={"canProceed": True, "manualReview": {"required": True, "confirmationLevel": "full"}},
    )
    c2_session.add(item); c2_session.commit()
    with pytest.raises(ApiError) as missing_type:
        imports_settings.confirm_import(item.id, imports_settings.PatchRequest(values={}), context, c2_session)
    assert missing_type.value.code == "CG-2607"
    with pytest.raises(ApiError) as missing_review:
        imports_settings.confirm_import(item.id, imports_settings.PatchRequest(values={"confirmedType": "material"}), context, c2_session)
    assert missing_review.value.code == "CG-2608"
    confirmed = imports_settings.confirm_import(
        item.id,
        imports_settings.PatchRequest(values={"confirmedType": "material", "manualConfirmed": True}),
        context,
        c2_session,
    )
    assert confirmed["status"] == "confirmed"
    assert item.import_type == "material" and item.options["typeConfirmed"] is True


def test_mixed_zip_upload_creates_structured_and_ocr_jobs(c2_session: Session, runtime_dir: Path, monkeypatch):
    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("nested/materials.csv", "material_id,material_name\nMAT-1,芯片\n")
        archive.writestr("nested/quality_inspections.png", b"fake-image")
        archive.writestr("nested/readme.txt", "ignored")
    archive_bytes.seek(0)
    monkeypatch.chdir(runtime_dir)
    context = AuthContext("u-a", "tenant-a", "A", "scm_lead", ("data:import",))
    result = asyncio.run(imports_settings.classify_import_batch(
        [UploadFile(filename="mixed.zip", file=archive_bytes)], context, c2_session,
    ))
    assert result["total"] == 2 and result["requiresConfirmation"] is True
    assert {item["mode"] for item in result["files"]} == {"structured", "ocr"}
    by_name = {item["fileName"]: item for item in result["files"]}
    assert by_name["materials.csv"]["recognition"]["recognizedType"] == "material"
    assert by_name["quality_inspections.png"]["recognition"]["recognizedType"] == "quality_inspection"
    jobs = list(c2_session.scalars(select(ImportJob).where(ImportJob.tenant_id == "tenant-a")))
    assert len(jobs) == 2 and all(job.import_type == "auto" for job in jobs)


def test_execute_normalized_files_land_in_all_seven_entity_tables(c2_session: Session, runtime_dir: Path):
    sources = [
        ("material", [{"material_id": "MAT-1", "material_name": "芯片", "daily_consumption": "24", "standard_cost": "10"}], Material),
        ("supplier", [{"supplier_id": "SUP-1", "supplier_name": "供应商", "status": "active"}], SupplierEntity),
        ("customer", [{"customer_id": "CUS-1", "customer_name": "客户", "customer_level": "A"}], CustomerEntity),
        ("supplier_material", [{"supplier_material_id": "SM-1", "supplier_id": "SUP-1", "material_id": "MAT-1", "qualified": "1", "supplier_rank": "1"}], SupplierMaterial),
        ("order", [{"sales_order_id": "SO-1", "customer_id": "CUS-1", "promised_delivery_at": "2026-07-18T08:00:00+08:00", "order_amount": "100", "gross_profit": "20", "penalty_cost": "5"}], SalesOrder),
        ("order_line", [{"sales_order_line_id": "SOL-1", "sales_order_id": "SO-1", "line_no": "1", "material_id": "MAT-1", "ordered_qty": "8", "unit_price": "10"}], SalesOrderLine),
        ("inventory", [{"inventory_id": "INV-1", "material_id": "MAT-1", "warehouse_id": "WH-1", "available_qty": "20", "on_hand_qty": "20", "safety_stock_qty": "5"}], InventoryEntity),
    ]
    for index, (resource_type, rows, model) in enumerate(sources, 1):
        result = import_entity_file(c2_session, "tenant-a", "job-seven", _write_csv(runtime_dir / f"{resource_type}.csv", rows), resource_type)
        assert result["sourceRows"] == result["successRows"] == result["entityRows"] == 1
        assert result["rejectedRows"] == 0
        assert c2_session.scalar(select(func.count()).select_from(model).where(model.tenant_id == "tenant-a")) == 1
    assert c2_session.scalar(select(func.count()).select_from(ImportSourceRow).where(ImportSourceRow.tenant_id == "tenant-a")) == 7


def test_d04_blocks_same_normalized_signature_before_enqueue(c2_session: Session, runtime_dir: Path, monkeypatch):
    path = _write_csv(runtime_dir / "materials.csv", [{"material_id": "MAT-1", "material_name": "芯片"}])
    context = AuthContext("u-a", "tenant-a", "A", "scm_lead", ("data:import",))
    first = ImportJob(id="job-1", tenant_id="tenant-a", file_name="materials.csv", import_type="material", status="confirmed", progress=50, options={"path": str(path)}, result={})
    second = ImportJob(id="job-2", tenant_id="tenant-a", file_name="copy.csv", import_type="material", status="confirmed", progress=50, options={"path": str(path)}, result={})
    other = ImportJob(id="job-b", tenant_id="tenant-b", file_name="copy.csv", import_type="material", status="confirmed", progress=50, options={"path": str(path)}, result={})
    c2_session.add_all([first, second, other])
    c2_session.commit()
    queued: list[str] = []
    monkeypatch.setattr(imports_settings, "enqueue_import_job", lambda job_id, _ctx: queued.append(job_id))
    assert imports_settings.execute_import(first.id, context, c2_session)["status"] == "pending"
    with pytest.raises(ApiError) as blocked:
        imports_settings.execute_import(second.id, context, c2_session)
    assert blocked.value.code == "CG-2605"
    assert queued == ["job-1"]
    other_context = AuthContext("u-b", "tenant-b", "B", "scm_lead", ("data:import",))
    assert imports_settings.execute_import(other.id, other_context, c2_session)["status"] == "pending"
    assert c2_session.scalar(select(func.count()).select_from(ImportSignature)) == 2


def test_legacy_migration_is_idempotent_and_persists_missing_sensitive_and_bad_fk_rejections(c2_session: Session):
    c2_session.add_all([
        DataRecord(id="legacy-good", tenant_id="tenant-a", resource_type="material", name="芯片", payload={"materialId": "MAT-1", "dailyConsumption": 24}),
        DataRecord(id="legacy-missing", tenant_id="tenant-a", resource_type="material", name="无编号", payload={}),
        DataRecord(id="legacy-secret", tenant_id="tenant-a", resource_type="material", name="敏感", payload={"materialId": "MAT-2", "api_key": "secret"}),
        DataRecord(id="legacy-fk", tenant_id="tenant-a", resource_type="inventory", name="错误库存", payload={"inventoryId": "INV-X", "materialId": "MAT-NOT-FOUND"}),
    ])
    c2_session.commit()
    first = migrate_data_records(c2_session, "tenant-a")
    c2_session.commit()
    material_count = c2_session.scalar(select(func.count()).select_from(Material).where(Material.tenant_id == "tenant-a"))
    rejection_count = c2_session.scalar(select(func.count()).select_from(ImportRejection).where(ImportRejection.tenant_id == "tenant-a"))
    second = migrate_data_records(c2_session, "tenant-a")
    c2_session.commit()
    assert first == {"source": 4, "inserted": 1, "updated": 0, "rejected": 3}
    assert second == {"source": 4, "inserted": 0, "updated": 1, "rejected": 3}
    assert c2_session.scalar(select(func.count()).select_from(Material).where(Material.tenant_id == "tenant-a")) == material_count == 1
    assert c2_session.scalar(select(func.count()).select_from(InventoryEntity).where(InventoryEntity.tenant_id == "tenant-a")) == 0
    assert c2_session.scalar(select(func.count()).select_from(ImportRejection).where(ImportRejection.tenant_id == "tenant-a")) == rejection_count == 3
    assert c2_session.scalar(select(func.count()).select_from(DataRecord).where(DataRecord.tenant_id == "tenant-a")) == 4


def test_ab_same_business_key_isolated_and_cross_tenant_fk_read_update_fail(c2_session: Session):
    upsert_entities(c2_session, "tenant-a", "material", [{"material_id": "MAT-SAME", "material_name": "A物料", "daily_consumption": 24}])
    upsert_entities(c2_session, "tenant-b", "material", [{"material_id": "MAT-SAME", "material_name": "B物料", "daily_consumption": 48}])
    c2_session.commit()
    bad_fk = upsert_entities(c2_session, "tenant-a", "inventory", [{"inventory_id": "INV-A", "material_id": "MAT-B-ONLY"}])
    upsert_entities(c2_session, "tenant-b", "material", [{"material_id": "MAT-B-ONLY", "material_name": "B私有"}])
    c2_session.commit()
    bad_fk = upsert_entities(c2_session, "tenant-a", "inventory", [{"inventory_id": "INV-A", "material_id": "MAT-B-ONLY"}])
    assert bad_fk["inserted"] == 0 and "非法外键" in bad_fk["rejected"][0]["reason"]
    assert [row["name"] for row in list_product_rows(c2_session, "tenant-a", "material")] == ["A物料"]
    assert {row["name"] for row in list_product_rows(c2_session, "tenant-b", "material")} == {"B物料", "B私有"}
    with pytest.raises(LookupError):
        save_product_entity(c2_session, "tenant-a", "material", {"name": "越权更新"}, business_key="MAT-B-ONLY")
    assert c2_session.scalar(select(Material).where(Material.tenant_id == "tenant-b", Material.material_id == "MAT-B-ONLY")).material_name == "B私有"


def test_shipments_sum_remaining_quantity_and_choose_nearest_unfinished_utc(c2_session: Session):
    upsert_entities(c2_session, "tenant-a", "material", [{"material_id": "MAT-1", "material_name": "芯片"}])
    upsert_entities(c2_session, "tenant-a", "inventory", [
        {"inventory_id": "INV-1", "material_id": "MAT-1", "warehouse_id": "WH-1"},
        {"inventory_id": "INV-2", "material_id": "MAT-1", "warehouse_id": "WH-2"},
    ])
    shipments = [
        {"shipment_id": "S1", "purchase_order_id": "PO-1", "destination_warehouse_id": "WH-2", "planned_arrival_at": "2026-07-20T08:00:00+08:00", "estimated_arrival_at": "2026-07-20T12:00:00+08:00", "shipment_status": "in_transit"},
        {"shipment_id": "S2", "purchase_order_id": "PO-1", "destination_warehouse_id": "WH-1", "planned_arrival_at": "2026-07-21T08:00:00+08:00", "estimated_arrival_at": "2026-07-21T08:00:00+08:00", "shipment_status": "delayed"},
        {"shipment_id": "S3", "purchase_order_id": "PO-2", "destination_warehouse_id": "WH-1", "planned_arrival_at": "2026-07-19T08:00:00+08:00", "estimated_arrival_at": "2026-07-19T10:00:00+08:00", "shipment_status": "delivered"},
    ]
    lines = [
        {"purchase_order_id": "PO-1", "material_id": "MAT-1", "ordered_qty": "100", "received_qty": "30"},
        {"purchase_order_id": "PO-2", "material_id": "MAT-1", "ordered_qty": "90", "received_qty": "0"},
    ]
    result = aggregate_shipments(c2_session, "tenant-a", "job-ship", shipments, lines)
    c2_session.commit()
    assert result == {"materialsAggregated": 1, "inventoryRowsUpdated": 1, "rejectedRows": 0}
    inv1 = c2_session.scalar(select(InventoryEntity).where(InventoryEntity.tenant_id == "tenant-a", InventoryEntity.inventory_id == "INV-1"))
    inv2 = c2_session.scalar(select(InventoryEntity).where(InventoryEntity.tenant_id == "tenant-a", InventoryEntity.inventory_id == "INV-2"))
    assert inv1.in_transit_qty == 0
    assert inv2.in_transit_qty == 70
    assert inv2.planned_arrival_at.replace(tzinfo=timezone.utc).isoformat() == "2026-07-20T00:00:00+00:00"
    assert inv2.estimated_arrival_at.replace(tzinfo=timezone.utc).isoformat() == "2026-07-20T04:00:00+00:00"


def test_data_pages_keep_frontend_fields_and_tenant_filter(c2_session: Session):
    for tenant, suffix in (("tenant-a", "A"), ("tenant-b", "B")):
        upsert_entities(c2_session, tenant, "material", [{"material_id": "MAT-1", "material_name": f"物料{suffix}", "daily_consumption": 24, "standard_cost": 10}])
        upsert_entities(c2_session, tenant, "supplier", [{"supplier_id": "SUP-1", "supplier_name": f"供应商{suffix}"}])
        upsert_entities(c2_session, tenant, "customer", [{"customer_id": "CUS-1", "customer_name": f"客户{suffix}", "customer_level": "A"}])
        upsert_entities(c2_session, tenant, "supplier_material", [{"supplier_material_id": f"SM-{suffix}", "supplier_id": "SUP-1", "material_id": "MAT-1", "lead_time_hours": 48, "unit_cost": 9}])
        upsert_entities(c2_session, tenant, "order", [{"sales_order_id": "SO-1", "customer_id": "CUS-1", "promised_delivery_at": "2026-07-20", "order_amount": 100, "gross_profit": 20}])
        upsert_entities(c2_session, tenant, "inventory", [{"inventory_id": "INV-1", "material_id": "MAT-1", "warehouse_id": "WH-1", "available_qty": 48, "safety_stock_qty": 10}])
    c2_session.commit()
    expected = {
        "material": {"id", "name", "category", "stock", "safety", "cost"},
        "supplier": {"id", "name", "status", "leadTime", "supplierPrice", "relations"},
        "customer": {"id", "name", "customerLevel", "contract", "owner"},
        "order": {"id", "orderNo", "customer", "dueAt", "amount", "profit", "status"},
        "inventory": {"id", "warehouse", "material", "quantity", "supportHours", "status"},
    }
    context = AuthContext("u-a", "tenant-a", "A", "admin", ("data:view",))
    for resource_type, fields in expected.items():
        response = imports_settings.data_table(resource_type, context, c2_session)
        assert response["total"] == 1
        assert set(response["data"][0]) == fields
        assert "B" not in str(response)


def test_supplier_default_relation_is_deterministic_complete_and_tenant_scoped(c2_session: Session):
    c2_session.add_all([
        Material(id="mat-a-1", tenant_id="tenant-a", material_id="MAT-1", material_name="A物料1"),
        Material(id="mat-a-2", tenant_id="tenant-a", material_id="MAT-2", material_name="A物料2"),
        Material(id="mat-a-3", tenant_id="tenant-a", material_id="MAT-3", material_name="A物料3"),
        Material(id="mat-b-1", tenant_id="tenant-b", material_id="MAT-1", material_name="B私有物料"),
        SupplierEntity(id="supplier-a", tenant_id="tenant-a", supplier_id="SUP-SAME", supplier_name="A供应商", status="active"),
        SupplierEntity(id="supplier-b", tenant_id="tenant-b", supplier_id="SUP-SAME", supplier_name="B供应商", status="active"),
    ])
    c2_session.flush()
    # Deliberately insert in the opposite order of the product selection rule.
    c2_session.add_all([
        SupplierMaterial(id="sm-a-3", tenant_id="tenant-a", supplier_material_id="SM-A-3", supplier_id="SUP-SAME", material_id="MAT-3", qualified=False, supplier_rank=1, lead_time_hours=12, supplier_price=3, available_emergency_qty=30),
        SupplierMaterial(id="sm-a-2", tenant_id="tenant-a", supplier_material_id="SM-A-2", supplier_id="SUP-SAME", material_id="MAT-2", qualified=True, supplier_rank=3, lead_time_hours=72, supplier_price=20, available_emergency_qty=20),
        SupplierMaterial(id="sm-a-1", tenant_id="tenant-a", supplier_material_id="SM-A-1", supplier_id="SUP-SAME", material_id="MAT-1", qualified=True, supplier_rank=1, lead_time_hours=48, supplier_price=10, available_emergency_qty=10),
        SupplierMaterial(id="sm-b-1", tenant_id="tenant-b", supplier_material_id="SM-B-1", supplier_id="SUP-SAME", material_id="MAT-1", qualified=True, supplier_rank=0, lead_time_hours=1, supplier_price=999, available_emergency_qty=999),
    ])
    c2_session.commit()

    row = list_product_rows(c2_session, "tenant-a", "supplier")[0]
    assert row["leadTime"] == 2
    assert row["supplierPrice"] == 10
    assert [relation["supplierMaterialId"] for relation in row["relations"]] == ["SM-A-1", "SM-A-2", "SM-A-3"]
    assert [relation["isDefault"] for relation in row["relations"]] == [True, False, False]
    assert row["relations"][0] == {
        "supplierMaterialId": "SM-A-1",
        "materialId": "MAT-1",
        "materialName": "A物料1",
        "supplierRank": 1,
        "leadTimeHours": 48,
        "supplierPrice": 10,
        "availableEmergencyQty": 10,
        "qualified": True,
        "isDefault": True,
    }
    assert "B私有物料" not in str(row) and "999" not in str(row)


def test_import_history_public_contract_and_tenant_isolation(c2_session: Session):
    c2_session.add_all([
        ImportJob(
            id="job-enterprise-a", tenant_id="tenant-a", file_name="enterprise/csv", import_type="enterprise",
            status="succeeded", progress=100, options={"path": "secret/a.csv", "operator": "验收员A"},
            result={
                "sourceRows": 111460, "successRows": 111460, "rejectedRows": 0,
                "tableReports": [{"table": "materials", "sourceRows": 240, "successRows": 240, "rejectedRows": 0}],
            },
        ),
        ImportJob(
            id="job-enterprise-b", tenant_id="tenant-b", file_name="enterprise/csv", import_type="enterprise",
            status="succeeded", progress=100, options={"operator": "验收员B"},
            result={"sourceRows": 9, "successRows": 8, "rejectedRows": 1},
        ),
    ])
    c2_session.commit()
    context = AuthContext("u-a", "tenant-a", "A", "scm_lead", ("data:import",))

    response = imports_settings.import_history(context, c2_session)
    assert response["total"] == 1 and response["success"] is True
    job = response["data"][0]
    assert job["id"] == "job-enterprise-a" and job["operator"] == "验收员A"
    assert "path" not in job["options"]
    assert job["status"] == "succeeded"
    assert job["total"] == job["sourceRows"] == 111460
    assert job["success"] == job["successRows"] == 111460
    assert job["failed"] == job["rejectedRows"] == 0
    assert job["result"]["total"] == job["result"]["sourceRows"] == 111460
    assert job["result"]["success"] == job["result"]["successRows"] == 111460
    assert job["result"]["failed"] == job["result"]["rejectedRows"] == 0
    assert job["reports"] == job["result"]["reports"] == job["result"]["tableReports"]
    assert job["createdAt"] and job["updatedAt"]
    assert "job-enterprise-b" not in str(response) and "验收员B" not in str(response)
