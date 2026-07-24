from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from src.security import masking
from src.security.encryption import encryption_status
from src.security.masking import mask_payload


POSTURE_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"view_decision", "run_decision", "export", "approve", "admin"},
    "operator": {"view_decision", "run_decision", "export"},
    "approver": {"view_decision", "approve"},
    "viewer": {"view_decision"},
}


@dataclass(frozen=True)
class SecurityPosture:
    role: str
    permissions: list[str]
    masking_rules: dict[str, str]
    encryption_active: bool
    encryption_note: str
    tenant_id: str
    tenant_isolated: bool
    scenario_db_path: str


def security_posture(role: str, data_source: Any | None = None) -> SecurityPosture:
    """Aggregate the current role and data source into a security posture snapshot."""
    if data_source is None:
        from src.data_source import demo_source

        data_source = demo_source()

    status = encryption_status()
    return SecurityPosture(
        role=role,
        permissions=sorted(POSTURE_ROLE_PERMISSIONS.get(role, set())),
        masking_rules={} if role == "admin" else dict(masking.DEFAULT_SENSITIVE_FIELDS),
        encryption_active=bool(status["active"]),
        encryption_note=str(status["note"]),
        tenant_id=str(getattr(data_source, "tenant_id", "default")),
        tenant_isolated=getattr(data_source, "kind", "demo") == "enterprise",
        scenario_db_path=str(getattr(data_source, "scenario_db_path", "")),
    )


def masking_preview(sample: dict[str, Any], role: str) -> dict[str, Any]:
    """Return before/after masking data for UI comparison."""
    before = copy.deepcopy(sample)
    return {
        "before": before,
        "after": mask_payload(before, role),
    }


def sample_sensitive_record() -> dict[str, Any]:
    """Build a sample record containing sensitive fields for masking demos."""
    return {
        "supplier_name": "华东精密供应商",
        "customer_name": "宁波核心客户",
        "unit_price": 128.5,
        "amount": 56000,
        "material_id": "MAT-AX-42",
        "nested": {
            "contact": "ops@example.com",
            "cost": 8200,
            "notes": "安全态势演示样例",
        },
    }
