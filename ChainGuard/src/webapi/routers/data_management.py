from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session


from ..auth import AuthContext, can_view_data, get_current_user, require_permission
from ..database import get_db
from ..errors import ApiError
from ..models import DataRecord
from ..entity_repository import MODEL_BY_RESOURCE, list_product_rows, save_product_entity
from ..repository import add_audit, get_tenant_record, list_tenant_records


router = APIRouter(tags=["imports-settings"])

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
