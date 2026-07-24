from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session


from ..auth import AuthContext, get_current_user, require_permission
from ..database import get_db
from ..models import CustomField
from ..repository import get_tenant_record, list_tenant_records, serialize


router = APIRouter(tags=["imports-settings"])

@router.get("/settings/custom-fields")
def fields(object_type: str = Query(..., alias="objectType"), ctx: Annotated[AuthContext, Depends(get_current_user)] = None, db: Annotated[Session, Depends(get_db)] = None): return [serialize(x) for x in list_tenant_records(db, CustomField, ctx.tenant_id) if x.object_type == object_type]
@router.post("/settings/custom-fields", status_code=201)
def save_field(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]): item = CustomField(id=body.get("id") or f"field-{uuid.uuid4().hex}", tenant_id=ctx.tenant_id, object_type=body["objectType"], name=body["name"], label=body["label"], field_type=body.get("type", "string"), required=body.get("required", False), enabled=True, config=body.get("config", {})); db.merge(item); db.commit(); return {"ok": True, "id": item.id}
@router.delete("/settings/custom-fields/{item_id}")
def disable_field(item_id: str, ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))], db: Annotated[Session, Depends(get_db)]): item = get_tenant_record(db, CustomField, item_id, ctx.tenant_id); item.enabled = False; db.commit(); return {"ok": True, "id": item.id}
