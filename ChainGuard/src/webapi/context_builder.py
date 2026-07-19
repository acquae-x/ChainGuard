from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config_loader import load_risk_weights, load_thresholds
from src.scenario_loader import TRANSPORT_OPTIONS

from .errors import ApiError
from .models import (
    CustomerEntity,
    Incident,
    InventoryEntity,
    Material,
    Risk,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    TenantConfig,
)


class ContextBuildError(ApiError):
    """A safe, structured C1 readiness failure suitable for API/job responses."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(status_code, code, message)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryContext(StrictModel):
    material_id: str
    material_name: str
    current_stock: float
    hourly_consumption: float
    safety_stock: float
    in_transit_qty: float
    planned_arrival_hours: float
    estimated_arrival_hours: float
    critical_order_demand: float
    external_risk_score: float = Field(ge=0, le=100)


class OrderContext(StrictModel):
    order_id: str
    customer_name: str
    priority: Literal["A", "B", "C"]
    required_material: str
    demand: float
    demand_qty: float
    delivery_hours: float
    due_hours: float
    penalty_cost: float
    gross_profit: float
    order_amount: float | None = None


class SupplierContext(StrictModel):
    supplier_id: str
    supplier_name: str
    material_id: str
    status: str
    available_qty: float
    lead_time_hours: float
    delay_hours: float
    cost_multiplier: float
    reliability_score: float
    region: str
    supplier_rank: int
    supplier_price: float | None = None


class TransportContext(StrictModel):
    mode: Literal["air", "truck", "rail", "sea"]
    name: str
    available: bool
    estimated_hours: float
    cost_multiplier: float
    cost_level: str
    risk_note: str


class EventContext(StrictModel):
    event_id: str
    event_type: str
    type: str
    title: str
    severity: str
    event_status: str
    location: str
    affected_supplier: str
    affected_material: str
    affected_route: str
    delay_hours: float
    estimated_delay_hours: float
    external_risk_score: float
    weather_risk: float
    description: str


class DataQualityModel(StrictModel):
    level: Literal["full", "degraded"]
    blocking: list[str]
    degraded: list[str]
    estimated_fields: list[str]


class EngineContext(BaseModel):
    """Formal Web-to-engine contract. Additive C1 metadata remains explicit."""

    model_config = ConfigDict(extra="forbid")
    inventory: InventoryContext
    orders: list[OrderContext]
    suppliers: list[SupplierContext]
    transport_options: list[TransportContext]
    events: list[EventContext]
    derived_metrics: dict[str, Any]
    data_quality: DataQualityModel
    configuration: dict[str, Any]


@dataclass
class DataQuality:
    level: Literal["full", "degraded"] = "full"
    blocking: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    estimated_fields: list[str] = field(default_factory=list)

    def degrade(self, reason: str, *estimated_fields: str) -> None:
        self.level = "degraded"
        if reason not in self.degraded:
            self.degraded.append(reason)
        for name in estimated_fields:
            if name not in self.estimated_fields:
                self.estimated_fields.append(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "blocking": list(self.blocking),
            "degraded": list(self.degraded),
            "estimated_fields": list(self.estimated_fields),
        }


@dataclass(frozen=True)
class TenantDecisionInputs:
    context: dict[str, Any]
    data_quality: DataQuality
    thresholds: dict[str, Any]
    risk_weights: dict[str, Any]
    configuration: dict[str, Any]


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_CLOSED_ORDER_STATUSES = {"delivered", "cancelled", "canceled", "closed", "已交付", "已取消"}
_HIGH_LEVELS = {"high", "critical", "高", "严重"}
_COEFFICIENT_DEFAULTS = {
    "penalty_rate": {"A": 0.20, "B": 0.10, "C": 0.05},
    "gross_profit_rate": {"A": 0.25, "B": 0.20, "C": 0.15},
}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hours_until(value: datetime | None, now: datetime) -> float:
    normalized = _utc(value)
    return max((normalized - now).total_seconds() / 3600.0, 0.0) if normalized else 0.0


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.search(str(value).replace(",", ""))
    return float(match.group()) if match else None


def _priority(value: Any) -> Literal["A", "B", "C"]:
    text = str(value or "C").strip().upper()
    if text.startswith("A") or text in {"VIP", "核心", "关键"}:
        return "A"
    if text.startswith("B") or text in {"重要"}:
        return "B"
    return "C"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class TenantContextBuilder:
    """Build one incident's complete, tenant-isolated engine context from C2 entities."""

    def __init__(self, db: Session, tenant_id: str, *, now: datetime | None = None) -> None:
        if not str(tenant_id or "").strip():
            raise ContextBuildError("CG-2510", "租户标识不能为空", status_code=404)
        self.db = db
        self.tenant_id = tenant_id
        self.now = _utc(now) or datetime.now(timezone.utc)

    def build(self, incident_id: str) -> TenantDecisionInputs:
        incident = self.db.scalar(
            select(Incident).where(Incident.id == incident_id, Incident.tenant_id == self.tenant_id)
        )
        if incident is None:
            raise ContextBuildError("CG-2510", "事件不存在", status_code=404)

        risks = list(
            self.db.scalars(
                select(Risk).where(
                    Risk.tenant_id == self.tenant_id,
                    Risk.id.in_(list(incident.source_risk_ids or [])),
                )
            ).all()
        )
        material = self._resolve_material(risks)
        if material is None:
            raise ContextBuildError("CG-2511", "事件未关联租户内有效物料")
        if material.daily_consumption is None or float(material.daily_consumption) <= 0:
            raise ContextBuildError("CG-2512", "物料日消耗量缺失或不大于 0")

        quality = DataQuality()
        delay = self._event_delay(incident, risks, quality)
        affected_supplier = self._resolve_affected_supplier(risks)
        risk_score = max([float(risk.score or 0) for risk in risks] or [0.0])
        inventory, inventory_rows, arrival = self._inventory(material, delay, quality)
        inventory["external_risk_score"] = risk_score
        orders = self._orders(material, quality)
        suppliers = self._suppliers(material, affected_supplier, delay, quality)
        transport, transport_config = self._transport_options(incident, risks)
        thresholds, risk_weights, configuration = self._decision_configuration(transport_config)
        coefficients, coefficient_meta = self._estimation_coefficients()
        configuration["items"]["estimation_coefficients"] = coefficient_meta
        orders = self._apply_financial_estimates(orders, coefficients, quality)

        critical_orders = [order for order in orders if order["priority"] == "A"]
        critical_demand = sum(order["demand_qty"] for order in critical_orders)
        inventory["critical_order_demand"] = float(critical_demand)
        event = self._event_context(
            incident, risks, material.material_id, affected_supplier, delay, risk_score
        )
        derived = self._derived_metrics(inventory, inventory_rows, orders, suppliers, arrival)
        if not orders:
            quality.degrade("no_orders")
        if not suppliers:
            quality.degrade("no_suppliers")

        configuration["items"]["transport_options"] = transport_config
        configuration["source"] = (
            "tenant_config" if any(item.get("source") == "tenant_config" for item in configuration["items"].values())
            else "expert_default"
        )
        configuration["fallback_reasons"] = [
            {"config_type": name, "reason": item["fallback_reason"]}
            for name, item in configuration["items"].items()
            if item.get("fallback_reason")
        ]
        context = {
            "inventory": inventory,
            "orders": orders,
            "suppliers": suppliers,
            "transport_options": transport,
            "events": [event],
            "derived_metrics": derived,
            "data_quality": quality.to_dict(),
            "configuration": configuration,
        }
        validated = EngineContext.model_validate(context).model_dump()
        return TenantDecisionInputs(validated, quality, thresholds, risk_weights, configuration)

    def readiness(self, incident_id: str) -> dict[str, Any]:
        try:
            built = self.build(incident_id)
        except ContextBuildError as error:
            return {
                "ready": False,
                "level": "blocked",
                "blocking": [{"code": error.code, "message": error.message}],
                "degraded": [],
            }
        context = built.context
        return {
            "ready": True,
            "level": built.data_quality.level,
            "blocking": [],
            "degraded": built.data_quality.degraded,
            "checks": {
                "material": context["inventory"]["material_id"],
                "hourlyConsumption": context["inventory"]["hourly_consumption"],
                "inventoryRows": context["derived_metrics"]["inventory_record_count"],
                "supplierCount": len(context["suppliers"]),
                "orderCount": len(context["orders"]),
                "safetyStockConfigured": "missing_safety_stock" not in built.data_quality.degraded,
                "delaySource": "estimated" if "event.delay_hours" in built.data_quality.estimated_fields else "risk",
            },
            "configuration": built.configuration,
        }

    def _resolve_material(self, risks: list[Risk]) -> Material | None:
        identifiers: list[str] = []
        names: list[str] = []
        for risk in risks:
            details = risk.details if isinstance(risk.details, dict) else {}
            for key in ("material_id", "materialId", "affected_material_id", "affectedMaterialId", "material"):
                value = str(details.get(key) or "").strip()
                if value:
                    identifiers.append(value)
                    names.append(value)
            if str(risk.object_type or "").lower() in {"material", "物料"}:
                names.append(str(risk.object_name or "").strip())
        if not identifiers and not names:
            return None
        return self.db.scalar(
            select(Material)
            .where(
                Material.tenant_id == self.tenant_id,
                (Material.material_id.in_(identifiers)) | (Material.material_name.in_(names)),
            )
            .order_by(Material.material_id)
        )

    def _event_delay(self, incident: Incident, risks: list[Risk], quality: DataQuality) -> float:
        candidates: list[float] = []
        for risk in risks:
            details = risk.details if isinstance(risk.details, dict) else {}
            for key in ("estimated_delay_hours", "estimatedDelayHours", "delay_hours", "delayHours", "delay"):
                parsed = _number(details.get(key))
                if parsed is not None and parsed >= 0:
                    candidates.append(parsed)
        if candidates:
            return max(candidates)
        if str(incident.level or "").strip().lower() in _HIGH_LEVELS:
            raise ContextBuildError("CG-2514", "高风险事件缺少预计延误")
        quality.degrade("default_event_delay", "event.delay_hours", "event.estimated_delay_hours")
        return 24.0

    def _resolve_affected_supplier(self, risks: list[Risk]) -> str:
        values: list[str] = []
        for risk in risks:
            details = risk.details if isinstance(risk.details, dict) else {}
            for key in ("supplier_id", "supplierId", "affected_supplier_id", "affectedSupplierId", "supplier"):
                value = str(details.get(key) or "").strip()
                if value:
                    values.append(value)
            if str(risk.object_type or "").lower() in {"supplier", "供应商"}:
                values.append(str(risk.object_name or "").strip())
        if not values:
            return ""
        supplier = self.db.scalar(
            select(SupplierEntity).where(
                SupplierEntity.tenant_id == self.tenant_id,
                (SupplierEntity.supplier_id.in_(values)) | (SupplierEntity.supplier_name.in_(values)),
            )
        )
        return supplier.supplier_id if supplier else ""

    def _inventory(
        self, material: Material, delay: float, quality: DataQuality
    ) -> tuple[dict[str, Any], list[InventoryEntity], dict[str, datetime | None]]:
        aggregate = self.db.execute(
            select(
                func.count(InventoryEntity.id),
                func.coalesce(func.sum(InventoryEntity.on_hand_qty), 0.0),
                func.coalesce(func.sum(InventoryEntity.available_qty), 0.0),
                func.coalesce(func.sum(InventoryEntity.safety_stock_qty), 0.0),
                func.coalesce(func.sum(InventoryEntity.in_transit_qty), 0.0),
                func.min(InventoryEntity.planned_arrival_at),
                func.min(InventoryEntity.estimated_arrival_at),
            ).where(
                InventoryEntity.tenant_id == self.tenant_id,
                InventoryEntity.material_id == material.material_id,
            )
        ).one()
        if int(aggregate[0] or 0) == 0:
            raise ContextBuildError("CG-2513", "物料缺少库存记录")
        rows = list(
            self.db.scalars(
                select(InventoryEntity).where(
                    InventoryEntity.tenant_id == self.tenant_id,
                    InventoryEntity.material_id == material.material_id,
                )
            ).all()
        )
        hourly = float(material.daily_consumption) / 24.0
        safety = float(aggregate[3] or 0)
        if safety <= 0:
            # The existing scorer requires a positive denominator. Use an explicit one-day
            # expert estimate and expose the substitution in data_quality (never demo data).
            safety = hourly * 24.0
            quality.degrade("missing_safety_stock", "inventory.safety_stock")
        planned_at = _utc(aggregate[5])
        estimated_at = _utc(aggregate[6])
        if planned_at is None and estimated_at is None:
            quality.degrade(
                "missing_arrival_information",
                "inventory.planned_arrival_hours",
                "inventory.estimated_arrival_hours",
            )
        planned_hours = _hours_until(planned_at, self.now)
        if estimated_at is not None:
            estimated_hours = _hours_until(estimated_at, self.now)
        elif planned_at is not None:
            estimated_at = planned_at + timedelta(hours=delay)
            estimated_hours = planned_hours + delay
            quality.degrade("estimated_arrival_from_event_delay", "inventory.estimated_arrival_hours")
        else:
            estimated_hours = 0.0
        return {
            "material_id": material.material_id,
            "material_name": material.material_name or material.material_id,
            "current_stock": float(aggregate[1] or 0),
            "hourly_consumption": hourly,
            "safety_stock": safety,
            "in_transit_qty": float(aggregate[4] or 0),
            "planned_arrival_hours": planned_hours,
            "estimated_arrival_hours": estimated_hours,
            "critical_order_demand": 0.0,
            "external_risk_score": 0.0,
        }, rows, {"planned": planned_at, "estimated": estimated_at}

    def _orders(self, material: Material, quality: DataQuality) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(
                SalesOrder.sales_order_id,
                CustomerEntity.customer_name,
                CustomerEntity.customer_level,
                SalesOrder.promised_delivery_at,
                SalesOrder.order_amount,
                SalesOrder.gross_profit,
                SalesOrder.penalty_cost,
                func.coalesce(func.sum(SalesOrderLine.ordered_qty), 0.0).label("demand"),
            )
            .join(
                SalesOrderLine,
                (SalesOrderLine.tenant_id == SalesOrder.tenant_id)
                & (SalesOrderLine.sales_order_id == SalesOrder.sales_order_id),
            )
            .join(
                CustomerEntity,
                (CustomerEntity.tenant_id == SalesOrder.tenant_id)
                & (CustomerEntity.customer_id == SalesOrder.customer_id),
            )
            .where(
                SalesOrder.tenant_id == self.tenant_id,
                SalesOrderLine.tenant_id == self.tenant_id,
                CustomerEntity.tenant_id == self.tenant_id,
                SalesOrderLine.material_id == material.material_id,
                func.lower(func.coalesce(SalesOrder.order_status, "")).not_in(_CLOSED_ORDER_STATUSES),
            )
            .group_by(
                SalesOrder.sales_order_id,
                CustomerEntity.customer_name,
                CustomerEntity.customer_level,
                SalesOrder.promised_delivery_at,
                SalesOrder.order_amount,
                SalesOrder.gross_profit,
                SalesOrder.penalty_cost,
            )
            .order_by(SalesOrder.promised_delivery_at, SalesOrder.sales_order_id)
        ).all()
        output: list[dict[str, Any]] = []
        for row in rows:
            due = _hours_until(row.promised_delivery_at, self.now)
            demand = float(row.demand or 0)
            output.append({
                "order_id": row.sales_order_id,
                "customer_name": row.customer_name or "未命名客户",
                "priority": _priority(row.customer_level),
                "required_material": material.material_id,
                "demand": demand,
                "demand_qty": demand,
                "delivery_hours": due,
                "due_hours": due,
                "penalty_cost": row.penalty_cost,
                "gross_profit": row.gross_profit,
                "order_amount": row.order_amount,
            })
        return output

    def _suppliers(
        self, material: Material, affected_supplier: str, delay: float, quality: DataQuality
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(SupplierMaterial, SupplierEntity)
            .join(
                SupplierEntity,
                (SupplierEntity.tenant_id == SupplierMaterial.tenant_id)
                & (SupplierEntity.supplier_id == SupplierMaterial.supplier_id),
            )
            .where(
                SupplierMaterial.tenant_id == self.tenant_id,
                SupplierEntity.tenant_id == self.tenant_id,
                SupplierMaterial.material_id == material.material_id,
                SupplierMaterial.qualified.is_(True),
            )
            .order_by(
                SupplierMaterial.supplier_rank.asc().nulls_last(),
                SupplierEntity.supplier_id,
            )
        ).all()
        output: list[dict[str, Any]] = []
        for relation, supplier in rows:
            reliability = supplier.reliability_score
            if reliability is None:
                reliability = 0.0
                quality.degrade(
                    "missing_supplier_reliability",
                    f"suppliers[{len(output)}].reliability_score",
                )
            output.append({
                "supplier_id": supplier.supplier_id,
                "supplier_name": supplier.supplier_name or supplier.supplier_id,
                "material_id": material.material_id,
                "status": supplier.status or ("受事件影响" if supplier.supplier_id == affected_supplier else "可用"),
                "available_qty": float(relation.available_emergency_qty or 0),
                "lead_time_hours": float(relation.lead_time_hours or 0),
                "delay_hours": delay if supplier.supplier_id == affected_supplier else 0.0,
                "cost_multiplier": float(relation.emergency_cost_multiplier or 1.0),
                "reliability_score": float(reliability),
                "region": supplier.region or "",
                "supplier_rank": int(relation.supplier_rank or 2**31 - 1),
                "supplier_price": None if relation.supplier_price is None else float(relation.supplier_price),
            })
        return output

    def _transport_options(
        self, incident: Incident, risks: list[Risk]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        config, meta = self._approved_config("transport_options")
        raw = config.payload if config is not None else copy.deepcopy(TRANSPORT_OPTIONS)
        if isinstance(raw, dict):
            raw = raw.get("options") or []
        route = self._risk_text(risks, "affected_route", "affectedRoute", "route")
        options: list[dict[str, Any]] = []
        for template in raw:
            option = dict(template)
            mode = "truck" if str(option.get("mode", "")).lower() == "road" else str(option.get("mode", "")).lower()
            unavailable = (
                incident.type == "port_shutdown" and mode == "sea"
            ) or (incident.type == "route_blockage" and mode in {"truck", "rail"})
            options.append({
                "mode": mode,
                "name": str(option.get("name") or mode),
                "available": bool(option.get("available", True)) and not unavailable,
                "estimated_hours": float(option.get("estimated_hours") or 0),
                "cost_multiplier": float(option.get("cost_multiplier") or 1),
                "cost_level": str(option.get("cost_level") or ""),
                "risk_note": (
                    f"{route or '指定路线'} 受事件影响，当前不可用"
                    if unavailable else str(option.get("risk_note") or "")
                ),
            })
        return options, meta

    def _approved_config(self, config_type: str) -> tuple[TenantConfig | None, dict[str, Any]]:
        config = self.db.scalar(
            select(TenantConfig).where(
                TenantConfig.tenant_id == self.tenant_id,
                TenantConfig.config_type == config_type,
                TenantConfig.is_active.is_(True),
            )
        )
        if config is None:
            return None, {
                "source": "expert_default", "version": None,
                "fallback_reason": "no_active_tenant_config",
            }
        if not config.approved_by or config.approved_at is None:
            return None, {
                "source": "expert_default", "version": None,
                "ignored_version": config.version,
                "fallback_reason": "active_config_not_approved",
            }
        return config, {
            "source": "tenant_config", "version": config.version,
            "config_source": config.source, "fallback_reason": None,
        }

    def _decision_configuration(
        self, transport_meta: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        thresholds = load_thresholds()
        raw_weights = load_risk_weights()
        risk_weights = {
            "inventory_risk_weights": copy.deepcopy(raw_weights["inventory_risk_weights"]),
            "decision_score_weights": copy.deepcopy(raw_weights["decision_score_weights"]),
            "payoff_weights": copy.deepcopy(raw_weights.get("payoff_weights") or {}),
            "_inventory_weight_source": "expert",
            "_inventory_weight_sample_size": 0,
            "_inventory_weight_note": "租户无获批配置时使用专家默认值",
            "_score_weight_source": "expert",
            "_score_weight_note": "租户无获批配置时使用专家默认值",
            "_payoff_weight_source": "expert",
            "_trigger_threshold_value": thresholds["inventory_warning"]["inventory_risk_trigger"],
            "_trigger_threshold_source": "expert",
            "_trigger_threshold_note": "租户无获批配置时使用专家默认值",
            "_trigger_threshold_sample_size": 0,
        }
        items: dict[str, Any] = {"transport_options": transport_meta}
        threshold_config, threshold_meta = self._approved_config("thresholds")
        if threshold_config is not None and isinstance(threshold_config.payload, dict):
            thresholds = _deep_merge(thresholds, threshold_config.payload)
        items["thresholds"] = threshold_meta
        weights_config, weights_meta = self._approved_config("risk_weights")
        if weights_config is not None and isinstance(weights_config.payload, dict):
            payload = weights_config.payload
            for key in ("inventory_risk_weights", "decision_score_weights", "payoff_weights"):
                if isinstance(payload.get(key), dict):
                    risk_weights[key] = _deep_merge(risk_weights[key], payload[key])
            risk_weights["_inventory_weight_source"] = weights_config.source
            risk_weights["_score_weight_source"] = weights_config.source
            risk_weights["_payoff_weight_source"] = weights_config.source
        items["risk_weights"] = weights_meta
        risk_weights["_trigger_threshold_value"] = thresholds["inventory_warning"]["inventory_risk_trigger"]
        risk_weights["_trigger_threshold_source"] = threshold_meta["source"]
        return thresholds, risk_weights, {"source": "expert_default", "items": items, "fallback_reasons": []}

    def _estimation_coefficients(self) -> tuple[dict[str, Any], dict[str, Any]]:
        config, meta = self._approved_config("estimation_coefficients")
        values = copy.deepcopy(_COEFFICIENT_DEFAULTS)
        if config is not None and isinstance(config.payload, dict):
            values = _deep_merge(values, config.payload)
        return values, meta

    @staticmethod
    def _apply_financial_estimates(
        orders: list[dict[str, Any]], coefficients: dict[str, Any], quality: DataQuality
    ) -> list[dict[str, Any]]:
        for index, order in enumerate(orders):
            amount = order.get("order_amount")
            priority = order["priority"]
            if order.get("penalty_cost") is None:
                order["penalty_cost"] = float(amount or 0) * float(coefficients["penalty_rate"][priority])
                quality.degrade("estimated_order_financials", f"orders[{index}].penalty_cost")
            if order.get("gross_profit") is None:
                order["gross_profit"] = float(amount or 0) * float(coefficients["gross_profit_rate"][priority])
                quality.degrade("estimated_order_financials", f"orders[{index}].gross_profit")
        return orders

    def _event_context(
        self,
        incident: Incident,
        risks: list[Risk],
        material_id: str,
        affected_supplier: str,
        delay: float,
        risk_score: float,
    ) -> dict[str, Any]:
        event_type = incident.type or "manual"
        return {
            "event_id": incident.id,
            "event_type": event_type,
            "type": event_type,
            "title": incident.title,
            "severity": incident.level,
            "event_status": incident.status,
            "location": self._risk_text(risks, "location"),
            "affected_supplier": affected_supplier,
            "affected_material": material_id,
            "affected_route": self._risk_text(risks, "affected_route", "affectedRoute", "route"),
            "delay_hours": delay,
            "estimated_delay_hours": delay,
            "external_risk_score": risk_score,
            "weather_risk": _number(self._risk_value(risks, "weather_risk", "weatherRisk")) or 0.0,
            "description": self._risk_text(risks, "description") or incident.title,
        }

    def _derived_metrics(
        self,
        inventory: dict[str, Any],
        rows: list[InventoryEntity],
        orders: list[dict[str, Any]],
        suppliers: list[dict[str, Any]],
        arrival: dict[str, datetime | None],
    ) -> dict[str, Any]:
        available = sum(float(row.available_qty or 0) for row in rows)
        total_demand = sum(float(order["demand_qty"]) for order in orders)
        critical = [order for order in orders if order["priority"] == "A"]
        required = float(inventory["critical_order_demand"])
        return {
            "inventory_support_hours": float(inventory["current_stock"]) / float(inventory["hourly_consumption"]),
            "arrival_delay_hours": max(float(inventory["estimated_arrival_hours"]) - float(inventory["planned_arrival_hours"]), 0.0),
            "safety_stock_gap": max(float(inventory["safety_stock"]) - float(inventory["current_stock"]), 0.0),
            "inventory_shortage_qty": max(required - available - float(inventory["in_transit_qty"]), 0.0),
            "available_inventory_qty": available,
            "in_transit_qty": float(inventory["in_transit_qty"]),
            "nearest_planned_arrival_at": arrival["planned"].isoformat() if arrival["planned"] else None,
            "nearest_estimated_arrival_at": arrival["estimated"].isoformat() if arrival["estimated"] else None,
            "critical_order_exposure": {
                "order_count": len(critical),
                "demand_qty": required,
                "order_amount": sum(float(order.get("order_amount") or 0) for order in critical),
                "penalty_cost": sum(float(order["penalty_cost"]) for order in critical),
                "gross_profit": sum(float(order["gross_profit"]) for order in critical),
            },
            "supplier_alternatives": {
                "qualified_count": len(suppliers),
                "available_count": sum(1 for supplier in suppliers if supplier["available_qty"] > 0),
                "total_available_qty": sum(float(supplier["available_qty"]) for supplier in suppliers),
                "best_lead_time_hours": min([float(supplier["lead_time_hours"]) for supplier in suppliers] or [0.0]),
            },
            "total_open_order_demand": total_demand,
            "inventory_record_count": len(rows),
            "units": {
                "quantity": "piece",
                "time": "hour",
                "currency": "CNY",
                "risk_score": "0-100",
                "timestamp": "UTC ISO-8601",
            },
        }

    @staticmethod
    def _risk_value(risks: list[Risk], *keys: str) -> Any:
        for risk in risks:
            details = risk.details if isinstance(risk.details, dict) else {}
            for key in keys:
                if details.get(key) not in (None, ""):
                    return details[key]
        return None

    @classmethod
    def _risk_text(cls, risks: list[Risk], *keys: str) -> str:
        value = cls._risk_value(risks, *keys)
        return str(value or "").strip()


def build_incident_context(
    db: Session, tenant_id: str, incident_id: str
) -> tuple[dict[str, Any], DataQuality]:
    """Specification-compatible convenience entry point."""
    built = TenantContextBuilder(db, tenant_id).build(incident_id)
    return built.context, built.data_quality
