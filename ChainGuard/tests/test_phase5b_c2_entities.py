from __future__ import annotations

import os
import csv
import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.webapi.database import Base
from src.webapi.entity_mapping import (
    MappingValidationError,
    activate_tenant_config,
    active_tenant_config,
    entity_to_product_row,
    load_mapping,
    map_row,
    normalize_transport_options,
    upsert_entities,
    validate_mapping,
)
from src.webapi.models import Material, TenantConfig


ROOT = Path(__file__).resolve().parents[1]
NEW_TABLES = {
    "materials",
    "suppliers",
    "supplier_materials",
    "customers",
    "sales_orders",
    "sales_order_lines",
    "inventory",
    "tenant_configs",
}


def _unique_db_path(prefix: str) -> Path:
    root = ROOT / "test_tmp"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{prefix}-{os.getpid()}-{uuid.uuid4().hex}.db"


def _alembic_head_revision() -> str:
    # Derived, not pinned: every new migration would otherwise break this test.
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"expected a single alembic head, got {heads}"
    return heads[0]


def _run_alembic(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def _best_effort_unlink(path: Path) -> None:
    # Windows may retain a just-closed SQLite handle briefly; cleanup must not
    # hide the migration assertion result.
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture
def entity_session():
    database = _unique_db_path("phase5b-c2-orm")
    engine = create_engine(f"sqlite:///{database.as_posix()}")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()
    engine.dispose()
    _best_effort_unlink(database)


def test_migration_upgrade_downgrade_upgrade_and_sqlite_constraints():
    database = _unique_db_path("phase5b-c2-migration")
    try:
        first = _run_alembic(database, "upgrade", "head")
        assert "Running upgrade 20260713_0003 -> 20260717_0004" in first.stderr
        assert "Running upgrade 20260717_0004 -> 20260718_0005" in first.stderr
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert NEW_TABLES <= tables
            fk_rows = connection.execute("PRAGMA foreign_key_list('supplier_materials')").fetchall()
            assert {(row[2], row[3], row[4]) for row in fk_rows} == {
                ("suppliers", "tenant_id", "tenant_id"),
                ("suppliers", "supplier_id", "supplier_id"),
                ("materials", "tenant_id", "tenant_id"),
                ("materials", "material_id", "material_id"),
            }
            connection.execute("INSERT INTO materials (id, tenant_id, material_id) VALUES ('m-b', 'tenant-b', 'MAT-1')")
            connection.execute("INSERT INTO suppliers (id, tenant_id, supplier_id) VALUES ('s-a', 'tenant-a', 'SUP-1')")
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO supplier_materials "
                    "(id, tenant_id, supplier_material_id, supplier_id, material_id) "
                    "VALUES ('sm-a', 'tenant-a', 'SM-1', 'SUP-1', 'MAT-1')"
                )
            connection.execute("INSERT INTO materials (id, tenant_id, material_id) VALUES ('m-a', 'tenant-a', 'MAT-1')")
            connection.execute("INSERT INTO suppliers (id, tenant_id, supplier_id) VALUES ('s-b', 'tenant-b', 'SUP-B')")
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO supplier_materials "
                    "(id, tenant_id, supplier_material_id, supplier_id, material_id) "
                    "VALUES ('sm-a2', 'tenant-a', 'SM-2', 'SUP-B', 'MAT-1')"
                )
            connection.execute("INSERT INTO customers (id, tenant_id, customer_id) VALUES ('c-b', 'tenant-b', 'CUS-B')")
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO sales_orders (id, tenant_id, sales_order_id, customer_id) "
                    "VALUES ('so-a', 'tenant-a', 'SO-A', 'CUS-B')"
                )
            connection.execute("INSERT INTO customers (id, tenant_id, customer_id) VALUES ('c-a', 'tenant-a', 'CUS-A')")
            connection.execute(
                "INSERT INTO sales_orders (id, tenant_id, sales_order_id, customer_id) "
                "VALUES ('so-b', 'tenant-b', 'SO-B', 'CUS-B')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO sales_order_lines "
                    "(id, tenant_id, sales_order_line_id, sales_order_id, line_no, material_id) "
                    "VALUES ('sol-a', 'tenant-a', 'SOL-A', 'SO-B', 1, 'MAT-1')"
                )
            connection.execute("INSERT INTO materials (id, tenant_id, material_id) VALUES ('m-b2', 'tenant-b', 'MAT-B')")
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO inventory (id, tenant_id, inventory_id, material_id) "
                    "VALUES ('inv-a', 'tenant-a', 'INV-A', 'MAT-B')"
                )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO materials (id, tenant_id, material_id) VALUES ('m-a2', 'tenant-a', 'MAT-1')")
            connection.execute(
                "INSERT INTO tenant_configs (id, tenant_id, config_type, payload, version, source, is_active) "
                "VALUES ('cfg-1', 'tenant-a', 'thresholds', '{}', 1, 'expert', 1)"
            )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO tenant_configs (id, tenant_id, config_type, payload, version, source, is_active) "
                    "VALUES ('cfg-2', 'tenant-a', 'thresholds', '{}', 2, 'expert', 1)"
                )
            connection.commit()

        down = _run_alembic(database, "downgrade", "20260713_0003")
        assert "Running downgrade 20260717_0004 -> 20260713_0003" in down.stderr
        with sqlite3.connect(database) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert not (NEW_TABLES & tables)
            assert "data_records" in tables
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20260713_0003"

        second = _run_alembic(database, "upgrade", "head")
        assert "Running upgrade 20260713_0003 -> 20260717_0004" in second.stderr
        assert "Running upgrade 20260717_0004 -> 20260718_0005" in second.stderr
        with sqlite3.connect(database) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert NEW_TABLES <= tables
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == _alembic_head_revision()
    finally:
        _best_effort_unlink(database)


