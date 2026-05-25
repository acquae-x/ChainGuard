import pytest

from src.config_loader import load_risk_weights, load_thresholds
from src.data_loader import load_inventory
from src.inventory_monitor import calculate_inventory_risk


def test_calculate_inventory_risk_matches_demo_scenario():
    result = calculate_inventory_risk(load_inventory(), load_risk_weights(), load_thresholds())

    assert result["support_hours"] == 36
    assert result["safety_stock_gap"] == 2600
    assert result["safety_stock_gap_rate"] == pytest.approx(0.4194, abs=0.0001)
    assert result["transit_delay_hours"] == 72
    assert result["critical_order_coverage_rate"] == pytest.approx(0.72)
    assert result["warning_level"] == "黄色预警"
    assert result["should_trigger_response"] is True
    assert result["inventory_risk_index"] == pytest.approx(70.25)
    assert result["explanation"]


def test_calculate_inventory_risk_raises_for_missing_field():
    inventory = load_inventory()
    inventory.pop("current_stock")

    with pytest.raises(ValueError, match="current_stock"):
        calculate_inventory_risk(inventory, load_risk_weights(), load_thresholds())


def test_calculate_inventory_risk_raises_for_zero_consumption():
    inventory = load_inventory()
    inventory["hourly_consumption"] = 0

    with pytest.raises(ValueError, match="hourly_consumption"):
        calculate_inventory_risk(inventory, load_risk_weights(), load_thresholds())
