"""Point-in-time, multi-signal findings for experimental supply monitoring.

This module intentionally does not alter ``scan_supply_chain``.  It only
turns records that were observable on ``as_of`` into transparent findings;
the replay script owns the outcome labels and evaluation metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable


PERFORMANCE_OTD_DROP = 0.12
PERFORMANCE_DELAY_HOURS = 24.0
DEMAND_WINDOW_DAYS = 7
DEMAND_BASELINE_DAYS = 28
DEMAND_MIN_ORDERS = 3
QUALITY_WINDOW_DAYS = 30
QUALITY_DEFECT_RATE = 0.08
QUALITY_MIN_DEFECT_QTY = 20.0
TRANSIT_DELAY_HOURS = 24.0


@dataclass(frozen=True)
class SignalFinding:
    signal: str
    as_of: date
    supplier_id: str | None
    material_id: str | None
    evidence: dict[str, float | str]


def scan_multisignal(
    *,
    as_of: date,
    supplier_performance: Iterable[dict[str, Any]],
    sales_orders: Iterable[dict[str, Any]],
    sales_order_lines: Iterable[dict[str, Any]],
    quality_inspections: Iterable[dict[str, Any]],
    shipments: Iterable[dict[str, Any]],
    purchase_order_lines: Iterable[dict[str, Any]],
) -> list[SignalFinding]:
    """Return only findings supported by data observable on ``as_of``.

    ``shipments`` must include an ``observed_at`` timestamp to be eligible.
    Shipment rows without it are deliberately ignored: an eventual delay is
    not proof the delay was known at the historical scan time.
    """
    findings: list[SignalFinding] = []
    findings.extend(_supplier_performance_findings(as_of, supplier_performance))
    findings.extend(_demand_findings(as_of, sales_orders, sales_order_lines))
    findings.extend(_quality_findings(as_of, quality_inspections))
    findings.extend(_transit_findings(as_of, shipments, purchase_order_lines))
    return sorted(
        findings,
        key=lambda item: (item.signal, item.supplier_id or "", item.material_id or ""),
    )


def _supplier_performance_findings(
    as_of: date, rows: Iterable[dict[str, Any]]
) -> list[SignalFinding]:
    by_supplier: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        period = _month_start(row.get("period"))
        if period is None or _next_month(period) > as_of:
            continue
        by_supplier.setdefault(str(row["supplier_id"]), []).append(row)

    findings: list[SignalFinding] = []
    for supplier_id, records in by_supplier.items():
        ordered = sorted(records, key=lambda row: str(row["period"]), reverse=True)
        if len(ordered) < 2:
            continue
        current, previous = ordered[:2]
        current_otd = _number(current.get("on_time_delivery_rate"))
        previous_otd = _number(previous.get("on_time_delivery_rate"))
        delay = _number(current.get("average_delay_hours"))
        if previous_otd - current_otd >= PERFORMANCE_OTD_DROP or delay >= PERFORMANCE_DELAY_HOURS:
            findings.append(
                SignalFinding(
                    signal="supplier_performance",
                    as_of=as_of,
                    supplier_id=supplier_id,
                    material_id=None,
                    evidence={
                        "current_period": str(current["period"]),
                        "previous_period": str(previous["period"]),
                        "otd_drop": round(previous_otd - current_otd, 4),
                        "average_delay_hours": delay,
                    },
                )
            )
    return findings


def _demand_findings(
    as_of: date,
    sales_orders: Iterable[dict[str, Any]],
    sales_order_lines: Iterable[dict[str, Any]],
) -> list[SignalFinding]:
    order_dates = {
        str(row["sales_order_id"]): _as_date(row.get("order_created_at"))
        for row in sales_orders
    }
    recent: dict[str, set[str]] = {}
    baseline: dict[str, set[str]] = {}
    for line in sales_order_lines:
        order_id = str(line["sales_order_id"])
        order_date = order_dates.get(order_id)
        if order_date is None or order_date > as_of:
            continue
        age = (as_of - order_date).days
        material_id = str(line["material_id"])
        if 0 <= age < DEMAND_WINDOW_DAYS:
            recent.setdefault(material_id, set()).add(order_id)
        elif DEMAND_WINDOW_DAYS <= age < DEMAND_WINDOW_DAYS + DEMAND_BASELINE_DAYS:
            baseline.setdefault(material_id, set()).add(order_id)

    findings: list[SignalFinding] = []
    for material_id, order_ids in recent.items():
        recent_orders = len(order_ids)
        baseline_daily = len(baseline.get(material_id, set())) / DEMAND_BASELINE_DAYS
        if recent_orders >= DEMAND_MIN_ORDERS and recent_orders >= 2 * baseline_daily * DEMAND_WINDOW_DAYS:
            findings.append(
                SignalFinding(
                    signal="demand_surge",
                    as_of=as_of,
                    supplier_id=None,
                    material_id=material_id,
                    evidence={
                        "recent_orders": float(recent_orders),
                        "baseline_daily_orders": round(baseline_daily, 4),
                    },
                )
            )
    return findings


def _quality_findings(
    as_of: date, rows: Iterable[dict[str, Any]]
) -> list[SignalFinding]:
    totals: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        inspected_at = _as_date(row.get("inspected_at"))
        if inspected_at is None or inspected_at > as_of:
            continue
        if (as_of - inspected_at).days >= QUALITY_WINDOW_DAYS:
            continue
        key = (str(row["supplier_id"]), str(row["material_id"]))
        values = totals.setdefault(key, [0.0, 0.0])
        values[0] += _number(row.get("inspected_qty"))
        values[1] += _number(row.get("defect_qty"))

    findings: list[SignalFinding] = []
    for (supplier_id, material_id), (inspected, defective) in totals.items():
        defect_rate = defective / inspected if inspected else 0.0
        if defect_rate >= QUALITY_DEFECT_RATE and defective >= QUALITY_MIN_DEFECT_QTY:
            findings.append(
                SignalFinding(
                    signal="quality_batch",
                    as_of=as_of,
                    supplier_id=supplier_id,
                    material_id=material_id,
                    evidence={
                        "inspected_qty": inspected,
                        "defect_qty": defective,
                        "defect_rate": round(defect_rate, 4),
                    },
                )
            )
    return findings


def _transit_findings(
    as_of: date,
    shipments: Iterable[dict[str, Any]],
    purchase_order_lines: Iterable[dict[str, Any]],
) -> list[SignalFinding]:
    materials_by_po: dict[str, set[str]] = {}
    for line in purchase_order_lines:
        materials_by_po.setdefault(str(line["purchase_order_id"]), set()).add(
            str(line["material_id"])
        )

    findings: list[SignalFinding] = []
    for shipment in shipments:
        observed_at = _as_date(shipment.get("observed_at"))
        if observed_at is None or observed_at > as_of:
            continue
        delay = _number(shipment.get("delay_hours"))
        if delay < TRANSIT_DELAY_HOURS:
            continue
        for material_id in materials_by_po.get(str(shipment["purchase_order_id"]), set()):
            findings.append(
                SignalFinding(
                    signal="in_transit_delay",
                    as_of=as_of,
                    supplier_id=str(shipment["supplier_id"]),
                    material_id=material_id,
                    evidence={"delay_hours": delay, "observed_at": str(shipment["observed_at"])},
                )
            )
    return findings


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _month_start(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m").date()
    except ValueError:
        return None


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)
