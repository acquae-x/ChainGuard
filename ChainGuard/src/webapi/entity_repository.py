"""Tenant-scoped repository for the five existing product data pages."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from .entity_mapping import entity_to_product_row, upsert_entities
from .models import CustomerEntity, InventoryEntity, Material, SalesOrder, SupplierEntity, SupplierMaterial


MODEL_BY_RESOURCE = {
    "material": Material,
    "supplier": SupplierEntity,
    "customer": CustomerEntity,
    "order": SalesOrder,
    "inventory": InventoryEntity,
}
BUSINESS_KEY = {
    "material": "material_id",
    "supplier": "supplier_id",
    "customer": "customer_id",
    "order": "sales_order_id",
    "inventory": "inventory_id",
}


def list_product_rows(db: Session, tenant_id: str, resource_type: str) -> list[dict[str, Any]]:
    model = MODEL_BY_RESOURCE[resource_type]
    entities = list(db.scalars(select(model).where(model.tenant_id == tenant_id)))
    if resource_type == "material":
        inventory_by_material: dict[str, list[InventoryEntity]] = defaultdict(list)
        for row in db.scalars(select(InventoryEntity).where(InventoryEntity.tenant_id == tenant_id)):
            inventory_by_material[row.material_id].append(row)
        return [entity_to_product_row(resource_type, row, related={"inventory": inventory_by_material[row.material_id]}) for row in entities]
    if resource_type == "supplier":
        relation_by_supplier: dict[str, list[SupplierMaterial]] = defaultdict(list)
        for row in db.scalars(select(SupplierMaterial).where(SupplierMaterial.tenant_id == tenant_id)):
            relation_by_supplier[row.supplier_id].append(row)
        material_names = {
            row.material_id: row.material_name
            for row in db.scalars(select(Material).where(Material.tenant_id == tenant_id))
        }
        return [
            entity_to_product_row(
                resource_type,
                row,
                related={
                    "supplier_materials": relation_by_supplier[row.supplier_id],
                    "material_names": material_names,
                },
            )
            for row in entities
        ]
    if resource_type == "order":
        customers = {
            row.customer_id: row
            for row in db.scalars(select(CustomerEntity).where(CustomerEntity.tenant_id == tenant_id))
        }
        return [entity_to_product_row(resource_type, row, related={"customer": customers.get(row.customer_id)}) for row in entities]
    if resource_type == "inventory":
        materials = {
            row.material_id: row
            for row in db.scalars(select(Material).where(Material.tenant_id == tenant_id))
        }
        output = []
        for row in entities:
            available = float(row.available_qty or 0)
            safety = float(row.safety_stock_qty or 0)
            status = "out_of_stock" if available <= 0 else ("low" if safety > 0 and available < safety else "normal")
            output.append(entity_to_product_row(resource_type, row, related={"material": materials.get(row.material_id), "status": status}))
        return output
    return [entity_to_product_row(resource_type, row) for row in entities]


def get_entity(db: Session, tenant_id: str, resource_type: str, business_key: str) -> Any | None:
    model = MODEL_BY_RESOURCE[resource_type]
    key = BUSINESS_KEY[resource_type]
    return db.scalar(select(model).where(model.tenant_id == tenant_id, getattr(model, key) == business_key))


def _resolve_related_key(db: Session, tenant_id: str, model: Any, key: str, name_key: str, body: Mapping[str, Any], *aliases: str) -> str | None:
    for alias in aliases:
        if body.get(alias):
            return str(body[alias])
    display = body.get(name_key)
    if display:
        name_column = getattr(model, name_key)
        item = db.scalar(select(model).where(model.tenant_id == tenant_id, name_column == str(display)))
        if item is not None:
            return str(getattr(item, key))
    return None


def product_body_to_source(db: Session, tenant_id: str, resource_type: str, body: Mapping[str, Any], *, existing: Any | None = None) -> dict[str, Any]:
    def old(name: str, default: Any = None) -> Any:
        return getattr(existing, name, default) if existing is not None else default

    if resource_type == "material":
        return {
            **dict(getattr(existing, "extra", {}) or {}),
            "material_id": body.get("id") or body.get("materialId") or old("material_id") or f"MAT-{uuid.uuid4().hex[:12].upper()}",
            "material_name": body.get("name", old("material_name")),
            "category": body.get("category", old("category")),
            "unit": body.get("unit", old("unit")),
            "standard_cost": body.get("cost", old("unit_cost")),
            "daily_consumption": body.get("dailyConsumption", old("daily_consumption")),
            "criticality": body.get("isCritical", old("is_critical")),
            "remark": body.get("remark"),
        }
    if resource_type == "supplier":
        return {
            **dict(getattr(existing, "extra", {}) or {}),
            "supplier_id": body.get("id") or body.get("supplierId") or old("supplier_id") or f"SUP-{uuid.uuid4().hex[:12].upper()}",
            "supplier_name": body.get("name", old("supplier_name")),
            "region": body.get("region", old("region")),
            "status": body.get("status", old("status", "active")),
            "reliability_score": body.get("reliabilityScore", old("reliability_score")),
            "remark": body.get("remark"),
        }
    if resource_type == "customer":
        return {
            **dict(getattr(existing, "extra", {}) or {}),
            "customer_id": body.get("id") or body.get("customerId") or old("customer_id") or f"CUS-{uuid.uuid4().hex[:12].upper()}",
            "customer_name": body.get("name", old("customer_name")),
            "customer_level": body.get("customerLevel", old("customer_level")),
            "region": body.get("region", old("region")),
            "contract": body.get("contract", old("contract")),
            "owner": body.get("owner", old("owner")),
            "remark": body.get("remark"),
        }
    if resource_type == "order":
        customer_id = body.get("customerId") or old("customer_id")
        if not customer_id and body.get("customer"):
            customer = db.scalar(
                select(CustomerEntity).where(
                    CustomerEntity.tenant_id == tenant_id,
                    CustomerEntity.customer_name == str(body["customer"]),
                )
            )
            customer_id = customer.customer_id if customer is not None else None
        return {
            **dict(getattr(existing, "extra", {}) or {}),
            "sales_order_id": body.get("orderNo") or body.get("id") or old("sales_order_id") or f"SO-{uuid.uuid4().hex[:12].upper()}",
            "customer_id": customer_id,
            "promised_delivery_at": body.get("dueAt", old("promised_delivery_at")),
            "order_amount": body.get("amount", old("order_amount")),
            "gross_profit": body.get("profit", old("gross_profit")),
            "penalty_cost": body.get("penaltyCost", old("penalty_cost")),
            "order_status": body.get("status", old("order_status", "pending")),
            "remark": body.get("remark"),
        }
    if resource_type == "inventory":
        material_id = body.get("materialId") or old("material_id")
        if not material_id and body.get("material"):
            material = db.scalar(
                select(Material).where(
                    Material.tenant_id == tenant_id,
                    Material.material_name == str(body["material"]),
                )
            )
            material_id = material.material_id if material is not None else None
        return {
            **dict(getattr(existing, "extra", {}) or {}),
            "inventory_id": body.get("id") or body.get("inventoryId") or old("inventory_id") or f"INV-{uuid.uuid4().hex[:12].upper()}",
            "material_id": material_id,
            "warehouse_id": body.get("warehouseId", old("warehouse_id")),
            "warehouse_name": body.get("warehouse", old("warehouse_name")),
            "available_qty": body.get("quantity", old("available_qty")),
            "on_hand_qty": body.get("stock", old("on_hand_qty")),
            "safety_stock_qty": body.get("safety", old("safety_stock_qty")),
            "in_transit_qty": body.get("inTransitQty", old("in_transit_qty")),
            "planned_arrival_at": body.get("plannedArrivalAt", old("planned_arrival_at")),
            "estimated_arrival_at": body.get("estimatedArrivalAt", old("estimated_arrival_at")),
            "remark": body.get("remark"),
        }
    raise KeyError(resource_type)


def save_product_entity(db: Session, tenant_id: str, resource_type: str, body: Mapping[str, Any], *, business_key: str | None = None) -> Any:
    existing = get_entity(db, tenant_id, resource_type, business_key) if business_key else None
    if business_key is not None and existing is None:
        raise LookupError("entity not found")
    source = product_body_to_source(db, tenant_id, resource_type, body, existing=existing)
    result = upsert_entities(db, tenant_id, resource_type, [source])
    if result["rejected"]:
        raise ValueError(str(result["rejected"][0]["reason"]))
    key = str(source[BUSINESS_KEY[resource_type]])
    db.flush()
    return get_entity(db, tenant_id, resource_type, key)
