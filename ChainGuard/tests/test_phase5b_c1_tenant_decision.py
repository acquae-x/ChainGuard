from __future__ import annotations

import threading
import time
import uuid
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api import app
from src.orchestrator import DecisionOrchestrator
from src.webapi import jobs
from src.webapi.auth.security import AuthContext, create_tokens
from src.webapi.context_builder import ContextBuildError, EngineContext, TenantContextBuilder
from src.webapi.database import SessionLocal
from src.webapi.entity_mapping import upsert_entities
from src.webapi.models import (
    CustomerEntity,
    Incident,
    InventoryEntity,
    Job,
    Material,
    Proposal,
    Risk,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    Tenant,
    TenantConfig,
    User,
)
from src.webapi.seed import seed


seed()
client = TestClient(app)


def _headers() -> dict[str, str]:
    with SessionLocal() as db:
        return {"Authorization": f"Bearer {create_tokens(db.get(User, 'u-scm_lead'))['token']}"}


def _add_scenario(
    db,
    tenant_id: str,
    suffix: str,
    *,
    stock: float = 40,
    available: float = 35,
    supplier_price: float = 12,
    supplier_lead: float = 18,
    order_amount: float = 100_000,
    level: str = "high",
    delay: float | None = 36,
    with_inventory: bool = True,
    with_suppliers: bool = True,
    with_orders: bool = True,
    with_arrival: bool = True,
    daily_consumption: float | None = 240,
) -> tuple[str, str]:
    material_id = f"MAT-C1-{suffix}"
    supplier_a = f"SUP-A-{suffix}"
    db.merge(Tenant(id=tenant_id, name=tenant_id, industry="制造", scale="small", status="active", plan="trial", trial_end_at="", demo_data_flag=False))
    material_pk = f"mat-{tenant_id}-{suffix}"
    db.add(Material(
        id=material_pk, tenant_id=tenant_id, material_id=material_id, material_name=f"C1核心物料-{tenant_id}",
        category="芯片", unit="件", daily_consumption=daily_consumption, unit_cost=10, is_critical=True, extra={},
    ))
    db.flush()
    if with_inventory:
        arrival = datetime.now(timezone.utc) + timedelta(hours=12)
        db.add(InventoryEntity(
            id=f"inv-{tenant_id}-{suffix}", tenant_id=tenant_id, inventory_id=f"INV-C1-{suffix}",
            material_id=material_id, warehouse_id="W-1", warehouse_name="一仓",
            on_hand_qty=stock, available_qty=available, safety_stock_qty=80, in_transit_qty=20,
            planned_arrival_at=arrival if with_arrival else None,
            estimated_arrival_at=(arrival + timedelta(hours=8)) if with_arrival else None,
            extra={},
        ))
    if with_suppliers:
        for index, (supplier_id, price, lead, qty) in enumerate([
            (supplier_a, supplier_price, supplier_lead, 180),
            (f"SUP-B-{suffix}", supplier_price * 1.1, supplier_lead + 12, 120),
        ], start=1):
            db.add(SupplierEntity(
                id=f"supplier-{tenant_id}-{suffix}-{index}", tenant_id=tenant_id,
                supplier_id=supplier_id, supplier_name=f"供应商{supplier_id}", region="华东",
                status="active", reliability_score=95 - index, extra={},
            ))
            db.flush()
            db.add(SupplierMaterial(
                id=f"sm-{tenant_id}-{suffix}-{index}", tenant_id=tenant_id,
                supplier_material_id=f"SM-{suffix}-{index}", supplier_id=supplier_id, material_id=material_id,
                qualified=True, supplier_rank=index, available_emergency_qty=qty,
                lead_time_hours=lead, emergency_cost_multiplier=1.2 + index / 10,
                supplier_price=price, extra={},
            ))
    if with_orders:
        for index, priority in enumerate(("A", "B"), start=1):
            customer_id = f"CUS-{priority}-{suffix}"
            order_id = f"SO-{priority}-{suffix}"
            db.add(CustomerEntity(
                id=f"customer-{tenant_id}-{suffix}-{index}", tenant_id=tenant_id,
                customer_id=customer_id, customer_name=f"{priority}级客户", customer_level=priority,
                region="华东", contract="年度", owner="销售", extra={},
            ))
            db.flush()
            db.add(SalesOrder(
                id=f"order-{tenant_id}-{suffix}-{index}", tenant_id=tenant_id,
                sales_order_id=order_id, customer_id=customer_id, order_status="pending",
                promised_delivery_at=datetime.now(timezone.utc) + timedelta(hours=24 * index),
                order_amount=order_amount / index, gross_profit=None, penalty_cost=None, extra={},
            ))
            db.flush()
            db.add(SalesOrderLine(
                id=f"line-{tenant_id}-{suffix}-{index}", tenant_id=tenant_id,
                sales_order_line_id=f"SOL-{index}", sales_order_id=order_id, line_no=1,
                material_id=material_id, ordered_qty=100 / index, unit_price=20, extra={},
            ))
    risk_id = f"risk-{tenant_id}-{suffix}"
    incident_id = f"inc-{tenant_id}-{suffix}"
    details = {"material_id": material_id, "supplier_id": supplier_a, "location": "苏州", "affected_route": "沪苏线"}
    if delay is not None:
        details["estimated_delay_hours"] = delay
    db.add(Risk(
        id=risk_id, tenant_id=tenant_id, code=f"R-{suffix}", level=level, type="供应",
        object_type="物料", object_name=material_id, score=88, rule="供应延误",
        found_at=datetime.now(timezone.utc).isoformat(), status="incident_created", details=details,
        incident_id=incident_id,
    ))
    db.add(Incident(
        id=incident_id, tenant_id=tenant_id, code=f"I-{suffix}", title="C1真实租户决策",
        type="supplier_shutdown", level=level, status="planning", owner="测试",
        source_risk_ids=[risk_id], loss=0, cost=0,
    ))
    db.commit()
    return incident_id, risk_id


