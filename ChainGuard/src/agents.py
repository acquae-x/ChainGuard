from typing import Any

from src.game_model import AgentPayoff, PayoffModel


Proposal = dict[str, Any]

_COST_LEVEL_MULTIPLIERS = {
    "低": 1.0,
    "中低": 1.3,
    "中": 1.6,
    "高": 3.0,
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _score(value: float) -> float:
    return round(_clamp(float(value)), 2)


def _number(record: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = record.get(key, default)
    if value is None:
        return default
    return float(value)


def _order_hours(order: dict[str, Any]) -> float:
    return _number(order, "delivery_hours", _number(order, "due_hours"))


def _minimum_a_delivery_hours(orders: list[dict[str, Any]]) -> float | None:
    delivery_hours = [
        _order_hours(order)
        for order in orders
        if order.get("priority") == "A" and _order_hours(order) >= 0
    ]
    return min(delivery_hours) if delivery_hours else None


def _transport_cost_multiplier(option: dict[str, Any]) -> float:
    explicit_multiplier = option.get("cost_multiplier")
    if explicit_multiplier is not None:
        return max(float(explicit_multiplier), 0.01)
    return _COST_LEVEL_MULTIPLIERS.get(str(option.get("cost_level", "")), 2.0)


def _service_level_score(action_hours: float, deadline_hours: float | None) -> float:
    if deadline_hours is None:
        return 50.0
    if deadline_hours <= 0:
        return 100.0 if action_hours <= 0 else 0.0
    if action_hours <= deadline_hours:
        return 100.0
    return _clamp(100.0 - ((action_hours - deadline_hours) / deadline_hours * 100.0))


def _strategy_options(payoff: AgentPayoff) -> list[dict[str, Any]]:
    return [
        {
            "label": option.label,
            "own_utility": option.own_utility,
            "system_utility": option.system_utility,
            "selected": index == payoff.selected_index,
        }
        for index, option in enumerate(payoff.options)
    ]


class ProcurementAgent:
    agent_name = "采购 Agent"
    role = "供应商替代、采购周期、供货稳定性"

    def generate_proposal(self, context: dict[str, Any]) -> Proposal:
        payoff = PayoffModel().evaluate_procurement(context)
        inventory = context["inventory"]
        suppliers = context.get("suppliers", [])
        orders = context.get("orders", [])
        material_name = str(inventory.get("material_name", "受影响物料"))

        if not suppliers:
            return {
                "agent_name": self.agent_name,
                "role": self.role,
                "proposal_title": "暂无合格供应商，启动人工寻源",
                "proposal": (
                    f"{material_name} 当前无合格供应商，无法形成自动补货承诺，"
                    "应立即启动人工寻源并保留库存分配控制。"
                ),
                "reasoning": [
                    "合格供应商数量为 0，当前可确认供给量为 0。",
                    "在新供应来源通过资质、价格和交期确认前，不应生成不可执行的采购承诺。",
                ],
                "risks": [
                    "人工寻源周期可能超过关键订单交付窗口。",
                    "未经审核的新供应来源可能带来质量和履约风险。",
                ],
                "actions": [
                    "立即发起跨区域供应商寻源。",
                    "冻结非关键订单的可用库存分配。",
                    "由采购负责人确认临时供应商准入和报价。",
                ],
                "scores": {
                    "timeliness": 0.0,
                    "cost": 0.0,
                    "risk_reduction": 0.0,
                    "feasibility": 0.0,
                    "service_level": 0.0,
                },
                "strategy_options": _strategy_options(payoff),
            }

        ready_suppliers = [
            supplier
            for supplier in suppliers
            if _number(supplier, "available_qty") > 0
            and _number(supplier, "delay_hours") == 0
        ]
        selected = payoff.selected
        selected_suppliers = selected.parameters["suppliers"]
        primary = (
            selected.parameters["representative_supplier"]
            or (
                ready_suppliers[0]
                if ready_suppliers
                else max(
                    suppliers,
                    key=lambda item: _number(item, "available_qty"),
                )
            )
        )
        backup_suppliers = [
            supplier
            for supplier in selected_suppliers
            if supplier is not primary and _number(supplier, "available_qty") > 0
        ]

        total_available_qty = sum(
            max(_number(supplier, "available_qty"), 0.0)
            for supplier in suppliers
        )
        critical_demand = max(_number(inventory, "critical_order_demand"), 0.0)
        safety_gap = max(
            _number(inventory, "safety_stock") - _number(inventory, "current_stock"),
            0.0,
        )
        daily_consumption = max(_number(inventory, "hourly_consumption") * 24.0, 0.0)
        demand_basis = max(critical_demand, safety_gap, daily_consumption, 1.0)
        supply_capacity_score = (
            total_available_qty / (total_available_qty + demand_basis) * 100.0
        )
        ready_ratio = len(ready_suppliers) / max(len(suppliers), 1) * 100.0
        primary_coverage_score = _clamp(
            _number(primary, "available_qty") / demand_basis * 100.0
        )

        lead_time = max(_number(primary, "lead_time_hours"), 0.0)
        cost_multiplier = max(_number(primary, "cost_multiplier", 1.0), 0.01)
        reliability = _number(primary, "reliability_score")
        deadline = _minimum_a_delivery_hours(orders)
        timing_reference = deadline or max(
            _number(inventory, "current_stock")
            / max(_number(inventory, "hourly_consumption"), 0.01),
            1.0,
        )
        primary_name = str(
            primary.get("supplier_name")
            or primary.get("supplier_id")
            or "优选供应商"
        )
        backup_names = [
            str(
                supplier.get("supplier_name")
                or supplier.get("supplier_id")
                or "候选供应商"
            )
            for supplier in backup_suppliers
        ]

        return {
            "agent_name": self.agent_name,
            "role": self.role,
            "proposal_title": f"{selected.label}：{primary_name}",
            "proposal": (
                f"针对 {material_name} 的供应缺口，执行“{selected.label}”，"
                f"计划调动 {len(selected_suppliers)} 家合格供应商，优先覆盖关键订单。"
            ),
            "reasoning": [
                f"{primary_name} 当前可供 {int(_number(primary, 'available_qty'))} 件，"
                f"交期约 {lead_time:g} 小时，成本倍数为 {cost_multiplier:g}。",
                f"选中策略预计供给 {int(selected.parameters['supply_qty'])} 件，"
                f"自身效用 {selected.own_utility:.2f}，"
                f"系统效用 {selected.system_utility:.2f}。",
                (
                    f"该策略另含 {len(backup_suppliers)} 家可供货来源："
                    f"{'、'.join(backup_names)}。"
                    if backup_names
                    else f"当前关键订单需求为 {int(critical_demand)} 件，"
                    "需重点确认单一来源履约。"
                ),
            ],
            "risks": [
                "应急采购成本可能高于常规采购。",
                "供应商可供量和交期仍需人工确认后才能形成采购承诺。",
                "单一来源占比过高时仍存在供应连续性风险。",
            ],
            "actions": [
                f"2小时内确认{primary_name}的可供量和交期。",
                f"锁定{material_name}的应急采购批次。",
                "同步联系其他合格供应商，准备分批采购或替代来源。",
            ],
            "scores": {
                "timeliness": _score(
                    100.0 - (lead_time / max(timing_reference, 1.0) * 50.0)
                ),
                "cost": _score(100.0 / cost_multiplier),
                "risk_reduction": _score(reliability),
                "feasibility": _score(
                    supply_capacity_score * 0.70
                    + ready_ratio * 0.16
                    + primary_coverage_score * 0.14
                ),
                "service_level": _score(
                    _service_level_score(lead_time, deadline)
                ),
            },
            "strategy_options": _strategy_options(payoff),
        }


class LogisticsAgent:
    agent_name = "物流 Agent"
    role = "运输时效、路线风险、交付保障"

    def generate_proposal(self, context: dict[str, Any]) -> Proposal:
        payoff = PayoffModel().evaluate_logistics(context)
        inventory = context["inventory"]
        orders = context.get("orders", [])
        transport_options = context.get("transport_options", [])
        available_modes = [
            option for option in transport_options if option.get("available")
        ]
        material_name = str(inventory.get("material_name", "受影响物料"))
        event = (context.get("events") or [{}])[0]
        event_title = str(event.get("title") or event.get("event_type") or "当前中断事件")

        if not available_modes:
            return {
                "agent_name": self.agent_name,
                "role": self.role,
                "proposal_title": "当前无可用运输方式",
                "proposal": (
                    f"{material_name} 当前无可用运输方式，不能形成自动发运计划，"
                    "应保留库存并启动人工路线协调。"
                ),
                "reasoning": [
                    f"{event_title}影响下，可用运输方式数量为 0。",
                    "在承运能力恢复前，任何运输时效承诺都不可执行。",
                ],
                "risks": [
                    "关键订单可能超过承诺交付时间。",
                    "临时路线可能产生额外成本和合规风险。",
                ],
                "actions": [
                    "立即联系承运商确认临时路线。",
                    "按订单优先级预留库存。",
                    "向客户同步运输中断和预计恢复时间。",
                ],
                "scores": {
                    "timeliness": 0.0,
                    "cost": 0.0,
                    "risk_reduction": 0.0,
                    "feasibility": 0.0,
                    "service_level": 0.0,
                },
                "strategy_options": _strategy_options(payoff),
            }

        selected = payoff.selected
        best_mode = selected.parameters["representative_mode"]
        best_hours = max(float(selected.parameters["estimated_hours"]), 0.0)
        mode_name = str(best_mode.get("name") or best_mode.get("mode") or "最快运输方式")
        mode_code = str(best_mode.get("mode", ""))
        transport_action = (
            "全量空运"
            if selected.label == "最快运输优先" and mode_code == "air"
            else selected.label
        )
        cost_multiplier = max(
            float(selected.parameters["cost_multiplier"]),
            0.01,
        )
        deadline = _minimum_a_delivery_hours(orders)
        timing_reference = deadline or max(
            _number(inventory, "current_stock")
            / max(_number(inventory, "hourly_consumption"), 0.01),
            1.0,
        )

        return {
            "agent_name": self.agent_name,
            "role": self.role,
            "proposal_title": f"{selected.label}：{mode_name}",
            "proposal": (
                f"对受影响的 {material_name} 订单执行{transport_action}，"
                "在当前可用路线中平衡交付时效和运输成本。"
            ),
            "reasoning": [
                f"{event_title}正在影响原有供应链路，需要启用可用替代路线。",
                f"选中策略预计 {best_hours:g} 小时到达，自身效用"
                f" {selected.own_utility:.2f}，系统效用"
                f" {selected.system_utility:.2f}。",
                (
                    f"A类订单最近交付窗口为 {deadline:g} 小时。"
                    if deadline is not None
                    else "当前没有A类订单交付窗口，运输资源可按整体交期排序。"
                ),
            ],
            "risks": [
                f"{mode_name}的成本倍数约为 {cost_multiplier:g}，需核验订单毛利。",
                "承运能力需要及时确认，否则预计时效可能变化。",
                "只依赖最快路线可能放大单一路线中断风险。",
            ],
            "actions": [
                f"立即锁定{mode_name}运力和提货窗口。",
                "将受影响订单按优先级和交期排序。",
                "保留其他可用运输方式作为分流和回退方案。",
            ],
            "scores": {
                "timeliness": _score(
                    100.0 - (best_hours / max(timing_reference, 1.0) * 50.0)
                ),
                "cost": _score(100.0 / cost_multiplier),
                "risk_reduction": _score(
                    len(available_modes) / max(len(transport_options), 1) * 100.0
                ),
                "feasibility": _score(
                    len(available_modes)
                    / (len(available_modes) + 1.0)
                    * 100.0
                ),
                "service_level": _score(
                    _service_level_score(best_hours, deadline)
                ),
            },
            "strategy_options": _strategy_options(payoff),
        }


class FinanceAgent:
    agent_name = "财务 Agent"
    role = "应急成本、订单毛利、违约损失"

    def generate_proposal(self, context: dict[str, Any]) -> Proposal:
        payoff = PayoffModel().evaluate_finance(context)
        orders = context.get("orders", [])
        inventory = context.get("inventory", {})
        material_name = str(inventory.get("material_name", "受影响物料"))
        if not orders:
            return {
                "agent_name": self.agent_name,
                "role": self.role,
                "proposal_title": "当前无订单，不启动额外财务保障",
                "proposal": (
                    f"{material_name} 当前没有待处理订单，暂不投入高成本应急资源，"
                    "保留预算并等待新的订单或风险信息。"
                ),
                "reasoning": [
                    "当前订单数量为 0，无法计算违约罚金和订单毛利暴露。",
                    "三个财务策略均缺少可执行订单，因此自身效用均为 0。",
                ],
                "risks": [
                    "若订单数据尚未同步完成，可能低估真实履约风险。",
                    "新订单进入后需要重新计算财务策略。",
                ],
                "actions": [
                    "确认订单数据同步状态。",
                    "保留应急预算，不生成额外成本承诺。",
                ],
                "scores": {
                    "timeliness": 0.0,
                    "cost": 0.0,
                    "risk_reduction": 0.0,
                    "feasibility": 0.0,
                    "service_level": 0.0,
                },
                "strategy_options": _strategy_options(payoff),
            }

        high_priority_orders = [
            order for order in orders if order.get("priority") == "A"
        ]
        lower_priority_orders = [
            order for order in orders if order.get("priority") in {"B", "C"}
        ]
        total_penalty = sum(max(_number(order, "penalty_cost"), 0.0) for order in orders)
        total_gross_profit = sum(
            max(_number(order, "gross_profit"), 0.0) for order in orders
        )
        a_penalty = sum(
            max(_number(order, "penalty_cost"), 0.0)
            for order in high_priority_orders
        )
        a_penalty_ratio = a_penalty / max(total_penalty, 1.0)
        lower_priority_ratio = len(lower_priority_orders) / max(len(orders), 1)
        a_order_ratio = len(high_priority_orders) / max(len(orders), 1)
        profit_exposure = a_penalty / max(total_gross_profit, 1.0)
        selected = payoff.selected
        selected_coverage_ratio = float(selected.parameters["coverage_ratio"])

        return {
            "agent_name": self.agent_name,
            "role": self.role,
            "proposal_title": f"{selected.label}：{material_name}",
            "proposal": (
                f"针对 {material_name} 执行“{selected.label}”，不默认对所有订单"
                "使用最高成本方案，而是依据违约损失和订单毛利决定保障范围。"
            ),
            "reasoning": [
                f"A类关键订单数量为 {len(high_priority_orders)}，"
                f"对应违约罚金 {a_penalty:g}，占全部罚金 {a_penalty_ratio:.1%}。",
                f"选中策略覆盖比例为 {selected_coverage_ratio:.1%}，"
                f"自身效用 {selected.own_utility:.2f}，"
                f"系统效用 {selected.system_utility:.2f}。",
                f"当前订单总毛利为 {total_gross_profit:g}，全部违约罚金为"
                f" {total_penalty:g}，B/C类订单占比 {lower_priority_ratio:.1%}。",
            ],
            "risks": [
                "若过度压缩应急运输成本，高罚金订单可能出现违约风险。",
                "若全部使用最高成本方案，部分低毛利订单可能利润转负。",
                "分级保障需要销售侧及时与客户沟通。",
            ],
            "actions": [
                "计算各订单毛利、罚金和应急成本承受上限。",
                "优先为A类和高罚金订单配置高时效资源。",
                "对其余订单采用较低成本运输、分批交付或延期沟通。",
            ],
            "scores": {
                "timeliness": _score(a_penalty_ratio * 100.0),
                "cost": _score(lower_priority_ratio * 100.0),
                "risk_reduction": _score(profit_exposure * 300.0),
                "feasibility": _score(
                    len(high_priority_orders)
                    / (len(high_priority_orders) + 0.25)
                    * 100.0
                    if high_priority_orders
                    else 0.0
                ),
                "service_level": _score(
                    a_order_ratio * selected_coverage_ratio * 100.0
                ),
            },
            "strategy_options": _strategy_options(payoff),
        }


def generate_all_proposals(context: dict[str, Any]) -> list[Proposal]:
    agents = [
        ProcurementAgent(),
        LogisticsAgent(),
        FinanceAgent(),
    ]
    return [agent.generate_proposal(context) for agent in agents]
