from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api import app
from src.webapi.auth.security import create_tokens, hash_password
from src.webapi.database import SessionLocal
from src.webapi.entity_import import import_entity_rows
from src.webapi.models import Material, OnboardingState, Role, Tenant, User
from src.webapi.seed import BASE, ROLE_PERMISSIONS, seed


client = TestClient(app)
seed()


def _tenant_users(suffix: str) -> tuple[str, str, str]:
    tenant_id, admin_id, finance_id = f"tenant-c3-{suffix}", f"admin-c3-{suffix}", f"finance-c3-{suffix}"
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="C3 空租户", industry="制造", scale="small", status="initializing", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        admin_role = Role(id=f"role-admin-c3-{suffix}", tenant_id=tenant_id, code="admin", name="管理员", builtin=True, permissions=[*BASE, *ROLE_PERMISSIONS["admin"]])
        finance_role = Role(id=f"role-finance-c3-{suffix}", tenant_id=tenant_id, code="finance", name="财务", builtin=True, permissions=[*BASE, *ROLE_PERMISSIONS["finance"]])
        db.add_all([admin_role, finance_role]); db.flush()
        db.add_all([
            User(id=admin_id, tenant_id=tenant_id, account=f"admin-c3-{suffix}", password_hash=hash_password("C3@2026-password"), name="C3 管理员", phone="", email="", dept_id="dept", role_id=admin_role.id, role_code="admin", status="active", data_scope="all"),
            User(id=finance_id, tenant_id=tenant_id, account=f"finance-c3-{suffix}", password_hash=hash_password("C3@2026-password"), name="C3 财务", phone="", email="", dept_id="dept", role_id=finance_role.id, role_code="finance", status="active", data_scope="all"),
        ])
        db.commit()
    return tenant_id, admin_id, finance_id


def _headers(user_id: str) -> dict[str, str]:
    with SessionLocal() as db:
        token = create_tokens(db.get(User, user_id))["token"]
        return {"Authorization": f"Bearer {token}"}


def _real_c2_minimum(db, tenant_id: str, suffix: str) -> None:
    now = datetime.now(timezone.utc)
    rows = {
        "material": [{"material_id": f"MAT-{suffix}", "material_name": "真实关键物料", "daily_consumption": 240, "standard_cost": 10, "criticality": "critical"}],
        "supplier": [{"supplier_id": f"SUP-{suffix}", "supplier_name": "真实供应商", "reliability_score": 90}],
        "customer": [{"customer_id": f"CUS-{suffix}", "customer_name": "真实客户", "customer_level": "A"}],
        "supplier_material": [{"supplier_material_id": f"REL-{suffix}", "supplier_id": f"SUP-{suffix}", "material_id": f"MAT-{suffix}", "qualified": True, "supplier_rank": 1, "lead_time_hours": 24, "available_emergency_qty": 1000, "emergency_cost_multiplier": 1.2, "unit_cost": 11}],
        "order": [{"sales_order_id": f"SO-{suffix}", "customer_id": f"CUS-{suffix}", "order_status": "pending", "promised_delivery_at": (now + timedelta(days=2)).isoformat(), "order_amount": 10000, "gross_profit": 3000, "penalty_cost": 2000}],
        "order_line": [{"sales_order_line_id": f"SOL-{suffix}", "sales_order_id": f"SO-{suffix}", "line_no": 1, "material_id": f"MAT-{suffix}", "ordered_qty": 300, "unit_price": 33}],
        "inventory": [{"inventory_id": f"INV-{suffix}", "material_id": f"MAT-{suffix}", "available_qty": 200, "on_hand_qty": 200, "safety_stock_qty": 300, "in_transit_qty": 200, "planned_arrival_at": (now + timedelta(hours=12)).isoformat(), "estimated_arrival_at": (now + timedelta(hours=16)).isoformat()}],
    }
    for resource_type in ("material", "supplier", "customer", "supplier_material", "order", "order_line", "inventory"):
        report = import_entity_rows(db, tenant_id, f"c3-real-{suffix}", rows[resource_type], resource_type)
        assert report["rejectedRows"] == 0


def test_c3_empty_tenant_progress_real_data_and_cross_tenant_isolation() -> None:
    suffix = uuid.uuid4().hex
    tenant_id, admin_id, _ = _tenant_users(suffix)
    other_tenant, other_admin, _ = _tenant_users(f"other-{suffix}")
    initial = client.get("/api/v1/onboarding/status", headers=_headers(admin_id))
    assert initial.status_code == 200
    assert initial.json()["guideVisible"] is True and initial.json()["phase"] == "empty"
    saved = client.post("/api/v1/onboarding/progress", headers=_headers(admin_id), json={"lastStep": "real_import", "progress": {"channel": "structured"}})
    assert saved.status_code == 200
    with SessionLocal() as db:
        state = db.scalar(select(OnboardingState).where(OnboardingState.tenant_id == tenant_id))
        assert state is not None and state.last_step == "real_import" and state.progress["channel"] == "structured"
        _real_c2_minimum(db, tenant_id, suffix)
        db.commit()
    completed = client.get("/api/v1/onboarding/status", headers=_headers(admin_id))
    assert completed.status_code == 200
    body = completed.json()
    assert body["guideVisible"] is False and body["entitySummary"]["hasRealData"] is True
    assert body["entitySummary"]["decisionReady"] is True and body["phase"] == "ready"
    isolated = client.get("/api/v1/onboarding/status", headers=_headers(other_admin))
    assert isolated.status_code == 200 and isolated.json()["guideVisible"] is True
    with SessionLocal() as db:
        assert not db.scalars(select(Material).where(Material.tenant_id == other_tenant)).all()


def test_c3_demo_is_explicit_permissioned_and_current_tenant_only() -> None:
    suffix = uuid.uuid4().hex
    tenant_id, admin_id, finance_id = _tenant_users(suffix)
    other_tenant, other_admin, _ = _tenant_users(f"other-{suffix}")
    missing_confirmation = client.post("/api/v1/onboarding/demo-dataset", headers=_headers(admin_id), json={"values": {}})
    assert missing_confirmation.status_code == 422 and missing_confirmation.json()["code"] == "CG-2701"
    forbidden = client.post("/api/v1/onboarding/demo-dataset", headers=_headers(finance_id), json={"values": {"confirmed": True}})
    assert forbidden.status_code == 403
    injected = client.post("/api/v1/onboarding/demo-dataset", headers=_headers(admin_id), json={"values": {"confirmed": True}})
    assert injected.status_code == 201, injected.text
    payload = injected.json()
    assert payload["status"]["phase"] == "demo_ready"
    assert payload["job"]["options"]["source"] == "onboarding_demo"
    with SessionLocal() as db:
        rows = list(db.scalars(select(Material).where(Material.tenant_id == tenant_id)).all())
        assert rows and rows[0].extra["onboardingDataSource"] == "onboarding_demo"
        assert not db.scalars(select(Material).where(Material.tenant_id == other_tenant)).all()
        assert db.get(Tenant, tenant_id).demo_data_flag is True
    # A second explicit request is blocked instead of silently merging a dataset.
    assert client.post("/api/v1/onboarding/demo-dataset", headers=_headers(admin_id), json={"values": {"confirmed": True}}).status_code == 409
    assert client.get("/api/v1/onboarding/status", headers=_headers(other_admin)).json()["phase"] == "empty"
