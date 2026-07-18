"""Deterministic import recognition agent with explainable confidence scores."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .enterprise_import_catalog import IMPORT_TYPE_CATALOG


EXPECTED_FIELDS: dict[str, set[str]] = {
    "material": {"material_id", "material_name", "category", "unit", "criticality", "standard_cost"},
    "supplier": {"supplier_id", "supplier_name", "supplier_tier", "reliability_score", "quality_score"},
    "supplier_material": {"supplier_material_id", "supplier_id", "material_id", "lead_time_hours", "supplier_rank"},
    "customer": {"customer_id", "customer_name", "customer_level", "credit_limit", "payment_terms_days"},
    "warehouse": {"warehouse_id", "warehouse_name", "warehouse_type", "capacity_units", "manager"},
    "inventory": {"inventory_id", "material_id", "warehouse_id", "on_hand_qty", "available_qty"},
    "inventory_snapshot": {"snapshot_id", "snapshot_date", "material_id", "warehouse_id", "inventory_value"},
    "inventory_movement": {"movement_id", "movement_type", "quantity", "reference_type", "movement_at"},
    "shipment": {"shipment_id", "purchase_order_id", "transport_mode", "carrier", "tracking_number"},
    "order": {"sales_order_id", "customer_id", "order_created_at", "promised_delivery_at", "order_status"},
    "order_line": {"sales_order_line_id", "sales_order_id", "line_no", "material_id", "ordered_qty"},
    "purchase_order": {"purchase_order_id", "supplier_id", "expected_arrival_at", "purchase_status", "buyer"},
    "purchase_order_line": {"purchase_order_line_id", "purchase_order_id", "line_no", "material_id", "received_qty"},
    "production_plan": {"production_plan_id", "plant_warehouse_id", "finished_material_id", "planned_qty", "plan_status"},
    "quality_inspection": {"inspection_id", "inspected_qty", "defect_qty", "inspection_type", "inspector"},
    "supplier_performance": {"supplier_performance_id", "period", "on_time_delivery_rate", "defect_rate", "score"},
    "disruption_event": {"event_id", "event_type", "severity", "risk_score", "affected_material_id"},
    "historical_decision": {"case_id", "event_id", "selected_strategy", "actual_cost", "human_rating"},
}


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9_\u4e00-\u9fff]+", value.lower()) if token}


def recognize_import_type(file_name: str, headers: Iterable[str] = ()) -> dict[str, Any]:
    """Return a ranked, explainable classification; low confidence requires user choice."""

    stem = Path(file_name).stem.lower().replace("-", "_").replace(" ", "_")
    header_set = {str(header).strip().lower() for header in headers if str(header).strip()}
    ranked: list[dict[str, Any]] = []
    for value, definition in IMPORT_TYPE_CATALOG.items():
        source_table = str(definition["source_table"])
        filename_exact = stem == source_table or stem.rstrip("_0123456789") == source_table
        filename_hint = source_table in stem or value in stem
        expected = EXPECTED_FIELDS[value]
        matches = sorted(header_set & expected)
        header_score = len(matches) / max(len(expected), 1)
        score = min(1.0, (0.72 if filename_exact else 0.3 if filename_hint else 0.0) + header_score * 0.7)
        ranked.append({
            "type": value, "label": definition["label"], "score": round(score, 3),
            "reasons": ([f"文件名匹配 {source_table}"] if filename_exact or filename_hint else [])
            + ([f"命中字段：{'、'.join(matches[:6])}"] if matches else []),
        })
    ranked.sort(key=lambda item: (-item["score"], item["type"]))
    best = ranked[0]
    confident = best["score"] >= 0.55 and (len(ranked) == 1 or best["score"] - ranked[1]["score"] >= 0.12)
    return {
        "recognizedType": best["type"] if confident else None,
        "label": best["label"] if confident else "待人工指定",
        "confidence": best["score"],
        "requiresConfirmation": True,
        "reasons": best["reasons"] or ["未发现足够稳定的文件名或字段特征"],
        "candidates": ranked[:3],
    }


def headers_from_rows(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    for row in rows:
        return [str(key) for key in row.keys()]
    return []
