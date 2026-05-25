def build_demo_state() -> dict:
    """Return the fixed supply-chain interruption scenario for the demo."""
    scenario = {
        "event": "台风导致宁波港停运",
        "supplier": "A供应商",
        "supplier_delay": "A供应商延误72小时",
        "delay_hours": 72,
        "inventory_hours": 36,
        "safety_stock_gap_pct": 42,
        "customer": "关键客户",
        "customer_delivery_due_hours": 48,
        "product": "核心零部件 P-100",
    }

    inventory_table = [
        {
            "物料": "核心零部件 P-100",
            "当前库存": "1,080 件",
            "日均消耗": "720 件",
            "可支撑时间": "36 小时",
            "安全库存缺口": "42%",
            "客户订单窗口": "48 小时",
        },
        {
            "物料": "替代件 P-100B",
            "当前库存": "260 件",
            "日均消耗": "160 件",
            "可支撑时间": "39 小时",
            "安全库存缺口": "28%",
            "客户订单窗口": "48 小时",
        },
    ]

    return {
        "scenario": scenario,
        "inventory_table": inventory_table,
        "expert_parameters": {
            "inventory_weight": 0.35,
            "delivery_weight": 0.25,
            "supplier_weight": 0.20,
            "port_disruption_weight": 0.20,
        },
    }


def compute_risk_summary(state: dict) -> dict:
    scenario = state["scenario"]
    inventory_gap = scenario["customer_delivery_due_hours"] - scenario["inventory_hours"]
    delay_gap = scenario["delay_hours"] - scenario["inventory_hours"]
    safety_gap = scenario["safety_stock_gap_pct"]

    score = min(
        100,
        45
        + max(inventory_gap, 0) * 1.4
        + max(delay_gap, 0) * 0.7
        + safety_gap * 0.6,
    )

    if score >= 85:
        risk_level = "极高"
        priority = "立即干预"
    elif score >= 70:
        risk_level = "高"
        priority = "高优先级"
    elif score >= 50:
        risk_level = "中"
        priority = "持续监控"
    else:
        risk_level = "低"
        priority = "正常"

    return {
        "score": round(score, 1),
        "risk_level": risk_level,
        "priority": priority,
        "summary": (
            "库存只能覆盖 36 小时，但关键客户交付窗口为 48 小时；"
            "供应商延误 72 小时且宁波港停运，存在明确断供与延期交付风险。"
        ),
    }