def _import_complete_scenario(db, tenant_id: str, suffix: str) -> str:
    """Use the real C2 shared YAML adapter for the C1 API acceptance fixture."""
    db.merge(Tenant(id=tenant_id, name=tenant_id, industry="制造", scale="small", status="active", plan="trial", trial_end_at="", demo_data_flag=False))
    db.flush()
    material_id = f"MAT-IMPORT-{suffix}"
    supplier_id = f"SUP-IMPORT-{suffix}"
    customer_id = f"CUS-IMPORT-{suffix}"
    order_id = f"SO-IMPORT-{suffix}"
    arrival = datetime.now(timezone.utc) + timedelta(hours=16)
    batches = [
        ("material", [{"material_id": material_id, "material_name": "导入核心芯片", "daily_consumption": 240, "standard_cost": 13, "criticality": "critical"}]),
        ("supplier", [{"supplier_id": supplier_id, "supplier_name": "导入备用供应商", "status": "active", "reliability_score": 96}]),
        ("supplier_material", [{"supplier_material_id": f"SM-IMPORT-{suffix}", "supplier_id": supplier_id, "material_id": material_id, "qualified": True, "supplier_rank": 1, "lead_time_hours": 30, "available_emergency_qty": 220, "emergency_cost_multiplier": 1.4, "unit_cost": 17}]),
        ("customer", [{"customer_id": customer_id, "customer_name": "导入A级客户", "customer_level": "A"}]),
        ("order", [{"sales_order_id": order_id, "customer_id": customer_id, "order_status": "pending", "promised_delivery_at": (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat(), "order_amount": 180_000, "gross_profit": 45_000, "penalty_cost": 36_000}]),
        ("order_line", [{"sales_order_line_id": f"SOL-IMPORT-{suffix}", "sales_order_id": order_id, "line_no": 1, "material_id": material_id, "ordered_qty": 140, "unit_price": 20}]),
        ("inventory", [{"inventory_id": f"INV-IMPORT-{suffix}", "material_id": material_id, "warehouse_id": "W-IMPORT", "warehouse_name": "导入仓", "on_hand_qty": 25, "available_qty": 20, "safety_stock_qty": 80, "in_transit_qty": 30, "planned_arrival_at": arrival.isoformat(), "estimated_arrival_at": (arrival + timedelta(hours=10)).isoformat()}]),
    ]
    for resource_type, rows in batches:
        result = upsert_entities(db, tenant_id, resource_type, rows)
        assert result["inserted"] == len(rows) and result["rejected"] == []
    risk_id, incident_id = f"risk-import-{suffix}", f"inc-import-{suffix}"
    db.add(Risk(id=risk_id, tenant_id=tenant_id, code=risk_id, level="high", type="供应", object_type="物料", object_name=material_id, score=91, rule="供应延误", found_at=datetime.now(timezone.utc).isoformat(), status="incident_created", details={"material_id": material_id, "supplier_id": supplier_id, "estimated_delay_hours": 42}, incident_id=incident_id))
    db.add(Incident(id=incident_id, tenant_id=tenant_id, code=incident_id, title="导入数据真实决策闭环", type="supplier_shutdown", level="high", status="planning", owner="测试", source_risk_ids=[risk_id], loss=0, cost=0))
    db.commit()
    return incident_id


def test_builder_contract_five_entities_metrics_units_and_degradation() -> None:
    suffix = uuid.uuid4().hex
    tenant_id = f"tenant-c1-contract-{suffix}"
    with SessionLocal() as db:
        incident_id, _ = _add_scenario(db, tenant_id, suffix)
        built = TenantContextBuilder(db, tenant_id).build(incident_id)

    context = EngineContext.model_validate(built.context).model_dump()
    inventory = context["inventory"]
    assert inventory["material_id"] == f"MAT-C1-{suffix}"
    assert inventory["hourly_consumption"] == 10.0
    assert inventory["current_stock"] == 40.0
    assert inventory["in_transit_qty"] == 20.0
    assert inventory["critical_order_demand"] == 100.0
    assert context["orders"][0]["demand"] == context["orders"][0]["demand_qty"]
    assert context["orders"][0]["delivery_hours"] == context["orders"][0]["due_hours"]
    assert context["orders"][0]["customer_name"] == "A级客户"
    assert context["suppliers"][0]["supplier_price"] == 12.0
    assert context["suppliers"][0]["delay_hours"] == 36.0
    assert [item["mode"] for item in context["transport_options"]] == ["air", "truck", "rail", "sea"]
    assert context["events"][0]["event_type"] == context["events"][0]["type"]
    metrics = context["derived_metrics"]
    assert metrics["inventory_support_hours"] == 4.0
    assert metrics["available_inventory_qty"] == 35.0
    assert metrics["inventory_shortage_qty"] == 45.0
    assert metrics["critical_order_exposure"]["order_amount"] == 100_000
    assert metrics["supplier_alternatives"]["qualified_count"] == 2
    assert metrics["units"] == {
        "quantity": "piece", "time": "hour", "currency": "CNY",
        "risk_score": "0-100", "timestamp": "UTC ISO-8601",
    }
    assert built.data_quality.level == "degraded"
    assert "estimated_order_financials" in built.data_quality.degraded


def test_builder_strictly_isolates_same_business_keys_across_two_tenants() -> None:
    suffix = uuid.uuid4().hex
    tenant_a, tenant_b = f"tenant-c1-a-{suffix}", f"tenant-c1-b-{suffix}"
    with SessionLocal() as db:
        incident_a, _ = _add_scenario(db, tenant_a, suffix, stock=20, supplier_price=9, order_amount=80_000)
        incident_b, _ = _add_scenario(db, tenant_b, suffix, stock=900, supplier_price=99, order_amount=900_000)
        context_a = TenantContextBuilder(db, tenant_a).build(incident_a).context
        context_b = TenantContextBuilder(db, tenant_b).build(incident_b).context
        with pytest.raises(ContextBuildError) as cross:
            TenantContextBuilder(db, tenant_a).build(incident_b)
    assert cross.value.code == "CG-2510" and cross.value.status_code == 404
    assert context_a["inventory"]["current_stock"] == 20
    assert context_b["inventory"]["current_stock"] == 900
    assert context_a["suppliers"][0]["supplier_price"] == 9
    assert context_b["suppliers"][0]["supplier_price"] == 99
    assert context_a["orders"][0]["order_amount"] == 80_000
    assert context_b["orders"][0]["order_amount"] == 900_000


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"with_inventory": False}, "CG-2513"),
        ({"daily_consumption": 0}, "CG-2512"),
        ({"level": "high", "delay": None}, "CG-2514"),
    ],
)
def test_builder_blocking_rules(kwargs: dict, code: str) -> None:
    suffix = uuid.uuid4().hex
    tenant_id = f"tenant-c1-block-{suffix}"
    with SessionLocal() as db:
        incident_id, _ = _add_scenario(db, tenant_id, suffix, **kwargs)
        with pytest.raises(ContextBuildError) as error:
            TenantContextBuilder(db, tenant_id).build(incident_id)
    assert error.value.code == code


