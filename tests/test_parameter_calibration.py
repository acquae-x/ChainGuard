from src.parameter_calibration import (
    calibrate_inventory_risk_weights,
    calibrate_thresholds,
    evaluate_decision_outcomes,
    explain_simulation_limitations,
)


def test_calibrate_inventory_risk_weights_returns_default_weights():
    weights = calibrate_inventory_risk_weights(historical_data=[])

    assert weights
    assert weights["shortage_urgency"] == 0.35
    assert round(sum(weights.values()), 6) == 1.0


def test_calibrate_thresholds_returns_default_thresholds():
    thresholds = calibrate_thresholds(historical_data=[])

    assert thresholds["inventory_warning"]["yellow_support_hours"] == 48
    assert thresholds["inventory_warning"]["inventory_risk_trigger"] == 70
    assert thresholds["debate"]["score_gap_trigger"] == 15


def test_evaluate_decision_outcomes_returns_mock_result():
    result = evaluate_decision_outcomes(historical_decisions=[])

    assert result["status"] == "simulated"
    assert result["average_score"] > 0
    assert result["key_findings"]


def test_explain_simulation_limitations_returns_chinese_notice():
    notice = explain_simulation_limitations()

    assert "当前 MVP 使用模拟数据和专家经验参数" in notice
    assert "ERP/WMS/TMS" in notice
