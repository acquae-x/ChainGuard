from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends


from ..auth import AuthContext, require_permission


router = APIRouter(tags=["imports-settings"])

@router.get("/notifications/webhook-config")
def webhook_config(ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))]): return {"enabled": bool(os.getenv("WEBHOOK_URL")), "url": "***" if os.getenv("WEBHOOK_URL") else ""}
@router.put("/notifications/webhook-config")
def update_webhook_config(body: dict[str, Any], ctx: Annotated[AuthContext, Depends(require_permission("settings:manage"))]): return {"enabled": bool(body.get("enabled")), "url": "***" if body.get("url") else ""}