def test_empty_incident_blocks_and_optional_absences_are_structured_degradations() -> None:
    suffix = uuid.uuid4().hex
    tenant_id = f"tenant-c1-empty-{suffix}"
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="空租户", industry="制造", scale="small", status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        empty_id = f"inc-empty-{suffix}"
        db.add(Incident(id=empty_id, tenant_id=tenant_id, code=empty_id, title="空事件", type="manual", level="low", status="planning", owner="", source_risk_ids=[], loss=0, cost=0))
        db.commit()
        with pytest.raises(ContextBuildError) as missing_material:
            TenantContextBuilder(db, tenant_id).build(empty_id)
        assert missing_material.value.code == "CG-2511"

        incident_id, _ = _add_scenario(
            db, f"tenant-c1-degraded-{suffix}", suffix, level="low", delay=None,
            with_suppliers=False, with_orders=False, with_arrival=False,
        )
        built = TenantContextBuilder(db, f"tenant-c1-degraded-{suffix}").build(incident_id)
    assert set(built.data_quality.degraded) >= {
        "default_event_delay", "missing_arrival_information", "no_orders", "no_suppliers",
    }
    result = DecisionOrchestrator().run_tenant_scenario(
        built.context, risk_weights=built.risk_weights, thresholds=built.thresholds,
    )
    assert any("人工寻源" in proposal["proposal_title"] for proposal in result.proposals)
    assert result.experience_references["reference_count"] == 0