def test_postgresql_ddl_contains_composite_fks_and_partial_active_index():
    migration_path = ROOT / "alembic" / "versions" / "20260717_0004_phase5b_c2_entities.py"
    module_spec = importlib.util.spec_from_file_location("phase5b_c2_0004", migration_path)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    output = io.StringIO()
    context = MigrationContext.configure(url="postgresql://", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
    ddl = output.getvalue()
    assert "FOREIGN KEY(tenant_id, supplier_id) REFERENCES suppliers (tenant_id, supplier_id)" in ddl
    assert "FOREIGN KEY(tenant_id, material_id) REFERENCES materials (tenant_id, material_id)" in ddl
    assert "FOREIGN KEY(tenant_id, customer_id) REFERENCES customers (tenant_id, customer_id)" in ddl
    assert "FOREIGN KEY(tenant_id, sales_order_id) REFERENCES sales_orders (tenant_id, sales_order_id)" in ddl
    assert "CREATE UNIQUE INDEX uq_tenant_config_active ON tenant_configs (tenant_id, config_type) WHERE is_active" in ddl


def test_0005_offline_mode_has_an_explicit_fail_fast_guard():
    source = (ROOT / "alembic" / "versions" / "20260718_0005_phase5b_c2_import_execution.py").read_text(encoding="utf-8")
    assert "op.get_context().as_sql" in source
    assert "requires online migration mode" in source
    assert "from src." not in source
    assert "import yaml" not in source
    assert "sqlalchemy.orm" not in source
    assert "_frozen_backfill_data_records(op.get_bind())" in source


def test_0005_frozen_backfill_migrates_legacy_rows_without_application_imports():
    database = _unique_db_path("phase5b-c2-frozen-backfill")
    timestamp = "2026-07-18 08:00:00+00:00"
    records = [
        ("legacy-material", "tenant-a", "material", "芯片", {"materialId": "MAT-1", "dailyConsumption": 24, "cost": 12.5}),
        ("legacy-secret", "tenant-a", "material", "敏感物料", {"materialId": "MAT-SECRET", "api_key": "must-reject"}),
        ("legacy-customer", "tenant-a", "customer", "客户A", {"customerId": "CUS-1", "customerLevel": "A"}),
        ("legacy-order", "tenant-a", "order", "订单A", {"orderNo": "SO-1", "customerId": "CUS-1", "amount": 1000, "profit": 200}),
        ("legacy-inventory", "tenant-a", "inventory", "库存A", {"inventoryId": "INV-1", "materialId": "MAT-1", "stock": 80, "safety": 20}),
        ("legacy-bad-fk", "tenant-a", "inventory", "坏库存", {"inventoryId": "INV-X", "materialId": "MAT-NOT-FOUND"}),
    ]
    try:
        _run_alembic(database, "upgrade", "20260713_0003")
        with sqlite3.connect(database) as connection:
            connection.executemany(
                "INSERT INTO data_records "
                "(id, tenant_id, resource_type, name, payload, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (record_id, tenant_id, resource_type, name, json.dumps(payload, ensure_ascii=False), timestamp, timestamp)
                    for record_id, tenant_id, resource_type, name, payload in records
                ],
            )
            connection.commit()

        _run_alembic(database, "upgrade", "20260718_0005")
        with sqlite3.connect(database) as connection:
            material = connection.execute(
                "SELECT material_name, daily_consumption, unit_cost FROM materials "
                "WHERE tenant_id='tenant-a' AND material_id='MAT-1'"
            ).fetchone()
            assert material == ("芯片", 24.0, 12.5)
            assert connection.execute(
                "SELECT customer_level FROM customers WHERE tenant_id='tenant-a' AND customer_id='CUS-1'"
            ).fetchone() == ("A",)
            assert connection.execute(
                "SELECT order_amount, gross_profit FROM sales_orders WHERE tenant_id='tenant-a' AND sales_order_id='SO-1'"
            ).fetchone() == (1000.0, 200.0)
            assert connection.execute(
                "SELECT on_hand_qty, safety_stock_qty FROM inventory WHERE tenant_id='tenant-a' AND inventory_id='INV-1'"
            ).fetchone() == (80.0, 20.0)
            rejection_ids = {
                row[0] for row in connection.execute(
                    "SELECT source_record_id FROM import_rejections WHERE tenant_id='tenant-a'"
                )
            }
            assert rejection_ids == {"legacy-secret", "legacy-bad-fk"}
            assert connection.execute("SELECT COUNT(*) FROM data_records").fetchone()[0] == len(records)
    finally:
        _best_effort_unlink(database)


