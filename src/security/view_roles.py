from __future__ import annotations

from typing import Any

from src.security.masking import mask_payload


VIEW_ROLE: dict[str, str] = {
    "管理者": "admin",
    "供应链经理": "operator",
    "一线从业者": "viewer",
}
DEFAULT_VIEW = "一线从业者"


def role_for_view(view: str) -> str:
    """Map a three-view label to the matching RBAC role."""
    for name, role in VIEW_ROLE.items():
        if name in view:
            return role
    return VIEW_ROLE[DEFAULT_VIEW]


def mask_for_view(payload: dict[str, Any], view: str) -> dict[str, Any]:
    """Mask one display record according to the role implied by the view."""
    return mask_payload(payload, role_for_view(view))


def mask_rows_for_view(rows: list[dict[str, Any]], view: str) -> list[dict[str, Any]]:
    """Mask a batch of display rows according to the role implied by the view."""
    if not rows:
        return []
    return [mask_for_view(row, view) for row in rows]
