from src.weight_manager import WeightManager


def test_no_data_returns_expert_source():
    weights = WeightManager().resolve_inventory_risk_weights(None)

    assert weights.source == "expert"
    assert weights.sample_size == 0


def test_sufficient_data_returns_calibrated_source():
    records = [
        {
            "outcome_status": "success",
            "covered_demand_rate": 0.9,
            "actual_delay_hours": 5,
            "lost_orders": 0,
            "production_downtime_hours": 0,
        },
        {
            "outcome_status": "failed",
            "covered_demand_rate": 0.2,
            "actual_delay_hours": 60,
            "lost_orders": 5,
            "production_downtime_hours": 24,
        },
        {
            "outcome_status": "partial_success",
            "covered_demand_rate": 0.6,
            "actual_delay_hours": 30,
            "lost_orders": 2,
            "production_downtime_hours": 8,
        },
        {
            "outcome_status": "success",
            "covered_demand_rate": 0.95,
            "actual_delay_hours": 3,
            "lost_orders": 0,
            "production_downtime_hours": 0,
        },
        {
            "outcome_status": "failed",
            "covered_demand_rate": 0.1,
            "actual_delay_hours": 72,
            "lost_orders": 8,
            "production_downtime_hours": 48,
        },
        {
            "outcome_status": "success",
            "covered_demand_rate": 0.85,
            "actual_delay_hours": 10,
            "lost_orders": 0,
            "production_downtime_hours": 2,
        },
    ]

    weights = WeightManager().resolve_inventory_risk_weights(records)

    assert weights.source == "calibrated"
    assert weights.sample_size == 6


def test_calibrated_weights_change_inventory_risk_output():
    from src.inventory_monitor import calculate_inventory_risk

    inventory = {
        "current_stock": 100,
        "hourly_consumption": 5,
        "safety_stock": 200,
        "planned_arrival_hours": 24,
        "estimated_arrival_hours": 48,
        "critical_order_demand": 150,
        "external_risk_score": 30,
    }
    thresholds = {
        "inventory_warning": {
            "yellow_support_hours": 48,
            "red_support_hours": 24,
            "safety_stock_gap_rate": 0.20,
            "transit_delay_hours": 24,
            "critical_order_coverage_rate": 0.80,
            "inventory_risk_trigger": 70,
        }
    }
    weights_a = {
        "shortage_urgency": 0.10,
        "order_importance": 0.10,
        "transit_delay": 0.10,
        "external_event": 0.70,
    }
    weights_b = {
        "shortage_urgency": 0.70,
        "order_importance": 0.10,
        "transit_delay": 0.10,
        "external_event": 0.10,
    }

    risk_a = calculate_inventory_risk(
        inventory,
        {"inventory_risk_weights": weights_a},
        thresholds,
    )
    risk_b = calculate_inventory_risk(
        inventory,
        {"inventory_risk_weights": weights_b},
        thresholds,
    )

    assert risk_a["inventory_risk_index"] != risk_b["inventory_risk_index"]


def test_score_weights_change_total_score_output():
    from src.scoring import calculate_total_score

    scores = {
        "timeliness": 80,
        "cost": 60,
        "risk_reduction": 90,
        "feasibility": 70,
        "service_level": 85,
    }
    weights_a = {
        "timeliness": 0.50,
        "cost": 0.10,
        "risk_reduction": 0.15,
        "feasibility": 0.15,
        "service_level": 0.10,
    }
    weights_b = {
        "timeliness": 0.10,
        "cost": 0.10,
        "risk_reduction": 0.15,
        "feasibility": 0.15,
        "service_level": 0.50,
    }

    assert calculate_total_score(scores, weights_a) != calculate_total_score(
        scores,
        weights_b,
    )


def test_payoff_weights_change_procurement_utility():
    from src.game_model import PayoffModel

    context = {
        "inventory": {
            "current_stock": 500,
            "hourly_consumption": 10,
            "safety_stock": 300,
            "critical_order_demand": 400,
            "planned_arrival_hours": 24,
            "estimated_arrival_hours": 36,
            "external_risk_score": 20,
        },
        "suppliers": [
            {
                "supplier_id": "S1",
                "available_qty": 300,
                "lead_time_hours": 12,
                "delay_hours": 0,
                "cost_multiplier": 1.5,
            }
        ],
        "orders": [],
        "transport_options": [],
    }
    base = {
        "procurement_own_coverage": 0.60,
        "procurement_own_speed": 0.40,
        "procurement_sys_coverage": 0.50,
        "procurement_sys_cost_efficiency": 0.50,
        "logistics_own_speed": 0.70,
        "logistics_own_availability": 0.30,
        "logistics_sys_speed": 0.40,
        "logistics_sys_cost_efficiency": 0.60,
        "finance_own_scale": 3.0,
        "finance_sys_service": 0.50,
        "finance_sys_own": 0.50,
    }
    weights_a = {
        **base,
        "procurement_own_coverage": 0.90,
        "procurement_own_speed": 0.10,
    }
    weights_b = {
        **base,
        "procurement_own_coverage": 0.10,
        "procurement_own_speed": 0.90,
    }

    utility_a = (
        PayoffModel(payoff_weights=weights_a)
        .evaluate_procurement(context)
        .selected
        .own_utility
    )
    utility_b = (
        PayoffModel(payoff_weights=weights_b)
        .evaluate_procurement(context)
        .selected
        .own_utility
    )

    assert utility_a != utility_b


def test_weight_set_has_explainability_fields():
    manager = WeightManager()

    for weights in [
        manager.resolve_inventory_risk_weights(None),
        manager.resolve_decision_score_weights(None),
        manager.resolve_payoff_weights(),
    ]:
        assert weights.source in ("expert", "calibrated")
        assert isinstance(weights.sample_size, int) and weights.sample_size >= 0
        assert weights.method != ""
        assert weights.note != ""
        assert all(not key.startswith("_") for key in weights.values)


def test_orchestrator_result_contains_weight_meta():
    from src.orchestrator import DecisionOrchestrator

    result = DecisionOrchestrator().run_demo()
    risk_weights = result.risk_weights

    assert "_inventory_weight_source" in risk_weights
    assert risk_weights["_inventory_weight_source"] == "calibrated"
    assert risk_weights["_inventory_weight_sample_size"] >= WeightManager.MIN_SAMPLES
    assert "inventory_risk_weights" in risk_weights
    assert "decision_score_weights" in risk_weights
    assert "payoff_weights" in risk_weights
