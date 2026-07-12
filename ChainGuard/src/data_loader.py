import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

INVENTORY_FIELDS = {
    "material_id",
    "material_name",
    "current_stock",
    "hourly_consumption",
    "safety_stock",
    "in_transit_qty",
    "planned_arrival_hours",
    "estimated_arrival_hours",
    "critical_order_demand",
    "external_risk_score",
}

ORDER_FIELDS = {
    "order_id",
    "customer_name",
    "priority",
    "required_material",
    "demand_qty",
    "due_hours",
    "penalty_cost",
    "gross_profit",
}

SUPPLIER_FIELDS = {
    "supplier_id",
    "supplier_name",
    "material_id",
    "status",
    "available_qty",
    "lead_time_hours",
    "delay_hours",
    "cost_multiplier",
}

TRANSPORT_FIELDS = {
    "mode",
    "name",
    "available",
    "estimated_hours",
    "cost_level",
    "risk_note",
}

EVENT_FIELDS = {
    "event_id",
    "event_type",
    "title",
    "location",
    "affected_supplier",
    "affected_route",
    "delay_hours",
    "external_risk_score",
    "weather_risk",
    "description",
}


def _resolve_data_path(path: str | Path) -> Path:
    data_path = Path(path)
    if data_path.is_absolute():
        return data_path

    project_relative = PROJECT_ROOT / data_path
    if project_relative.exists():
        return project_relative

    return DATA_DIR / data_path


def load_json(path: str | Path) -> Any:
    json_path = _resolve_data_path(path)
    if not json_path.exists():
        raise FileNotFoundError(f"数据文件不存在：{json_path}")

    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON 格式错误：{json_path}，{error}") from error


def _validate_required_fields(payload: Any, required_fields: set[str], dataset_name: str) -> None:
    records = payload if isinstance(payload, list) else [payload]
    if not records:
        raise ValueError(f"{dataset_name} 数据为空。")

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"{dataset_name} 第 {index} 条记录必须是对象。")
        missing_fields = sorted(required_fields - set(record))
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise ValueError(f"{dataset_name} 第 {index} 条记录缺少字段：{missing}")


def load_inventory() -> dict[str, Any]:
    data = load_json("inventory.json")
    _validate_required_fields(data, INVENTORY_FIELDS, "inventory")
    if data["hourly_consumption"] <= 0:
        raise ValueError("inventory.hourly_consumption 必须大于 0。")
    return data


def load_orders() -> list[dict[str, Any]]:
    data = load_json("orders.json")
    _validate_required_fields(data, ORDER_FIELDS, "orders")
    return data


def load_suppliers() -> list[dict[str, Any]]:
    data = load_json("suppliers.json")
    _validate_required_fields(data, SUPPLIER_FIELDS, "suppliers")
    return data


def load_transport_options() -> list[dict[str, Any]]:
    data = load_json("transport_options.json")
    _validate_required_fields(data, TRANSPORT_FIELDS, "transport_options")
    return data


def load_events() -> list[dict[str, Any]]:
    data = load_json("events.json")
    _validate_required_fields(data, EVENT_FIELDS, "events")
    return data


def load_demo_context() -> dict[str, Any]:
    inventory = load_inventory()
    support_hours = inventory["current_stock"] / inventory["hourly_consumption"]

    return {
        "inventory": inventory,
        "orders": load_orders(),
        "suppliers": load_suppliers(),
        "transport_options": load_transport_options(),
        "events": load_events(),
        "derived_metrics": {
            "inventory_support_hours": support_hours,
            "arrival_delay_hours": inventory["estimated_arrival_hours"] - inventory["planned_arrival_hours"],
            "safety_stock_gap": max(inventory["safety_stock"] - inventory["current_stock"], 0),
        },
    }