def test_mapping_template_is_complete_and_finance_stays_on_order_header():
    spec = load_mapping()
    assert validate_mapping(spec) == []
    assert {rule["target_table"] for rule in spec["resources"].values()} == NEW_TABLES - {"tenant_configs"}
    for rule in spec["resources"].values():
        assert {"source_table", "source_key", "target_table", "target_key", "unknown_columns", "aggregation"} <= set(rule)
    assert {"order_amount", "gross_profit", "penalty_cost"} <= set(spec["resources"]["order"]["converts"])
    line_rule = spec["resources"]["order_line"]
    assert not ({"order_amount", "gross_profit", "penalty_cost"} & (set(line_rule["fields"].values()) | set(line_rule["converts"])))
    assert set(line_rule["forbidden_columns"]) == {"order_amount", "gross_profit", "penalty_cost"}


def test_real_enterprise_csv_headers_map_for_all_seven_resources():
    spec = load_mapping()
    csv_root = ROOT / "demo_assets" / "enterprise" / "csv"
    sources = {
        "material": "materials.csv",
        "supplier": "suppliers.csv",
        "supplier_material": "supplier_materials.csv",
        "customer": "customers.csv",
        "order": "sales_orders.csv",
        "order_line": "sales_order_lines.csv",
        "inventory": "inventory.csv",
    }
    mapped = {}
    for resource_type, filename in sources.items():
        with (csv_root / filename).open(encoding="utf-8-sig", newline="") as handle:
            source_row = next(csv.DictReader(handle))
        target, reason = map_row(resource_type, source_row, spec)
        assert reason is None, (resource_type, reason)
        assert target is not None
        mapped[resource_type] = target
    assert mapped["material"]["unit_cost"] is not None
    assert mapped["supplier_material"]["emergency_cost_multiplier"] is not None
    assert {"order_amount", "gross_profit", "penalty_cost"} <= set(mapped["order"])
    assert not ({"order_amount", "gross_profit", "penalty_cost"} & set(mapped["order_line"]))


