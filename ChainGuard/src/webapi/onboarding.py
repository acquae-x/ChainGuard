"""C3 empty-tenant guidance: derive truth from C2 entities, never client mock state."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import AuthContext
from .entity_import import import_entity_rows
from .models import (
    CustomerEntity,
    ImportJob,
    InventoryEntity,
    Material,
    OnboardingState,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    Tenant,
)
from .repository import add_audit, serialize


DEMO_SOURCE = "onboarding_demo"
ENTITY_MODELS = {
    "material": Material,
    "supplier": SupplierEntity,
    "supplierMaterial": SupplierMaterial,
    "customer": CustomerEntity,
    "order": SalesOrder,
    "orderLine": SalesOrderLine,
    "inventory": InventoryEntity,
}
DECISION_REQUIRED = ("material", "supplier", "supplierMaterial", "order", "orderLine", "inventory")


def _is_demo_row(item: Any) -> bool:
    extra = getattr(item, "extra", None)
    return isinstance(extra, dict) and extra.get("onboardingDataSource") == DEMO_SOURCE


def _rows(db: Session, tenant_id: str, model: type[Any]) -> list[Any]:
    return list(db.scalars(select(model).where(model.tenant_id == tenant_id)).all())


def entity_summary(db: Session, tenant_id: str) -> dict[str, Any]:
    """Return current-tenant-only counts plus a real/demo origin split.

    The split is intentionally evaluated from persisted entity metadata instead
    of a tenant boolean: old C2 data without a C3 source marker is real data.
    """

    counts: dict[str, int] = {}
    real_counts: dict[str, int] = {}
    demo_counts: dict[str, int] = {}
    for name, model in ENTITY_MODELS.items():
        records = _rows(db, tenant_id, model)
        counts[name] = len(records)
        demo_counts[name] = sum(1 for item in records if _is_demo_row(item))
        real_counts[name] = counts[name] - demo_counts[name]
    has_any = any(counts.values())
    has_real = any(real_counts.values())
    decision_ready = all(real_counts[name] > 0 for name in DECISION_REQUIRED)
    return {
        "counts": counts,
        "realCounts": real_counts,
        "demoCounts": demo_counts,
        "isEmpty": not has_any,
        "hasBusinessData": has_any,
        "hasRealData": has_real,
        "hasDemoData": any(demo_counts.values()),
        "decisionReady": decision_ready,
    }


def _latest_imports(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    rows = list(db.scalars(
        select(ImportJob).where(ImportJob.tenant_id == tenant_id).order_by(ImportJob.created_at.desc()).limit(5)
    ).all())
    return [serialize(item) for item in rows]


def onboarding_status(db: Session, tenant_id: str) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise LookupError("tenant not found")
    summary = entity_summary(db, tenant_id)
    state = db.scalar(select(OnboardingState).where(OnboardingState.tenant_id == tenant_id))
    if summary["isEmpty"]:
        phase = "empty"
    elif summary["hasRealData"] and summary["decisionReady"]:
        phase = "ready"
    elif summary["hasDemoData"] and not summary["hasRealData"]:
        phase = "demo_ready"
    else:
        phase = "preparing"
    return {
        "phase": phase,
        "guideVisible": summary["isEmpty"],
        "canInjectDemo": summary["isEmpty"],
        "entitySummary": summary,
        "state": {
            "lastStep": state.last_step if state else "welcome",
            "dismissed": state.dismissed if state else False,
            "progress": state.progress if state else {},
        },
        "recommendedData": [
            {"type": "material", "label": "物料主数据", "required": True, "template": "物料标准模板", "fields": ["material_id", "material_name", "daily_consumption", "standard_cost"]},
            {"type": "supplier", "label": "供应商与供料关系", "required": True, "template": "供应商/供料关系模板", "fields": ["supplier_id", "supplier_name", "material_id", "lead_time_hours"]},
            {"type": "inventory", "label": "库存", "required": True, "template": "库存标准模板", "fields": ["inventory_id", "material_id", "available_qty", "safety_stock_qty"]},
            {"type": "customer", "label": "客户与订单", "required": True, "template": "客户/订单模板", "fields": ["customer_id", "sales_order_id", "material_id", "ordered_qty", "promised_delivery_at"]},
        ],
        "recommendedOrder": ["material", "supplier", "supplier_material", "inventory", "customer", "order", "order_line"],
        "imports": _latest_imports(db, tenant_id),
    }


def activate_tenant_after_business_data(db: Session, tenant_id: str) -> None:
    """Registration status is a UX hint only; promote after any C2 entity lands."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is not None and entity_summary(db, tenant_id)["hasBusinessData"]:
        tenant.status = "active"


