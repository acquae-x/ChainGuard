from src.config_loader import load_risk_weights, load_thresholds, validate_weights_sum


def test_load_risk_weights_reads_yaml_config():
    risk_weights = load_risk_weights()

    assert "inventory_risk_weights" in risk_weights
    assert "decision_score_weights" in risk_weights
    assert risk_weights["inventory_risk_weights"]["shortage_urgency"] == 0.35
    assert risk_weights["decision_score_weights"]["timeliness"] == 0.25
    assert validate_weights_sum(risk_weights["inventory_risk_weights"]) is True
    assert validate_weights_sum(risk_weights["decision_score_weights"]) is True


def test_load_thresholds_reads_yaml_config():
    thresholds = load_thresholds()

    assert "inventory_warning" in thresholds
    assert "debate" in thresholds
    assert "learning" in thresholds
    assert thresholds["inventory_warning"]["yellow_support_hours"] == 48
    assert thresholds["inventory_warning"]["red_support_hours"] == 24
    assert thresholds["inventory_warning"]["inventory_risk_trigger"] == 70
    assert thresholds["debate"]["score_gap_trigger"] == 15
    assert thresholds["learning"]["low_score_threshold"] == 70