def test_real_inventory_quote_lead_and_order_changes_explainably_change_output() -> None:
    suffix = uuid.uuid4().hex
    tenant_id = f"tenant-c1-change-{suffix}"
    with SessionLocal() as db:
        incident_id, _ = _add_scenario(db, tenant_id, suffix, stock=20, supplier_price=10, supplier_lead=12, order_amount=100_000)
        first = TenantContextBuilder(db, tenant_id).build(incident_id)
    first_result = DecisionOrchestrator().run_tenant_scenario(first.context, risk_weights=first.risk_weights, thresholds=first.thresholds)
    first_procurement = next(item for item in first_result.proposals if "采购" in item["agent_name"])
    first_finance = next(item for item in first_result.proposals if "财务" in item["agent_name"])

    with SessionLocal() as db:
        inventory = db.scalar(select(InventoryEntity).where(InventoryEntity.tenant_id == tenant_id))
        relation = db.scalar(select(SupplierMaterial).where(SupplierMaterial.tenant_id == tenant_id, SupplierMaterial.supplier_id == f"SUP-A-{suffix}"))
        order = db.scalar(select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.sales_order_id == f"SO-A-{suffix}"))
        inventory.on_hand_qty = inventory.available_qty = 300
        relation.supplier_price = 25
        relation.lead_time_hours = 72
        order.order_amount = 400_000
        db.commit()
        second = TenantContextBuilder(db, tenant_id).build(incident_id)
    second_result = DecisionOrchestrator().run_tenant_scenario(second.context, risk_weights=second.risk_weights, thresholds=second.thresholds)
    second_procurement = next(item for item in second_result.proposals if "采购" in item["agent_name"])
    second_finance = next(item for item in second_result.proposals if "财务" in item["agent_name"])

    assert second_result.inventory_risk["inventory_risk_index"] < first_result.inventory_risk["inventory_risk_index"]
    assert second_procurement["total_cost"] != first_procurement["total_cost"]
    assert second_procurement["lead_time_impact"] > first_procurement["lead_time_impact"]
    # SUP-A's quote increase makes the engine select the still-cheaper SUP-B;
    # the output exposes both the switch and the exact tenant quote used.
    assert second_procurement["economic_basis"]["supplier_id"] != first_procurement["economic_basis"]["supplier_id"]
    assert second_procurement["economic_basis"]["unit_price_cny"] == 11
    assert second_finance["economic_basis"]["total_penalty_cny"] > first_finance["economic_basis"]["total_penalty_cny"]


