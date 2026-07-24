from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session


from ..auth import AuthContext, require_permission
from ..database import get_db
from ..models import Role
from ..repository import add_audit, get_tenant_record, list_tenant_records, serialize


router = APIRouter(tags=["imports-settings"])

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
