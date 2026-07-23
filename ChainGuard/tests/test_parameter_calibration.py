from src.parameter_calibration import (
    calibrate_inventory_risk_weights,
    calibrate_thresholds,
    evaluate_decision_outcomes,
    explain_simulation_limitations,
)
from src.config_loader import load_risk_weights


WEIGHT_KEYS = [
    "shortage_urgency",
    "order_importance",
    "transit_delay",
    "external_event",
]
def test_calibrate_inventory_risk_weights_returns_default_weights():
    weights = calibrate_inventory_risk_weights(historical_data=[])

    assert weights
    assert weights["shortage_urgency"] == 0.35
    assert round(sum(weights[key] for key in WEIGHT_KEYS), 6) == 1.0


def test_calibrate_thresholds_returns_default_thresholds():
    thresholds = calibrate_thresholds(historical_data=[])

    assert thresholds["inventory_warning"]["yellow_support_hours"] == 48
    assert thresholds["inventory_warning"]["inventory_risk_trigger"] == 70
    assert thresholds["debate"]["score_gap_trigger"] == 15


def test_evaluate_decision_outcomes_reports_no_data_instead_of_inventing_numbers():
    """无样本时必须返回 None，不得编造 average_score 82 / success_rate 0.76。

    与 P0-2 同源：不可测量就说不可测量，捏造的"演示数字"会被下游当成真实历史表现。
    """
    result = evaluate_decision_outcomes(historical_decisions=[])

    assert result["status"] == "no_data"
    assert result["sample_size"] == 0
    assert result["average_score"] is None
    assert result["success_rate"] is None
    assert result["key_findings"]


def test_explain_simulation_limitations_returns_chinese_notice():
    notice = explain_simulation_limitations()

    assert "当前 MVP 使用模拟数据和专家经验参数" in notice
    assert "ERP/WMS/TMS" in notice


def _rec(outcome, coverage, delay, lost, downtime, rating=3):
    return {
        "outcome_status": outcome,
        "covered_demand_rate": coverage,
        "actual_delay_hours": delay,
        "predicted_delay_hours": delay * 0.8,
        "actual_cost": 100000.0,
        "predicted_cost": 110000.0,
        "production_downtime_hours": downtime,
        "lost_orders": lost,
        "human_rating": rating,
    }


def _mixed_records():
    return [
        _rec("success", 0.95, 4, 0, 0, 5),
        _rec("success", 0.85, 10, 0, 2, 4),
        _rec("partial_success", 0.55, 32, 1, 8, 3),
        _rec("failed", 0.25, 68, 4, 48, 2),
        _rec("failed", 0.10, 80, 6, 72, 1),
    ]


def test_calibrate_weights_returns_all_keys():
    weights = calibrate_inventory_risk_weights(_mixed_records())

    assert all(key in weights for key in WEIGHT_KEYS)
    assert all(isinstance(weights[key], float) for key in WEIGHT_KEYS)


def test_calibrate_weights_sum_to_one():
    weights = calibrate_inventory_risk_weights(_mixed_records())

    assert abs(sum(weights[key] for key in WEIGHT_KEYS) - 1.0) < 0.01


def test_calibrate_weights_empty_data():
    weights = calibrate_inventory_risk_weights([])

    assert weights["shortage_urgency"] == 0.35


def test_calibrate_thresholds_failure_cases():
    records = [
        _rec("failed", 0.4, delay, 1, 12)
        for delay in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    ]

    thresholds = calibrate_thresholds(records)

    assert thresholds["inventory_warning"]["yellow_support_hours"] > thresholds["inventory_warning"]["red_support_hours"] > 0


def test_evaluate_outcomes_sample_size():
    records = [
        *[_rec("success", 0.9, 10, 0, 0, 5) for _ in range(5)],
        *[_rec("failed", 0.2, 70, 4, 48, 1) for _ in range(5)],
    ]

    result = evaluate_decision_outcomes(records)

    assert result["status"] == "calibrated"
    assert result["sample_size"] == 10


def test_calibrate_weights_input_changes_output():
    all_success = [_rec("success", 0.8, 12, 0, 0) for _ in range(25)]
    mixed = [
        *[_rec("success", 0.9, 10, 0, 0) for _ in range(13)],
        *[_rec("failed", 0.1, 70, 4, 48) for _ in range(12)],
    ]
    same = calibrate_inventory_risk_weights(all_success)
    calibrated = calibrate_inventory_risk_weights(mixed)

    assert any(abs(calibrated[key] - same[key]) > 0.01 for key in WEIGHT_KEYS)


def test_calibration_includes_metadata():
    weights = calibrate_inventory_risk_weights(_mixed_records())

    assert isinstance(weights["_sample_size"], int)
    assert weights["_sample_size"] > 0
    assert weights["_method"] == "pearson_correlation"
    assert isinstance(weights["_calibration_note"], str)
    assert weights["_calibration_note"]


def test_calibration_metadata_on_insufficient_samples():
    weights = calibrate_inventory_risk_weights(_mixed_records()[:3])
    expert = load_risk_weights()["inventory_risk_weights"]

    assert weights["_sample_size"] == 3
    assert "样本量不足" in weights["_calibration_note"]
    for key, value in expert.items():
        assert weights[key] == value


def test_metadata_keys_do_not_break_weight_sum():
    weights = calibrate_inventory_risk_weights(_mixed_records())

    assert round(sum(weights[key] for key in WEIGHT_KEYS), 6) == 1.0