def save_onboarding_progress(db: Session, ctx: AuthContext, values: dict[str, Any]) -> dict[str, Any]:
    item = db.scalar(select(OnboardingState).where(OnboardingState.tenant_id == ctx.tenant_id))
    if item is None:
        item = OnboardingState(id=f"onboarding-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id)
        db.add(item)
    step = str(values.get("lastStep") or values.get("step") or item.last_step or "welcome")
    item.last_step = step[:40]
    item.dismissed = bool(values.get("dismissed", item.dismissed))
    incoming = values.get("progress")
    if isinstance(incoming, dict):
        item.progress = {**(item.progress or {}), **incoming}
    db.flush()
    return onboarding_status(db, ctx.tenant_id)


def _demo_rows(now: datetime) -> dict[str, list[dict[str, Any]]]:
    origin = {"onboardingDataSource": DEMO_SOURCE, "onboardingLabel": "演示数据", "dataset": "starter-v1"}
    arrival = (now + timedelta(hours=18)).isoformat()
    due = (now + timedelta(days=3)).isoformat()
    return {
        "material": [{"material_id": "DEMO-MCU-A9", "material_name": "演示 MCU-A9", "category": "芯片", "unit": "件", "daily_consumption": 240, "standard_cost": 12.5, "criticality": "critical", **origin}],
        "supplier": [
            {"supplier_id": "DEMO-SUP-PRIMARY", "supplier_name": "演示主供", "region": "上海", "status": "active", "reliability_score": 82, **origin},
            {"supplier_id": "DEMO-SUP-BACKUP", "supplier_name": "演示备供", "region": "苏州", "status": "active", "reliability_score": 91, **origin},
        ],
        "supplier_material": [
            {"supplier_material_id": "DEMO-REL-1", "supplier_id": "DEMO-SUP-PRIMARY", "material_id": "DEMO-MCU-A9", "qualified": True, "supplier_rank": 1, "lead_time_hours": 72, "available_emergency_qty": 1800, "emergency_cost_multiplier": 1.15, "unit_cost": 13, **origin},
            {"supplier_material_id": "DEMO-REL-2", "supplier_id": "DEMO-SUP-BACKUP", "material_id": "DEMO-MCU-A9", "qualified": True, "supplier_rank": 2, "lead_time_hours": 48, "available_emergency_qty": 1200, "emergency_cost_multiplier": 1.3, "unit_cost": 16, **origin},
        ],
        "customer": [{"customer_id": "DEMO-CUS-A", "customer_name": "演示重点客户", "customer_level": "A", "region": "华东", "contract": "演示合同", "owner": "演示销售", **origin}],
        "order": [{"sales_order_id": "DEMO-SO-001", "customer_id": "DEMO-CUS-A", "order_status": "pending", "promised_delivery_at": due, "order_amount": 120000, "gross_profit": 30000, "penalty_cost": 24000, **origin}],
        "order_line": [{"sales_order_line_id": "DEMO-SOL-1", "sales_order_id": "DEMO-SO-001", "line_no": 1, "material_id": "DEMO-MCU-A9", "ordered_qty": 900, "unit_price": 133.33, **origin}],
        "inventory": [{"inventory_id": "DEMO-INV-1", "material_id": "DEMO-MCU-A9", "warehouse_id": "DEMO-WH-1", "warehouse_name": "演示上海仓", "on_hand_qty": 480, "available_qty": 420, "safety_stock_qty": 600, "in_transit_qty": 500, "planned_arrival_at": arrival, "estimated_arrival_at": arrival, **origin}],
    }


def inject_demo_dataset(db: Session, ctx: AuthContext) -> dict[str, Any]:
    summary = entity_summary(db, ctx.tenant_id)
    if summary["hasBusinessData"]:
        raise ValueError("当前租户已有业务数据；为避免与演示数据混合，已禁止注入演示数据")
    now = datetime.now(timezone.utc)
    job = ImportJob(
        id=f"import-demo-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id,
        file_name="系统内置演示数据集（用户确认）", import_type="onboarding_demo",
        status="running", progress=20,
        options={"source": DEMO_SOURCE, "explicitConfirmation": True, "dataset": "starter-v1"}, result={},
    )
    db.add(job)
    db.flush()
    reports: dict[str, Any] = {}
    for resource_type, rows in _demo_rows(now).items():
        reports[resource_type] = import_entity_rows(db, ctx.tenant_id, job.id, rows, resource_type)
        if reports[resource_type]["rejectedRows"]:
            raise RuntimeError(f"演示数据集被 C2 校验拒绝: {resource_type}")
    job.status = "succeeded"
    job.progress = 100
    job.result = {"source": DEMO_SOURCE, "explicitConfirmation": True, "reports": reports}
    tenant = db.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    tenant.demo_data_flag = True
    activate_tenant_after_business_data(db, ctx.tenant_id)
    save_onboarding_progress(db, ctx, {"lastStep": "demo_ready", "progress": {"demoDataset": "starter-v1"}})
    add_audit(db, ctx, "注入演示数据集", "onboarding", job.id, job.file_name, {"source": DEMO_SOURCE, "explicitConfirmation": True, "reports": reports})
    db.flush()
    return {"job": serialize(job), "status": onboarding_status(db, ctx.tenant_id)}