def test_only_active_and_approved_tenant_configs_apply() -> None:
    suffix = uuid.uuid4().hex
    tenant_id = f"tenant-c1-config-{suffix}"
    with SessionLocal() as db:
        incident_id, _ = _add_scenario(db, tenant_id, suffix)
        db.add(TenantConfig(
            id=f"cfg-threshold-{suffix}", tenant_id=tenant_id, config_type="thresholds",
            payload={"inventory_warning": {"inventory_risk_trigger": 33}}, version=2,
            source="calibrated", is_active=True, approved_by="approver",
            approved_at=datetime.now(timezone.utc), extra={},
        ))
        db.add(TenantConfig(
            id=f"cfg-weight-{suffix}", tenant_id=tenant_id, config_type="risk_weights",
            payload={"inventory_risk_weights": {"shortage_urgency": 0.1, "order_importance": 0.2, "transit_delay": 0.3, "external_event": 0.4}},
            version=3, source="calibrated", is_active=True, approved_by=None, approved_at=None, extra={},
        ))
        db.add(TenantConfig(
            id=f"cfg-transport-{suffix}", tenant_id=tenant_id, config_type="transport_options",
            payload=[], version=1, source="expert", is_active=False, approved_by="approver",
            approved_at=datetime.now(timezone.utc), extra={},
        ))
        db.commit()
        built = TenantContextBuilder(db, tenant_id).build(incident_id)
    assert built.thresholds["inventory_warning"]["inventory_risk_trigger"] == 33
    assert built.configuration["items"]["thresholds"]["version"] == 2
    assert built.risk_weights["inventory_risk_weights"]["shortage_urgency"] == 0.35
    assert built.configuration["items"]["risk_weights"]["fallback_reason"] == "active_config_not_approved"
    assert built.configuration["items"]["transport_options"]["fallback_reason"] == "no_active_tenant_config"


