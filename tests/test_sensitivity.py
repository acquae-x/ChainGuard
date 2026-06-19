import copy
import json

import pytest

from src.sensitivity import run_sensitivity


_MINIMAL_INVENTORY = {
    "material_id": "MAT-001",
    "material_name": "测试物料",
    "current_stock": 3600,
    "hourly_consumption": 150,
    "safety_stock": 2000,
    "planned_arrival_hours": 24,
    "estimated_arrival_hours": 72,
    "critical_order_demand": 1200,
    "external_risk_score": 60,
}

_MINIMAL_CONTEXT = {
    "inventory": _MINIMAL_INVENTORY,
    "events": [{"event_type": "test", "title": "test"}],
    "suppliers": [],
}


def _context():
    return copy.deepcopy(_MINIMAL_CONTEXT)


def test_run_sensitivity_returns_list_with_required_keys():
    results = run_sensitivity(
        "current_stock",
        [720, 3600],
        baseline_context=_context(),
    )

    assert len(results) == 2
    assert {
        "param_value",
        "inventory_risk_index",
        "support_hours",
        "should_trigger_response",
    } <= set(results[0])


def test_run_sensitivity_lower_stock_higher_risk():
    results = run_sensitivity(
        "current_stock",
        [720, 7200],
        baseline_context=_context(),
    )

    assert results[0]["inventory_risk_index"] > results[1]["inventory_risk_index"]


def test_run_sensitivity_result_is_json_serializable():
    results = run_sensitivity(
        "current_stock",
        [720, 3600, 7200],
        baseline_context=_context(),
    )

    assert json.dumps(results, ensure_ascii=False)


def test_run_sensitivity_single_value_returns_one_row():
    results = run_sensitivity(
        "current_stock",
        [3600],
        baseline_context=_context(),
    )

    assert len(results) == 1
    assert results[0]["param_value"] == 3600


def test_run_sensitivity_empty_values_returns_empty():
    assert run_sensitivity("current_stock", [], baseline_context=_context()) == []


def test_run_sensitivity_unsupported_param_raises():
    with pytest.raises(ValueError, match="Unsupported param"):
        run_sensitivity("unknown_field", [1], baseline_context=_context())


def test_run_sensitivity_custom_baseline_context_used():
    context = _context()
    context["inventory"]["hourly_consumption"] = 100

    results = run_sensitivity(
        "current_stock",
        [1000],
        baseline_context=context,
    )

    assert results[0]["support_hours"] == 10


def test_run_sensitivity_param_value_order_preserved():
    values = [3600, 720, 7200]
    results = run_sensitivity(
        "current_stock",
        values,
        baseline_context=_context(),
    )

    assert [row["param_value"] for row in results] == values
