"""Phase 5B / C2 第一批：实体表约束、tenant-aware 外键、租户隔离、映射 adapter 测试。

契约来源：codex_landing_spec/11_Phase5B_前置产出.md v2 §②③。
- 用独立 in-memory SQLite（StaticPool + PRAGMA foreign_keys=ON）确定性验证复合外键与部分唯一索引；
- 覆盖：租户内业务唯一键、跨租户同业务键隔离、tenant-aware FK 挡串租户、
  tenant_configs 单 active、映射幂等（二次不增行）、未知列→extra、敏感列拒绝、
  重命名/类型转换、订单头/行财务分离、运输 road→truck 边界、映射声明与模型一致。

Alembic upgrade/downgrade/upgrade 由迁移驱动单独实测（见 phase5b 交付记录），
本文件的 test_c2_migration_uses_explicit_operations 另做静态守卫。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.webapi.database import Base
from src.webapi import models  # noqa: F401  确保实体表注册进 metadata
from src.webapi.models import (
    CustomerEntity,
    Material,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    TenantConfig,
)
from src.webapi.entity_mapping import (
    activate_tenant_config,
    active_tenant_config,
    load_mapping,
    normalize_transport_mode,
    upsert_entities,
    validate_mapping,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _material(tenant: str, material_id: str, **kw) -> Material:
    return Material(id=f"m-{uuid.uuid4().hex}", tenant_id=tenant, material_id=material_id, **kw)


# ── 唯一约束与跨租户隔离 ───────────────────────────────────────────────────────

def test_business_key_unique_within_tenant_but_shared_across_tenants(db: Session):
    db.add(_material("t-a", "M1", daily_consumption=24.0))
    db.flush()
    # 同租户重复业务键 → 违约
    db.add(_material("t-a", "M1"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    # 不同租户可复用同一业务键
    db.add(_material("t-a", "M1", daily_consumption=24.0))
    db.add(_material("t-b", "M1", daily_consumption=48.0))
    db.flush()
    a = db.scalar(select(Material).where(Material.tenant_id == "t-a", Material.material_id == "M1"))
    b = db.scalar(select(Material).where(Material.tenant_id == "t-b", Material.material_id == "M1"))
    assert a.daily_consumption == 24.0 and b.daily_consumption == 48.0  # 数值严格分离


def test_tenant_aware_fk_blocks_cross_tenant_and_missing_parent(db: Session):
    db.add(_material("t-a", "M1"))
    db.add(SupplierEntity(id=f"s-{uuid.uuid4().hex}", tenant_id="t-a", supplier_id="S1"))
    db.flush()
    # 父存在于本租户 → 允许
    db.add(SupplierMaterial(id=f"sm-{uuid.uuid4().hex}", tenant_id="t-a", supplier_material_id="SM1", supplier_id="S1", material_id="M1"))
    db.flush()
    # 越权/串租户：t-b 引用只存在于 t-a 的父 → 复合外键(含 tenant_id)挡下
    db.add(SupplierMaterial(id=f"sm-{uuid.uuid4().hex}", tenant_id="t-b", supplier_material_id="SM2", supplier_id="S1", material_id="M1"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_sales_order_line_requires_same_tenant_parents(db: Session):
    db.add(_material("t-a", "M1"))
    db.add(CustomerEntity(id=f"c-{uuid.uuid4().hex}", tenant_id="t-a", customer_id="C1", customer_level="A"))
    db.flush()
    db.add(SalesOrder(id=f"o-{uuid.uuid4().hex}", tenant_id="t-a", sales_order_id="O1", customer_id="C1", gross_profit=100000.0, penalty_cost=20000.0))
    db.flush()
    # 行引用本租户订单+物料 → OK
    db.add(SalesOrderLine(id=f"ol-{uuid.uuid4().hex}", tenant_id="t-a", sales_order_line_id="OL1", sales_order_id="O1", line_no=1, material_id="M1", ordered_qty=5000.0))
    db.flush()
    # 跨租户引用订单 → 被 FK 挡下
    db.add(SalesOrderLine(id=f"ol-{uuid.uuid4().hex}", tenant_id="t-b", sales_order_line_id="OL2", sales_order_id="O1", line_no=1, material_id="M1", ordered_qty=1.0))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ── tenant_configs 单 active ──────────────────────────────────────────────────

def test_tenant_config_single_active_partial_unique_index(db: Session):
    db.add(TenantConfig(id=f"tc-{uuid.uuid4().hex}", tenant_id="t-a", config_type="thresholds", payload={"x": 1}, version=1, is_active=True))
    db.flush()
    # 同 (tenant, config_type) 第二个 active → 部分唯一索引违约
    db.add(TenantConfig(id=f"tc-{uuid.uuid4().hex}", tenant_id="t-a", config_type="thresholds", payload={"x": 2}, version=2, is_active=True))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_activate_tenant_config_deactivates_previous(db: Session):
    first = activate_tenant_config(db, "t-a", "thresholds", {"warn": 70}, source="expert")
    assert first.version == 1 and first.is_active is True
    second = activate_tenant_config(db, "t-a", "thresholds", {"warn": 60}, source="calibrated", approved_by="u-admin")
    assert second.version == 2 and second.is_active is True
    assert second.approved_by == "u-admin" and second.approved_at is not None
    actives = list(db.scalars(select(TenantConfig).where(TenantConfig.tenant_id == "t-a", TenantConfig.config_type == "thresholds", TenantConfig.is_active.is_(True))))
    assert len(actives) == 1 and actives[0].payload == {"warn": 60}
    assert active_tenant_config(db, "t-a", "thresholds").version == 2
    # 另一租户不受影响
    other = activate_tenant_config(db, "t-b", "thresholds", {"warn": 90})
    assert other.version == 1 and active_tenant_config(db, "t-b", "thresholds").payload == {"warn": 90}


# ── 映射 adapter ─────────────────────────────────────────────────────────────

def test_mapping_spec_matches_entity_models():
    assert validate_mapping(load_mapping()) == []


def test_mapping_renames_conversions_and_unknown_to_extra(db: Session):
    spec = load_mapping()
    rows = [{
        "material_id": "M1", "material_name": "核心控制芯片", "category": "IC", "unit": "件",
        "daily_consumption": "240", "standard_cost": "12.5", "criticality": "critical",
        "sales_price": "20", "safety_stock_days": "3",
    }]
    result = upsert_entities(db, "t-a", "material", rows, spec)
    assert result["inserted"] == 1 and result["rejected"] == []
    m = db.scalar(select(Material).where(Material.tenant_id == "t-a", Material.material_id == "M1"))
    assert m.unit_cost == 12.5            # standard_cost → unit_cost 重命名
    assert m.is_critical is True          # criticality → is_critical bool_level
    assert m.daily_consumption == 240.0   # 字符串→float 类型转换
    assert m.extra.get("sales_price") == "20" and m.extra.get("safety_stock_days") == "3"

    # 2026-07-18 C2 批准规格：敏感列不是“丢弃列后继续导入”，而是整行拒绝且不产生实体。
    sensitive = upsert_entities(db, "t-a", "material", [{
        "material_id": "M2", "material_name": "禁止落库", "password": "should-reject",
    }], spec)
    assert sensitive["inserted"] == 0 and len(sensitive["rejected"]) == 1
    assert "安全敏感列" in sensitive["rejected"][0]["reason"]
    assert db.scalar(select(Material).where(Material.tenant_id == "t-a", Material.material_id == "M2")) is None


def test_supplier_material_price_rename(db: Session):
    spec = load_mapping()
    db.add(_material("t-a", "M1"))
    db.add(SupplierEntity(id=f"s-{uuid.uuid4().hex}", tenant_id="t-a", supplier_id="S1"))
    db.flush()
    rows = [{"supplier_material_id": "SM1", "supplier_id": "S1", "material_id": "M1",
             "supplier_rank": "1", "lead_time_hours": "36", "available_emergency_qty": "4200",
             "emergency_cost_multiplier": "1.45", "unit_cost": "88.0", "qualified": "1"}]
    upsert_entities(db, "t-a", "supplier_material", rows, spec)
    sm = db.scalar(select(SupplierMaterial).where(SupplierMaterial.tenant_id == "t-a", SupplierMaterial.supplier_material_id == "SM1"))
    assert sm.supplier_price == 88.0                  # CSV unit_cost → 实体 supplier_price
    assert sm.emergency_cost_multiplier == 1.45       # cost_multiplier 直存，非推导
    assert sm.qualified is True


def test_order_header_financial_kept_once_lines_only_qty(db: Session):
    spec = load_mapping()
    db.add(CustomerEntity(id=f"c-{uuid.uuid4().hex}", tenant_id="t-a", customer_id="C1", customer_level="A"))
    db.add(_material("t-a", "M1"))
    db.flush()
    upsert_entities(db, "t-a", "order", [{
        "sales_order_id": "O1", "customer_id": "C1", "order_status": "open",
        "promised_delivery_at": "2026-07-20T08:00:00Z", "order_amount": "600000",
        "gross_profit": "150000", "penalty_cost": "30000",
    }], spec)
    upsert_entities(db, "t-a", "order_line", [
        {"sales_order_line_id": "OL1", "sales_order_id": "O1", "line_no": "1", "material_id": "M1", "ordered_qty": "3000", "unit_price": "100"},
        {"sales_order_line_id": "OL2", "sales_order_id": "O1", "line_no": "2", "material_id": "M1", "ordered_qty": "2000", "unit_price": "100"},
    ], spec)
    order = db.scalar(select(SalesOrder).where(SalesOrder.tenant_id == "t-a", SalesOrder.sales_order_id == "O1"))
    assert order.gross_profit == 150000.0 and order.penalty_cost == 30000.0  # 头级取一次
    assert isinstance(order.promised_delivery_at, datetime) and order.promised_delivery_at.tzinfo is not None
    # 行模型结构上没有订单头财务列，杜绝按行复制累计
    line_cols = {c.name for c in SalesOrderLine.__table__.columns}
    assert "gross_profit" not in line_cols and "penalty_cost" not in line_cols
    lines = list(db.scalars(select(SalesOrderLine).where(SalesOrderLine.tenant_id == "t-a", SalesOrderLine.sales_order_id == "O1")))
    assert sorted(l.ordered_qty for l in lines) == [2000.0, 3000.0]


def test_mapping_idempotent_second_run_no_new_rows(db: Session):
    spec = load_mapping()
    rows = [{"material_id": "M1", "daily_consumption": "24", "standard_cost": "10"},
            {"material_id": "M2", "daily_consumption": "48", "standard_cost": "20"}]
    first = upsert_entities(db, "t-a", "material", rows, spec)
    assert first["inserted"] == 2 and first["updated"] == 0
    before = db.scalar(select(func.count()).select_from(Material))
    # 二次执行同一映射函数：行数不增长，全部走 update
    rows[0]["standard_cost"] = "11"
    second = upsert_entities(db, "t-a", "material", rows, spec)
    assert second["inserted"] == 0 and second["updated"] == 2
    after = db.scalar(select(func.count()).select_from(Material))
    assert before == after == 2
    assert db.scalar(select(Material).where(Material.tenant_id == "t-a", Material.material_id == "M1")).unit_cost == 11.0


def test_mapping_missing_business_key_is_rejected_not_guessed(db: Session):
    spec = load_mapping()
    rows = [{"material_name": "无编号物料", "daily_consumption": "24"}]  # 缺 material_id
    result = upsert_entities(db, "t-a", "material", rows, spec)
    assert result["inserted"] == 0
    assert result["rejected"] and "缺业务主键" in result["rejected"][0]["reason"]
    assert db.scalar(select(func.count()).select_from(Material)) == 0  # 不猜值、不落库


def test_mapping_upsert_is_tenant_scoped(db: Session):
    spec = load_mapping()
    upsert_entities(db, "t-a", "material", [{"material_id": "M1", "daily_consumption": "24"}], spec)
    upsert_entities(db, "t-b", "material", [{"material_id": "M1", "daily_consumption": "48"}], spec)
    # A 的再次 upsert 不得改动 B 的同业务键行
    upsert_entities(db, "t-a", "material", [{"material_id": "M1", "daily_consumption": "36"}], spec)
    assert db.scalar(select(Material).where(Material.tenant_id == "t-a", Material.material_id == "M1")).daily_consumption == 36.0
    assert db.scalar(select(Material).where(Material.tenant_id == "t-b", Material.material_id == "M1")).daily_consumption == 48.0


def test_transport_mode_boundary_maps_road_to_truck():
    assert normalize_transport_mode("road") == "truck"
    assert normalize_transport_mode("公路") == "truck"
    for canonical in ("air", "truck", "rail", "sea"):
        assert normalize_transport_mode(canonical) == canonical
    assert normalize_transport_mode(None) is None


# ── 迁移静态守卫（可脱库运行）──────────────────────────────────────────────────

def test_c2_migration_uses_explicit_operations():
    path = Path("alembic/versions/20260717_0004_phase5b_c2_entities.py")
    source = path.read_text(encoding="utf-8")
    assert 'down_revision = "20260713_0003"' in source
    assert "metadata.create_all" not in source
    for table in ("materials", "suppliers", "supplier_materials", "customers",
                  "sales_orders", "sales_order_lines", "inventory", "tenant_configs"):
        assert f'op.create_table(\n        "{table}"' in source or f'"{table}"' in source
        assert f'op.drop_table("{table}")' in source
    assert "uq_tenant_config_active" in source          # 部分唯一索引
    assert "ForeignKeyConstraint" in source             # tenant-aware 复合外键
