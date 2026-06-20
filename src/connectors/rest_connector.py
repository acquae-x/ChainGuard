"""Generic REST adapter for the ChainGuard mock ERP API."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib import error, parse, request

from src.connectors.base import ErpConnector
from src.scenario_loader import ScenarioLoader


LOGGER = logging.getLogger(__name__)


class ErpConnectorError(RuntimeError):
    """Raised when an ERP connector request cannot be completed."""


class RestErpConnector(ErpConnector):
    """REST/OData-style adapter for ERP event pull and decision write-back."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        retries: int = 1,
        page_size: int = 500,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = max(0, retries)
        self.page_size = min(1000, max(1, page_size))

    def fetch_disruption_events(self) -> list[dict[str, Any]]:
        """Return valid disruption events from ERP, skipping malformed rows."""
        try:
            rows = self._fetch_resource("disruption-events")
        except ErpConnectorError as exc:
            LOGGER.error("Failed to fetch disruption events: %s", exc)
            return []

        events: list[dict[str, Any]] = []
        for row in rows:
            if not row.get("event_id"):
                LOGGER.warning("Skipping disruption event without event_id: %s", row)
                continue
            event = dict(row)
            event["event_id"] = str(event["event_id"])
            events.append(event)
        return events

    def fetch_context(self, event_id: str) -> dict[str, Any]:
        """Return a ScenarioLoader-compatible context for an ERP event."""
        event = self._find_event(event_id)
        material_id = str(event.get("affected_material_id") or "")
        if not material_id:
            raise ValueError(f"ERP event {event_id} does not include affected_material_id")

        material = self._get_first("materials", {"material_id": material_id})
        inventory_rows = self._fetch_resource("inventory", {"material_id": material_id})
        supplier_rows = self._build_suppliers(
            material_id,
            event.get("affected_supplier_id"),
            self._float(event.get("estimated_delay_hours")),
        )
        order_rows, critical_order_demand = self._build_orders(material_id)

        inventory = self._build_inventory(
            material_id,
            material,
            inventory_rows,
            event,
            critical_order_demand,
        )
        event_context = self._map_event(event, material_id)
        return {
            "inventory": inventory,
            "events": [event_context],
            "suppliers": supplier_rows,
            "orders": order_rows,
            "transport_options": ScenarioLoader._build_transport_options(
                str(event.get("event_type") or ""),
                event.get("affected_route"),
            ),
        }

    def load_context(self, event_id: str) -> dict[str, Any]:
        """Compatibility shim for DecisionOrchestrator.run_scenario()."""
        return self.fetch_context(event_id)

    def write_back_decision(self, decision: dict[str, Any]) -> bool:
        """Write a generated decision to the ERP decision endpoint."""
        payload = dict(decision)
        payload.setdefault("decision_status", "generated")
        payload.setdefault("human_approval_required", False)
        payload.setdefault("written_back_at", datetime.now(timezone.utc).isoformat())
        try:
            self._json_request("POST", "/api/v1/decisions", payload=payload)
            return True
        except ErpConnectorError as exc:
            LOGGER.error("Failed to write back decision %s: %s", decision.get("decision_id"), exc)
            return False

    def read_decisions(self) -> list[dict[str, Any]]:
        """Read decisions stored by the mock ERP, useful for smoke tests."""
        payload = self._json_request("GET", "/api/v1/decisions")
        if isinstance(payload, dict):
            items = payload.get("items", [])
            return [dict(item) for item in items if isinstance(item, dict)]
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        return []

    def _fetch_resource(
        self,
        resource: str,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page = 1
        filters = filters or {}
        while True:
            params = {"page": page, "page_size": self.page_size, **filters}
            payload = self._json_request("GET", f"/api/v1/{resource}", params=params)
            if not isinstance(payload, dict):
                raise ErpConnectorError(f"Unexpected ERP response for {resource}: {type(payload)!r}")
            items = payload.get("items", [])
            if not isinstance(items, list):
                raise ErpConnectorError(f"ERP resource {resource} returned non-list items")
            results.extend(dict(item) for item in items if isinstance(item, dict))
            total = self._int(payload.get("total"), len(results))
            if not items or len(results) >= total:
                break
            page += 1
        return results

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        query = f"?{parse.urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{query}"
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = request.Request(url, data=body, headers=headers, method=method)
                with request.urlopen(req, timeout=self.timeout) as response:
                    raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
            except (OSError, TimeoutError, json.JSONDecodeError, error.URLError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.1 * (attempt + 1))
        raise ErpConnectorError(f"ERP request failed: {method} {url}: {last_error}")

    def _find_event(self, event_id: str) -> dict[str, Any]:
        for event in self.fetch_disruption_events():
            if event.get("event_id") == event_id:
                return event
        raise ValueError(f"ERP event not found: {event_id}")

    def _get_first(self, resource: str, filters: dict[str, Any]) -> dict[str, Any]:
        rows = self._fetch_resource(resource, filters)
        for row in rows:
            if all(str(row.get(key)) == str(value) for key, value in filters.items()):
                return row
        return rows[0] if rows else {}

    def _build_inventory(
        self,
        material_id: str,
        material: dict[str, Any],
        inventory_rows: list[dict[str, Any]],
        event: dict[str, Any],
        critical_order_demand: float,
    ) -> dict[str, Any]:
        current_stock = sum(self._float(row.get("on_hand_qty")) for row in inventory_rows)
        safety_stock = sum(self._float(row.get("safety_stock_qty")) for row in inventory_rows)
        in_transit_qty = sum(self._float(row.get("in_transit_qty")) for row in inventory_rows)
        daily_consumption = self._float(material.get("daily_consumption"), 24.0)
        delay_hours = self._float(event.get("estimated_delay_hours"))
        risk_score = self._float(event.get("risk_score"))
        return {
            "material_id": material_id,
            "material_name": material.get("material_name") or material_id,
            "on_hand_qty": current_stock,
            "current_stock": current_stock,
            "hourly_consumption": max(daily_consumption / 24.0, 0.01),
            "safety_stock": safety_stock,
            "in_transit_qty": in_transit_qty,
            "planned_arrival_hours": 0.0,
            "estimated_arrival_hours": delay_hours,
            "critical_order_demand": critical_order_demand,
            "external_risk_score": risk_score,
        }

    def _map_event(self, event: dict[str, Any], material_id: str) -> dict[str, Any]:
        delay_hours = self._float(event.get("estimated_delay_hours"))
        risk_score = self._float(event.get("risk_score"))
        return {
            "event_id": str(event.get("event_id")),
            "event_type": event.get("event_type"),
            "type": event.get("event_type"),
            "title": event.get("event_title"),
            "severity": event.get("severity"),
            "external_risk_score": risk_score,
            "location": event.get("location"),
            "affected_supplier": event.get("affected_supplier_id"),
            "affected_material": material_id,
            "affected_route": event.get("affected_route"),
            "delay_hours": delay_hours,
            "estimated_delay_hours": delay_hours,
            "event_status": event.get("event_status"),
            "description": event.get("description"),
        }

    def _build_suppliers(
        self,
        material_id: str,
        affected_supplier_id: Any,
        estimated_delay_hours: float,
    ) -> list[dict[str, Any]]:
        supplier_materials = self._fetch_resource(
            "supplier-materials",
            {"material_id": material_id, "qualified": 1},
        )
        suppliers: list[dict[str, Any]] = []
        for relation in supplier_materials:
            if str(relation.get("material_id")) != material_id:
                continue
            if self._int(relation.get("qualified"), 1) != 1:
                continue
            supplier_id = str(relation.get("supplier_id") or "")
            if not supplier_id:
                continue
            supplier = self._get_first("suppliers", {"supplier_id": supplier_id})
            suppliers.append(
                {
                    "supplier_id": supplier_id,
                    "supplier_name": supplier.get("supplier_name") or supplier_id,
                    "material_id": material_id,
                    "status": supplier.get("status"),
                    "available_qty": self._float(relation.get("available_emergency_qty")),
                    "lead_time_hours": self._float(relation.get("lead_time_hours")),
                    "delay_hours": (
                        estimated_delay_hours
                        if supplier_id == str(affected_supplier_id or "")
                        else 0.0
                    ),
                    "cost_multiplier": self._float(
                        relation.get("emergency_cost_multiplier"),
                        1.0,
                    ),
                    "reliability_score": self._float(supplier.get("reliability_score")),
                    "region": supplier.get("region"),
                    "supplier_rank": self._int(relation.get("supplier_rank"), 999),
                }
            )
        return sorted(suppliers, key=lambda row: (row["supplier_rank"], row["supplier_id"]))

    def _build_orders(self, material_id: str) -> tuple[list[dict[str, Any]], float]:
        lines = self._fetch_resource("sales-order-lines", {"material_id": material_id})
        order_cache: dict[str, dict[str, Any]] = {}
        mapped: list[dict[str, Any]] = []
        critical_order_demand = 0.0
        for line in lines:
            if str(line.get("material_id")) != material_id:
                continue
            order_id = str(line.get("sales_order_id") or "")
            if not order_id:
                continue
            order = order_cache.get(order_id)
            if order is None:
                order = self._get_first("sales-orders", {"sales_order_id": order_id})
                order_cache[order_id] = order
            status = str(order.get("order_status") or "")
            if status in {"delivered", "cancelled"}:
                continue
            demand_qty = self._float(line.get("ordered_qty"))
            if order.get("customer_level") == "A" and status in {"at_risk", "pending"}:
                critical_order_demand += demand_qty
            delivery_hours = self._hours_until(order.get("promised_delivery_at"))
            mapped.append(
                {
                    "order_id": order_id,
                    "customer_name": order.get("customer_id"),
                    "priority": order.get("customer_level"),
                    "required_material": material_id,
                    "delivery_hours": delivery_hours,
                    "due_hours": delivery_hours,
                    "demand": demand_qty,
                    "demand_qty": demand_qty,
                    "gross_profit": self._float(order.get("gross_profit")),
                    "penalty_cost": self._float(order.get("penalty_cost")),
                }
            )
        mapped.sort(key=lambda row: row["delivery_hours"])
        return mapped[:20], critical_order_demand

    @staticmethod
    def _hours_until(value: Any) -> float:
        if not value:
            return 0.0
        try:
            due_at = datetime.fromisoformat(str(value))
            now = datetime.now(due_at.tzinfo or timezone.utc)
            return round((due_at - now).total_seconds() / 3600.0)
        except ValueError:
            return 0.0

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default
