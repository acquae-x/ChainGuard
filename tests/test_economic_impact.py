def test_no_orders_returns_zero_impact():
    from src.economic_impact import calculate_economic_impact

    result = calculate_economic_impact(
        {"orders": [], "inventory": {"current_stock": 1000}}
    )

    assert result.net_benefit == 0
    assert result.manual_penalty == 0
    assert result.manual_covered_orders == []


def test_manual_skips_order_exceeding_stock():
    from src.economic_impact import calculate_economic_impact

    context = {
        "orders": [
            {
                "order_id": "A1",
                "priority": "A",
                "demand_qty": 5000,
                "penalty_cost": 180000,
                "gross_profit": 420000,
                "due_hours": 48,
            },
            {
                "order_id": "B1",
                "priority": "B",
                "demand_qty": 2000,
                "penalty_cost": 60000,
                "gross_profit": 160000,
                "due_hours": 72,
            },
        ],
        "inventory": {"current_stock": 2000},
        "suppliers": [],
    }

    result = calculate_economic_impact(context)

    assert "B1" in result.manual_covered_orders
    assert "A1" not in result.manual_covered_orders
    assert result.manual_penalty == 180000


def test_system_uses_feasible_supplier_to_fill_gap():
    from src.economic_impact import calculate_economic_impact

    context = {
        "orders": [
            {
                "order_id": "A1",
                "priority": "A",
                "demand_qty": 5000,
                "penalty_cost": 180000,
                "gross_profit": 420000,
                "due_hours": 48,
            },
        ],
        "inventory": {"current_stock": 3600},
        "suppliers": [
            {
                "supplier_id": "S1",
                "available_qty": 5000,
                "lead_time_hours": 36,
                "delay_hours": 0,
                "reliability_score": 85,
            },
        ],
    }

    result = calculate_economic_impact(context)

    assert "A1" not in result.manual_covered_orders
    assert "A1" in result.system_covered_orders
    assert result.penalty_savings == 180000
    assert result.net_benefit > 0


def test_infeasible_supplier_not_used():
    from src.economic_impact import calculate_economic_impact

    context = {
        "orders": [
            {
                "order_id": "A1",
                "priority": "A",
                "demand_qty": 5000,
                "penalty_cost": 180000,
                "gross_profit": 420000,
                "due_hours": 48,
            },
        ],
        "inventory": {"current_stock": 3600},
        "suppliers": [
            {
                "supplier_id": "S_late",
                "available_qty": 9999,
                "lead_time_hours": 72,
                "delay_hours": 0,
                "reliability_score": 99,
            },
        ],
    }

    result = calculate_economic_impact(context)

    assert "A1" not in result.system_covered_orders
    assert result.penalty_savings == 0


def test_system_outperforms_manual_and_annual_is_12x():
    from src.economic_impact import ANNUAL_INCIDENT_COUNT, calculate_economic_impact

    context = {
        "orders": [
            {
                "order_id": "A1",
                "priority": "A",
                "demand_qty": 5000,
                "penalty_cost": 200000,
                "gross_profit": 500000,
                "due_hours": 48,
            },
        ],
        "inventory": {"current_stock": 3600},
        "suppliers": [
            {
                "supplier_id": "S1",
                "available_qty": 2000,
                "lead_time_hours": 36,
                "delay_hours": 0,
                "reliability_score": 85,
            },
        ],
    }

    result = calculate_economic_impact(context)

    assert result.net_benefit > 0
    assert len(result.system_covered_orders) > len(result.manual_covered_orders)
    assert result.annual_benefit_estimate == result.net_benefit * ANNUAL_INCIDENT_COUNT
