def run_mock_agents(state: dict, risk: dict) -> list[dict]:
    scenario = state["scenario"]

    return [
        {
            "name": "库存 Agent",
            "judgement": (
                f"{scenario['product']} 当前库存仅能支撑 {scenario['inventory_hours']} 小时，"
                f"短于客户交付窗口 {scenario['customer_delivery_due_hours']} 小时。"
            ),
            "recommended_action": "立即冻结非关键订单库存，并优先保障关键客户订单",
            "confidence": 92,
            "priority": "P0",
        },
        {
            "name": "采购 Agent",
            "judgement": (
                f"{scenario['supplier']} 延误 {scenario['delay_hours']} 小时，单一供应风险已触发。"
            ),
            "recommended_action": "启动备用供应商询价和小批量应急采购",
            "confidence": 84,
            "priority": "P1",
        },
        {
            "name": "物流 Agent",
            "judgement": "宁波港停运导致原计划海运链路失效，常规补货无法覆盖缺口。",
            "recommended_action": "评估上海港转运和空运补货的组合方案",
            "confidence": 88,
            "priority": "P0",
        },
        {
            "name": "客户交付 Agent",
            "judgement": "关键客户订单 48 小时后交付，库存覆盖不足会直接影响履约。",
            "recommended_action": "提前同步客户风险，并准备分批交付承诺",
            "confidence": 79,
            "priority": "P1",
        },
    ]


def build_debate(agent_results: list[dict], risk: dict) -> dict:
    conflicts = [
        {
            "争议点": "成本 vs 履约",
            "主张 A": "物流 Agent 建议高成本空运补货",
            "主张 B": "采购 Agent 倾向备用供应商小批量采购",
            "仲裁判断": "履约风险优先于短期成本",
        },
        {
            "争议点": "库存分配",
            "主张 A": "库存 Agent 建议冻结非关键订单",
            "主张 B": "客户交付 Agent 建议保留部分缓冲用于分批交付",
            "仲裁判断": "关键客户订单优先，保留最小服务缓冲",
        },
    ]

    return {
        "conflicts": conflicts,
        "verdict": (
            f"综合风险等级为{risk['risk_level']}，应采用“保交付优先”的应急策略："
            "先锁定关键客户库存，再通过备用供应商和替代物流组合补齐缺口，"
            "同时向客户透明同步风险与分批交付计划。"
        ),
        "action_plan": [
            "冻结非关键订单对核心零部件 P-100 的占用，保障关键客户订单。",
            "启动备用供应商小批量应急采购，确认 24 小时内可交付数量。",
            "物流侧并行评估上海港转运与空运补货，优先覆盖 12 小时库存缺口。",
            "销售侧向关键客户同步风险，准备分批交付和补偿方案。",
            "记录本次事件参数与决策结果，作为后续阈值校准样本。",
        ],
    }
