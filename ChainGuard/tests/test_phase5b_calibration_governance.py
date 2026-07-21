from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api import app
from src.webapi.auth.security import create_tokens, hash_password
from src.webapi.database import SessionLocal
from src.webapi.models import ImportSourceRow, NotificationMessage, Role, Tenant, TenantConfig, User
from src.webapi.seed import BASE, ROLE_PERMISSIONS, seed


client = TestClient(app)
seed()


def _tenant_users(suffix: str) -> tuple[str, str, str]:
    tenant_id = f"tenant-calibration-{suffix}"
    admin_id, buyer_id = f"admin-{suffix}", f"buyer-{suffix}"
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="校准治理验收租户", industry="制造", scale="small", status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        admin_role = Role(id=f"role-admin-{suffix}", tenant_id=tenant_id, code="admin", name="管理员", builtin=True, permissions=[*BASE, *ROLE_PERMISSIONS["admin"]])
        buyer_role = Role(id=f"role-buyer-{suffix}", tenant_id=tenant_id, code="buyer", name="采购", builtin=True, permissions=[*BASE, *ROLE_PERMISSIONS["buyer"]])
        db.add_all([admin_role, buyer_role]); db.flush()
        db.add_all([
            User(id=admin_id, tenant_id=tenant_id, account=f"admin-{suffix}", password_hash=hash_password("Calibration@2026"), name="校准管理员", phone="", email="", dept_id="dept-1", role_id=admin_role.id, role_code="admin", status="active", data_scope="all"),
            User(id=buyer_id, tenant_id=tenant_id, account=f"buyer-{suffix}", password_hash=hash_password("Calibration@2026"), name="采购用户", phone="", email="", dept_id="dept-1", role_id=buyer_role.id, role_code="buyer", status="active", data_scope="custom"),
        ])
        db.commit()
    return tenant_id, admin_id, buyer_id


def _headers(user_id: str) -> dict[str, str]:
    with SessionLocal() as db:
        token = create_tokens(db.get(User, user_id))["token"]
        return {"Authorization": f"Bearer {token}"}


def _history(tenant_id: str, suffix: str, *, failed: bool, count: int = 5) -> None:
    with SessionLocal() as db:
        for index in range(count):
            db.add(ImportSourceRow(
                id=f"history-{suffix}-{failed}-{index}", tenant_id=tenant_id,
                import_job_id=f"job-{suffix}-{failed}", source_table="historical_decisions", row_number=index + 1,
                payload={
                    "case_id": f"case-{suffix}-{failed}-{index}",
                    "created_at": f"2026-07-{index + 1:02d}T00:00:00+00:00",
                    "outcome_status": "failed" if failed else "success",
                    "covered_demand_rate": 0.3 if failed else 0.95,
                    "actual_delay_hours": 30 if failed else 4,
                    "predicted_delay_hours": 10,
                    "actual_cost": 1500 if failed else 1000,
                    "predicted_cost": 1000,
                    "lost_orders": 2 if failed else 0,
                    "production_downtime_hours": 8 if failed else 0,
                    "human_rating": 2 if failed else 5,
                },
            ))
        db.commit()


def test_calibration_is_tenant_scoped_gated_and_drift_notifies_admin(tmp_path, monkeypatch) -> None:
    # The production adapter uses one ModelRegistry per tenant.  Keep the
    # acceptance registry outside repository evidence files for this unit test.
    import src.webapi.calibration_governance as governance
    monkeypatch.setattr(governance, "_registry_path", lambda tenant_id: tmp_path / tenant_id / "model_registry.json")
    suffix = uuid.uuid4().hex
    tenant_id, admin_id, buyer_id = _tenant_users(suffix)
    _history(tenant_id, suffix, failed=False)
    other_tenant, _, _ = _tenant_users(f"other-{suffix}")
    _history(other_tenant, f"other-{suffix}", failed=True, count=9)

    forbidden = client.get("/api/v1/settings/calibration-governance", headers=_headers(buyer_id))
    assert forbidden.status_code == 403

    proposed = client.get("/api/v1/settings/calibration-governance", headers=_headers(admin_id))
    assert proposed.status_code == 200, proposed.text
    snapshot = proposed.json()
    assert snapshot["sample"]["totalRows"] == snapshot["sample"]["effectiveRows"] == 5
    assert snapshot["comparison"]["active"]["approved"] is False
    assert snapshot["sample"]["timeRange"]["from"].startswith("2026-07-01")
    with SessionLocal() as db:
        assert not db.scalars(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id)).all()

    # 只有 5 条历史决策、且没有重建事前特征所需的扰动事件/库存快照，
    # 监督式校准无法通过样本外验证 —— 此时**必须拒绝应用**，不能把未经验证的
    # 权重以"已校准"的名义写进租户配置。成功确认的完整闭环见
    # tests/test_calibration_loop_end_to_end.py::test_signal_bearing_history_calibrates_and_applies
    confirmed = client.post("/api/v1/settings/calibration-governance/confirm", headers=_headers(admin_id), json={"values": {"recommendationId": snapshot["recommendationId"]}})
    assert confirmed.status_code == 409, confirmed.text
    assert confirmed.json()["code"] == "CG-2902"
    with SessionLocal() as db:
        assert not db.scalars(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id)).all(), \
            "校准未通过验证时不得写入任何租户配置"
        assert not db.scalars(select(TenantConfig).where(TenantConfig.tenant_id == other_tenant)).all()

    # 漂移体检需要一个已提升为 stable 的基线版本。过去这一步由"确认校准"顺带完成，
    # 现在确认被验证门挡住，因此显式提升基线，把漂移这段与校准是否获批解耦。
    from src.model_registry import ModelRegistry
    ModelRegistry(tmp_path / tenant_id / "model_registry.json").promote_stable(str(snapshot["registeredVersion"]))

    _history(tenant_id, suffix, failed=True)
    drifted = client.get("/api/v1/settings/calibration-governance", headers=_headers(admin_id))
    assert drifted.status_code == 200, drifted.text
    assert drifted.json()["drift"]["driftDetected"] is True
    assert drifted.json()["drift"]["severity"] == "critical"
    with SessionLocal() as db:
        alerts = list(db.scalars(select(NotificationMessage).where(
            NotificationMessage.tenant_id == tenant_id,
            NotificationMessage.user_id == admin_id,
            NotificationMessage.kind == "drift_detected",
        )).all())
        assert len(alerts) == 1