def test_mapping_validator_rejects_incomplete_or_model_divergent_rules():
    spec = load_mapping()
    broken = {**spec, "resources": {key: dict(value) for key, value in spec["resources"].items()}}
    broken["resources"]["material"].pop("source_table")
    broken["resources"]["order"]["target_key"] = "not_a_column"
    problems = validate_mapping(broken)
    assert any("source_table" in problem for problem in problems)
    assert any("not_a_column" in problem for problem in problems)
    with pytest.raises(MappingValidationError):
        upsert_entities(None, "tenant-a", "material", [], broken)  # type: ignore[arg-type]


def test_map_row_converts_units_times_unknowns_and_rejects_sensitive_or_wrong_finance():
    spec = load_mapping()
    material, reason = map_row(
        "material",
        {"material_id": "MAT-1", "material_name": "芯片", "standard_cost": "12.5", "daily_consumption": "240", "criticality": "A", "quality_score": 98},
        spec,
    )
    assert reason is None
    assert material == {
        "material_id": "MAT-1",
        "material_name": "芯片",
        "category": None,
        "unit": None,
        "daily_consumption": 240.0,
        "unit_cost": 12.5,
        "is_critical": True,
        "extra": {"quality_score": 98},
    }
    order, reason = map_row(
        "order",
        {"sales_order_id": "SO-1", "customer_id": "CUS-1", "promised_delivery_at": "2026-07-17T08:00:00+08:00", "gross_profit": "30", "penalty_cost": "4"},
        spec,
    )
    assert reason is None
    assert order["promised_delivery_at"].isoformat() == "2026-07-17T00:00:00+00:00"
    assert order["gross_profit"] == 30.0 and order["penalty_cost"] == 4.0

    rejected, reason = map_row("material", {"material_id": "MAT-2", "api_key": "secret-value"}, spec)
    assert rejected is None and "安全敏感列" in reason
    rejected, reason = map_row(
        "order_line",
        {"sales_order_line_id": "SOL-1", "sales_order_id": "SO-1", "line_no": 1, "material_id": "MAT-1", "gross_profit": 100},
        spec,
    )
    assert rejected is None and "不允许" in reason


def test_tenant_scoped_upsert_is_idempotent_and_same_business_key_isolated(entity_session: Session):
    row = {"material_id": "MAT-SAME", "material_name": "租户A", "standard_cost": 10, "daily_consumption": 24}
    first = upsert_entities(entity_session, "tenant-a", "material", [row])
    second = upsert_entities(entity_session, "tenant-a", "material", [{**row, "material_name": "租户A更新"}])
    other = upsert_entities(entity_session, "tenant-b", "material", [{**row, "material_name": "租户B"}])
    entity_session.commit()
    assert first == {"inserted": 1, "updated": 0, "rejected": []}
    assert second == {"inserted": 0, "updated": 1, "rejected": []}
    assert other == {"inserted": 1, "updated": 0, "rejected": []}
    rows_a = list(entity_session.scalars(select(Material).where(Material.tenant_id == "tenant-a")))
    rows_b = list(entity_session.scalars(select(Material).where(Material.tenant_id == "tenant-b")))
    assert [(row.material_id, row.material_name) for row in rows_a] == [("MAT-SAME", "租户A更新")]
    assert [(row.material_id, row.material_name) for row in rows_b] == [("MAT-SAME", "租户B")]


def test_missing_key_rejection_does_not_create_a_row(entity_session: Session):
    result = upsert_entities(entity_session, "tenant-a", "material", [{"material_name": "无编号"}])
    assert result["inserted"] == result["updated"] == 0
    assert len(result["rejected"]) == 1 and "缺业务主键" in result["rejected"][0]["reason"]
    assert list(entity_session.scalars(select(Material))) == []


def test_tenant_config_single_active_and_atomic_activation(entity_session: Session):
    first = activate_tenant_config(entity_session, "tenant-a", "thresholds", {"high": 80}, source="expert")
    second = activate_tenant_config(entity_session, "tenant-a", "thresholds", {"high": 85}, approved_by="u-admin")
    other = activate_tenant_config(entity_session, "tenant-b", "thresholds", {"high": 90}, source="expert")
    entity_session.commit()
    assert first.is_active is False
    assert second.version == 2 and second.is_active is True and second.source == "calibrated"
    assert other.version == 1 and other.is_active is True
    assert active_tenant_config(entity_session, "tenant-a", "thresholds").id == second.id

    entity_session.add(TenantConfig(id="cfg-conflict", tenant_id="tenant-a", config_type="thresholds", payload={}, version=3, source="expert", is_active=True))
    with pytest.raises(IntegrityError):
        entity_session.commit()
    entity_session.rollback()