def test_web_blocked_job_returns_structured_reason_without_persisting_proposals() -> None:
    suffix = uuid.uuid4().hex
    with SessionLocal() as db:
        incident_id, _ = _add_scenario(db, "tenant-demo", suffix, level="high", delay=None)
    readiness = client.get(f"/api/v1/incidents/{incident_id}/decision-readiness", headers=_headers())
    assert readiness.status_code == 200
    assert readiness.json()["level"] == "blocked"
    assert readiness.json()["blocking"][0]["code"] == "CG-2514"
    response = client.post(f"/api/v1/incidents/{incident_id}/proposals:generate", headers=_headers())
    assert response.status_code == 202
    job_id = response.json()["jobId"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}", headers=_headers()).json()
        if body["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.03)
    assert body["status"] == "failed"
    assert body["errorCode"] == "CG-2514"
    assert body["result"]["dataQuality"]["level"] == "blocked"
    with SessionLocal() as db:
        assert db.scalar(select(Proposal.id).where(Proposal.tenant_id == "tenant-demo", Proposal.incident_id == incident_id)) is None


def test_web_real_closed_loop_persists_tenant_context_and_uses_worker_session() -> None:
    started = time.perf_counter()
    suffix = uuid.uuid4().hex
    tenant_id = "tenant-demo"
    with SessionLocal() as db:
        incident_id = _import_complete_scenario(db, tenant_id, suffix)
    response = client.post(f"/api/v1/incidents/{incident_id}/proposals:generate", headers=_headers())
    assert response.status_code == 202, response.text
    job_id = response.json()["jobId"]
    deadline = time.monotonic() + 30
    body = None
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}", headers=_headers()).json()
        if body["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert body and body["status"] == "succeeded", body
    assert body["result"]["configuration"]["source"] in {"expert_default", "tenant_config"}
    listed = client.get(f"/api/v1/proposals?incidentId={incident_id}", headers=_headers()).json()["data"]
    assert listed and any(item["totalCost"] is not None for item in listed)
    detail = client.get(f"/api/v1/incidents/{incident_id}/decision-detail", headers=_headers()).json()
    assert detail["context"]["inventory"]["current_stock"] == 25
    assert detail["context"]["suppliers"][0]["supplier_price"] == 17
    assert detail["context"]["events"][0]["event_id"] == incident_id
    with SessionLocal() as db:
        assert all(item.tenant_id == tenant_id for item in db.scalars(select(Proposal).where(Proposal.incident_id == incident_id)))

    first_risk = detail["inventory_risk"]["inventory_risk_index"]
    first_procurement = next(item for item in detail["proposals"] if "采购" in item["agent_name"])
    with SessionLocal() as db:
        inventory = db.scalar(select(InventoryEntity).where(InventoryEntity.tenant_id == tenant_id, InventoryEntity.material_id == f"MAT-IMPORT-{suffix}"))
        supplier = db.scalar(select(SupplierMaterial).where(SupplierMaterial.tenant_id == tenant_id, SupplierMaterial.material_id == f"MAT-IMPORT-{suffix}"))
        inventory.on_hand_qty = inventory.available_qty = 260
        supplier.supplier_price = 29
        supplier.lead_time_hours = 72
        db.commit()
    rerun = client.post(f"/api/v1/incidents/{incident_id}/proposals:generate", headers=_headers())
    assert rerun.status_code == 202 and rerun.json()["jobId"] != job_id
    rerun_id = rerun.json()["jobId"]
    while time.monotonic() < deadline + 30:
        rerun_body = client.get(f"/api/v1/jobs/{rerun_id}", headers=_headers()).json()
        if rerun_body["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert rerun_body["status"] == "succeeded", rerun_body
    changed = client.get(f"/api/v1/incidents/{incident_id}/decision-detail", headers=_headers()).json()
    changed_procurement = next(item for item in changed["proposals"] if "采购" in item["agent_name"])
    assert changed["inventory_risk"]["inventory_risk_index"] < first_risk
    assert changed_procurement["total_cost"] != first_procurement["total_cost"]
    assert changed_procurement["lead_time_impact"] > first_procurement["lead_time_impact"]

    other_tenant = f"tenant-c1-job-other-{suffix}"
    with SessionLocal() as db:
        db.add(Tenant(id=other_tenant, name="第二租户", industry="制造", scale="small", status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        foreign_incident = Incident(id=f"inc-other-{suffix}", tenant_id=other_tenant, code=f"inc-other-{suffix}", title="第二租户事件", type="manual", level="low", status="planning", owner="", source_risk_ids=[], loss=0, cost=0)
        db.add(foreign_incident)
        foreign_job = Job(id=f"job-other-{suffix}", tenant_id=other_tenant, kind="decision", resource_id="none", idempotency_key=f"other:{suffix}", status="pending", progress=0, result={})
        db.add(foreign_job)
        db.commit()
    assert client.get(f"/api/v1/jobs/{foreign_job.id}", headers=_headers()).status_code == 404
    assert client.get(f"/api/v1/incidents/{foreign_incident.id}", headers=_headers()).status_code == 404

    # Regression proof: _run_decision_job and its decision worker acquire Sessions
    # in different threads; no request Session object is passed to either boundary.
    thread_ids: list[int] = []
    real_factory = jobs.SessionLocal
    ctx = AuthContext("u-scm_lead", tenant_id, "供应链负责人", "scm_lead", ())
    with SessionLocal() as db:
        incident2, _ = _add_scenario(db, tenant_id, f"{suffix}-thread", stock=60)
        job2 = Job(id=f"job-thread-{suffix}", tenant_id=tenant_id, kind="decision", resource_id=incident2, idempotency_key=f"thread:{suffix}", status="pending", progress=0, result={})
        db.add(job2)
        db.commit()

    def tracked_factory():
        thread_ids.append(threading.get_ident())
        return real_factory()

    with patch("src.webapi.jobs.SessionLocal", side_effect=tracked_factory):
        jobs._run_decision_job(job2.id, ctx)
    assert len(set(thread_ids)) >= 2
    with SessionLocal() as db:
        assert db.get(Job, job2.id).status == "succeeded"
    print(json.dumps({
        "c1Acceptance": {
            "incidentId": incident_id,
            "firstJobId": job_id,
            "rerunJobId": rerun_id,
            "firstRiskIndex": first_risk,
            "changedRiskIndex": changed["inventory_risk"]["inventory_risk_index"],
            "firstProcurementCostCny": first_procurement["total_cost"],
            "changedProcurementCostCny": changed_procurement["total_cost"],
            "firstLeadDays": first_procurement["lead_time_impact"],
            "changedLeadDays": changed_procurement["lead_time_impact"],
            "supplierPriceCny": changed_procurement["economic_basis"]["unit_price_cny"],
            "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
        }
    }, ensure_ascii=False))
