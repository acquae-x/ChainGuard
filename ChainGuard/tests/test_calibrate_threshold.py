from src.parameter_calibration import calibrate_trigger_threshold
from src.config_loader import load_thresholds, load_risk_weights


def test_no_failure_data_returns_expert_trigger():
    """空列表 -> 返回 YAML 专家默认值，source 为 expert。"""
    expert_trigger = float(
        load_thresholds()["inventory_warning"]["inventory_risk_trigger"]
    )
    weights = dict(load_risk_weights()["inventory_risk_weights"])

    result = calibrate_trigger_threshold([], weights)

    assert result["value"] == expert_trigger
    assert result["_source"] == "expert"
    assert result["_sample_size"] == 0


def test_calibrated_trigger_below_expert_default():
    """足够失败样本 -> source 为 calibrated，value < 专家默认值 70。"""
    weights = dict(load_risk_weights()["inventory_risk_weights"])
    failure_record = {
        "outcome_status": "failed",
        "covered_demand_rate": 0.5,
        "actual_delay_hours": 20,
        "lost_orders": 2,
        "production_downtime_hours": 8,
    }
    records = [failure_record] * 10

    result = calibrate_trigger_threshold(records, weights)

    assert result["_source"] == "calibrated"
    assert result["_sample_size"] == 10
    assert result["value"] < 70


def test_trigger_threshold_changes_should_trigger_response():
    """校准阈值 35 vs 专家阈值 70 对同一场景产生相反的 should_trigger_response。"""
    from src.inventory_monitor import calculate_inventory_risk

    inventory = {
        "current_stock": 3000,
        "hourly_consumption": 100,
        "safety_stock": 6000,
        "planned_arrival_hours": 24,
        "estimated_arrival_hours": 48,
        "critical_order_demand": 4000,
        "external_risk_score": 30,
    }
    weights = {
        "shortage_urgency": 0.35,
        "order_importance": 0.25,
        "transit_delay": 0.20,
        "external_event": 0.20,
    }
    base_warning = {
        "yellow_support_hours": 48,
        "red_support_hours": 24,
        "safety_stock_gap_rate": 0.20,
        "transit_delay_hours": 24,
        "critical_order_coverage_rate": 0.80,
    }

    thresholds_expert     = {"inventory_warning": {**base_warning, "inventory_risk_trigger": 70}}
    thresholds_calibrated = {"inventory_warning": {**base_warning, "inventory_risk_trigger": 35}}

    result_expert = calculate_inventory_risk(
        inventory, {"inventory_risk_weights": weights}, thresholds_expert
    )
    result_calibrated = calculate_inventory_risk(
        inventory, {"inventory_risk_weights": weights}, thresholds_calibrated
    )

    assert result_expert["should_trigger_response"] is False
    assert result_calibrated["should_trigger_response"] is True


def test_different_failure_data_produces_different_thresholds():
    """低风险失败记录 -> 低阈值；高风险失败记录 -> 高阈值。"""
    weights = dict(load_risk_weights()["inventory_risk_weights"])

    low_risk_records = [
        {
            "outcome_status": "failed",
            "covered_demand_rate": 0.8,
            "actual_delay_hours": 5,
            "lost_orders": 0,
            "production_downtime_hours": 2,
        }
    ] * 6

    high_risk_records = [
        {
            "outcome_status": "failed",
            "covered_demand_rate": 0.1,
            "actual_delay_hours": 65,
            "lost_orders": 8,
            "production_downtime_hours": 50,
        }
    ] * 6

    result_low  = calibrate_trigger_threshold(low_risk_records, weights)
    result_high = calibrate_trigger_threshold(high_risk_records, weights)

    assert result_low["value"] < result_high["value"]


def test_orchestrator_result_contains_trigger_threshold_meta():
    """run_demo() 结果的 risk_weights 包含触发阈值元数据。"""
    from src.orchestrator import DecisionOrchestrator

    result = DecisionOrchestrator().run_demo()
    rw = result.risk_weights

    assert "_trigger_threshold_value" in rw
    assert "_trigger_threshold_source" in rw
    assert rw["_trigger_threshold_source"] in ("expert", "calibrated")
    assert 0 < rw["_trigger_threshold_value"] < 100