def test_transport_boundary_uses_truck_and_requires_cost_multiplier():
    normalized = normalize_transport_options([{"mode": "road", "estimated_hours": "12", "cost_multiplier": "1.4", "cost_level": "中"}])
    assert normalized == [{"mode": "truck", "estimated_hours": 12.0, "cost_multiplier": 1.4, "cost_level": "中"}]
    with pytest.raises(ValueError, match="cost_multiplier"):
        normalize_transport_options([{"mode": "air", "cost_level": "高"}])
    with pytest.raises(ValueError, match="unsupported transport mode"):
        normalize_transport_options([{"mode": "road_v2", "cost_multiplier": 1.0}])


def test_product_row_adapter_preserves_existing_page_field_names():
    material = entity_to_product_row(
        "material",
        {"material_id": "MAT-1", "material_name": "芯片", "category": "IC", "unit_cost": 12},
        related={"inventory": [{"on_hand_qty": 30, "safety_stock_qty": 10}]},
    )
    assert material == {"id": "MAT-1", "name": "芯片", "category": "IC", "stock": 30.0, "safety": 10.0, "cost": 12}
    supplier = entity_to_product_row(
        "supplier",
        {"supplier_id": "SUP-1", "supplier_name": "供方甲", "status": "active"},
        related={"supplier_materials": [{"lead_time_hours": 48, "supplier_price": 9.5}]},
    )
    assert {"id", "name", "status", "leadTime", "supplierPrice", "relations"} == set(supplier)
    assert supplier["leadTime"] == 2.0 and supplier["supplierPrice"] == 9.5
    customer = entity_to_product_row(
        "customer",
        {"customer_id": "CUS-1", "customer_name": "客户甲", "customer_level": "A", "contract": "年度合同", "owner": "张三"},
    )
    assert customer == {"id": "CUS-1", "name": "客户甲", "customerLevel": "A", "contract": "年度合同", "owner": "张三"}
    order = entity_to_product_row(
        "order",
        {"sales_order_id": "SO-1", "customer_id": "CUS-1", "promised_delivery_at": "2026-07-18", "order_amount": 100, "gross_profit": 30, "order_status": "pending"},
        related={"customer": {"customer_name": "客户甲"}},
    )
    assert {"id", "orderNo", "customer", "dueAt", "amount", "profit", "status"} == set(order)
    inventory = entity_to_product_row(
        "inventory",
        {"inventory_id": "INV-1", "warehouse_id": "WH-1", "available_qty": 48, "material_id": "MAT-1"},
        related={"material": {"material_name": "芯片", "daily_consumption": 24}, "status": "normal"},
    )
    assert inventory == {"id": "INV-1", "warehouse": "WH-1", "material": "芯片", "quantity": 48, "supportHours": 48.0, "status": "normal"}


def test_multiple_supplier_relations_select_stable_default_and_keep_all_details():
    row = entity_to_product_row(
        "supplier",
        {"supplier_id": "SUP-1", "supplier_name": "供方甲", "status": "active"},
        related={"supplier_materials": [
            {"supplier_material_id": "SM-2", "material_id": "MAT-2", "qualified": True, "supplier_rank": 2, "lead_time_hours": 72, "supplier_price": 20},
            {"supplier_material_id": "SM-3", "material_id": "MAT-3", "qualified": False, "supplier_rank": 1, "lead_time_hours": 12, "supplier_price": 5},
            {"supplier_material_id": "SM-1", "material_id": "MAT-1", "qualified": True, "supplier_rank": 1, "lead_time_hours": 24, "supplier_price": 10},
        ]},
    )
    # 2026-07-18 C2 产品验收规则：合格优先、排名最小，再按业务键稳定选择默认主供。
    assert row["leadTime"] == 1 and row["supplierPrice"] == 10
    assert [relation["supplierMaterialId"] for relation in row["relations"]] == ["SM-1", "SM-2", "SM-3"]
    assert [relation["isDefault"] for relation in row["relations"]] == [True, False, False]
