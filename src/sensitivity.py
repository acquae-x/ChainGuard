import copy
from typing import Any

from src.config_loader import load_risk_weights, load_thresholds
from src.data_loader import load_demo_context
from src.inventory_monitor import calculate_inventory_risk


SUPPORTED_PARAMS = {"current_stock"}


def run_sensitivity(
    param: str,
    values: list[float | int],
    *,
    baseline_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if param not in SUPPORTED_PARAMS:
        raise ValueError(f"Unsupported param: {param!r}")
    if not values:
        return []

    context = baseline_context if baseline_context is not None else load_demo_context()
    risk_weights = load_risk_weights()
    thresholds = load_thresholds()
    results: list[dict[str, Any]] = []

    for value in values:
        inventory = copy.copy(context["inventory"])
        inventory[param] = value
        risk = calculate_inventory_risk(inventory, risk_weights, thresholds)
        results.append(
            {
                "param_value": value,
                "inventory_risk_index": risk["inventory_risk_index"],
                "support_hours": risk["support_hours"],
                "should_trigger_response": risk["should_trigger_response"],
            }
        )

    return results
