from datetime import date

from src.proactive_monitor import scan_multisignal


def test_multisignal_scanner_emits_each_observable_signal():
    findings = scan_multisignal(
        as_of=date(2026, 6, 1),
        supplier_performance=[
            _performance("2026-04", 0.95, 4),
            _performance("2026-05", 0.80, 30),
        ],
        sales_orders=[
            {"sales_order_id": f"SO-{number}", "order_created_at": "2026-05-30T08:00:00+08:00"}
            for number in range(3)
        ] + [{"sales_order_id": "SO-old", "order_created_at": "2026-05-10T08:00:00+08:00"}],
        sales_order_lines=[
            {"sales_order_id": f"SO-{number}", "material_id": "MAT-1"}
            for number in range(3)
        ] + [{"sales_order_id": "SO-old", "material_id": "MAT-1"}],
        quality_inspections=[
            {
                "supplier_id": "SUP-1",
                "material_id": "MAT-1",
                "inspected_at": "2026-05-31T08:00:00+08:00",
                "inspected_qty": "100",
                "defect_qty": "20",
            }
        ],
        shipments=[
            {
                "purchase_order_id": "PO-1",
                "supplier_id": "SUP-1",
                "delay_hours": "24",
                "observed_at": "2026-05-31T08:00:00+08:00",
            }
        ],
        purchase_order_lines=[{"purchase_order_id": "PO-1", "material_id": "MAT-1"}],
    )

    assert {finding.signal for finding in findings} == {
        "supplier_performance",
        "demand_surge",
        "quality_batch",
        "in_transit_delay",
    }


def test_transit_without_observation_time_is_not_used():
    findings = scan_multisignal(
        as_of=date(2026, 6, 1),
        supplier_performance=[],
        sales_orders=[],
        sales_order_lines=[],
        quality_inspections=[],
        shipments=[{"purchase_order_id": "PO-1", "supplier_id": "SUP-1", "delay_hours": "72"}],
        purchase_order_lines=[{"purchase_order_id": "PO-1", "material_id": "MAT-1"}],
    )

    assert findings == []


def _performance(period: str, otd: float, delay: float) -> dict[str, str | float]:
    return {
        "supplier_id": "SUP-1",
        "period": period,
        "on_time_delivery_rate": otd,
        "average_delay_hours": delay,
    }
