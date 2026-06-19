from dataclasses import dataclass
from typing import Any


_COST_LEVEL_MULTIPLIERS = {
    "低": 1.0,
    "中低": 1.3,
    "中": 1.6,
    "高": 3.0,
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _utility(value: float) -> float:
    return round(_clamp(value), 2)


def _number(record: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = record.get(key, default)
    if value is None:
        return default
    return float(value)


def _order_hours(order: dict[str, Any]) -> float:
    return _number(order, "delivery_hours", _number(order, "due_hours"))


def _minimum_a_delivery_hours(context: dict[str, Any]) -> float:
    deadlines = [
        _order_hours(order)
        for order in context.get("orders", [])
        if order.get("priority") == "A" and _order_hours(order) >= 0
    ]
    if deadlines:
        return max(min(deadlines), 1.0)

    inventory = context.get("inventory", {})
    hourly_consumption = max(_number(inventory, "hourly_consumption"), 0.01)
    support_hours = _number(inventory, "current_stock") / hourly_consumption
    return max(support_hours, 1.0)


def _demand_basis(context: dict[str, Any]) -> float:
    inventory = context.get("inventory", {})
    critical_demand = max(_number(inventory, "critical_order_demand"), 0.0)
    safety_gap = max(
        _number(inventory, "safety_stock") - _number(inventory, "current_stock"),
        0.0,
    )
    daily_consumption = max(_number(inventory, "hourly_consumption") * 24.0, 0.0)
    return max(critical_demand, safety_gap, daily_consumption, 1.0)


def _transport_cost_multiplier(option: dict[str, Any]) -> float:
    explicit_multiplier = option.get("cost_multiplier")
    if explicit_multiplier is not None:
        return max(float(explicit_multiplier), 0.01)
    return _COST_LEVEL_MULTIPLIERS.get(str(option.get("cost_level", "")), 2.0)


def _weighted_supplier_metric(
    suppliers: list[dict[str, Any]],
    field: str,
    default: float,
) -> float:
    if not suppliers:
        return default
    weights = [max(_number(supplier, "available_qty"), 0.0) for supplier in suppliers]
    total_weight = sum(weights)
    if total_weight <= 0:
        return sum(_number(supplier, field, default) for supplier in suppliers) / len(
            suppliers
        )
    return sum(
        _number(supplier, field, default) * weight
        for supplier, weight in zip(suppliers, weights)
    ) / total_weight


@dataclass
class StrategyOption:
    """One discrete strategy a single agent can choose."""

    label: str
    parameters: dict[str, Any]
    own_utility: float
    system_utility: float


@dataclass
class AgentPayoff:
    """Computed payoffs for all options of one agent."""

    agent_name: str
    options: list[StrategyOption]
    selected_index: int
    selected_label: str

    @property
    def selected(self) -> StrategyOption:
        return self.options[self.selected_index]


def _build_payoff(agent_name: str, options: list[StrategyOption]) -> AgentPayoff:
    selected_index = max(
        range(len(options)),
        key=lambda index: options[index].own_utility,
    )
    return AgentPayoff(
        agent_name=agent_name,
        options=options,
        selected_index=selected_index,
        selected_label=options[selected_index].label,
    )


class PayoffModel:
    """Compute strategy options and payoffs for all three agents."""

    def evaluate_procurement(self, context: dict[str, Any]) -> AgentPayoff:
        suppliers = context.get("suppliers", [])
        ready_suppliers = [
            supplier
            for supplier in suppliers
            if _number(supplier, "available_qty") > 0
            and _number(supplier, "delay_hours") == 0
        ]
        primary_supplier = (
            min(
                ready_suppliers,
                key=lambda supplier: _number(
                    supplier,
                    "lead_time_hours",
                    float("inf"),
                ),
            )
            if ready_suppliers
            else None
        )
        strategy_suppliers = [
            [primary_supplier] if primary_supplier is not None else [],
            ready_suppliers,
            suppliers,
        ]
        labels = [
            "主供应商紧急补货",
            "多源联合补货",
            "应急最大化供给",
        ]
        demand_basis = _demand_basis(context)
        options: list[StrategyOption] = []

        for label, selected_suppliers in zip(labels, strategy_suppliers):
            supply_qty = sum(
                max(_number(supplier, "available_qty"), 0.0)
                for supplier in selected_suppliers
            )
            lead_time = _weighted_supplier_metric(
                selected_suppliers,
                "lead_time_hours",
                0.0,
            )
            cost_multiplier = max(
                _weighted_supplier_metric(
                    selected_suppliers,
                    "cost_multiplier",
                    1.0,
                ),
                0.01,
            )
            coverage_rate = min(supply_qty / demand_basis, 1.0)
            speed_score = _clamp(100.0 - lead_time / 48.0 * 50.0)
            own_utility = (
                coverage_rate * 60.0
                + speed_score * 0.40
                if selected_suppliers
                else 0.0
            )
            system_utility = (
                coverage_rate * 50.0
                + (100.0 / cost_multiplier) * 0.50
                if selected_suppliers
                else 0.0
            )
            representative_supplier = (
                min(
                    selected_suppliers,
                    key=lambda supplier: _number(
                        supplier,
                        "lead_time_hours",
                        float("inf"),
                    ),
                )
                if selected_suppliers
                else None
            )
            options.append(
                StrategyOption(
                    label=label,
                    parameters={
                        "suppliers": list(selected_suppliers),
                        "supplier_ids": [
                            supplier.get("supplier_id")
                            for supplier in selected_suppliers
                        ],
                        "supply_qty": supply_qty,
                        "lead_time_hours": lead_time,
                        "cost_multiplier": cost_multiplier,
                        "coverage_rate": coverage_rate,
                        "representative_supplier": representative_supplier,
                    },
                    own_utility=_utility(own_utility),
                    system_utility=_utility(system_utility),
                )
            )

        return _build_payoff("采购 Agent", options)

    def evaluate_logistics(self, context: dict[str, Any]) -> AgentPayoff:
        transport_options = context.get("transport_options", [])
        available_modes = sorted(
            (
                option
                for option in transport_options
                if option.get("available")
                and option.get("estimated_hours") is not None
            ),
            key=lambda option: _number(
                option,
                "estimated_hours",
                float("inf"),
            ),
        )
        fastest = available_modes[0] if available_modes else None
        balanced_modes = available_modes[:2]
        cheapest = (
            min(available_modes, key=_transport_cost_multiplier)
            if available_modes
            else None
        )
        deadline = _minimum_a_delivery_hours(context)
        availability_ratio = (
            len(available_modes) / max(len(transport_options), 1) * 100.0
        )

        raw_options = [
            ("最快运输优先", [fastest] if fastest is not None else []),
            ("均衡运输组合", balanced_modes),
            ("最低成本路线", [cheapest] if cheapest is not None else []),
        ]
        options: list[StrategyOption] = []

        for label, selected_modes in raw_options:
            if selected_modes:
                hours = sum(
                    _number(option, "estimated_hours")
                    for option in selected_modes
                ) / len(selected_modes)
                cost_multiplier = sum(
                    _transport_cost_multiplier(option)
                    for option in selected_modes
                ) / len(selected_modes)
                speed_score = _clamp(
                    100.0 - hours / max(deadline, 1.0) * 50.0
                )
                own_utility = (
                    speed_score * 0.70
                    + availability_ratio * 0.30
                )
                system_utility = (
                    speed_score * 0.40
                    + _clamp(100.0 / max(cost_multiplier, 0.01)) * 0.60
                )
                representative_mode = min(
                    selected_modes,
                    key=lambda option: _number(
                        option,
                        "estimated_hours",
                        float("inf"),
                    ),
                )
            else:
                hours = 0.0
                cost_multiplier = 0.0
                own_utility = 0.0
                system_utility = 0.0
                representative_mode = None

            options.append(
                StrategyOption(
                    label=label,
                    parameters={
                        "modes": list(selected_modes),
                        "mode_codes": [
                            option.get("mode") for option in selected_modes
                        ],
                        "estimated_hours": hours,
                        "cost_multiplier": cost_multiplier,
                        "availability_ratio": availability_ratio,
                        "representative_mode": representative_mode,
                    },
                    own_utility=_utility(own_utility),
                    system_utility=_utility(system_utility),
                )
            )

        return _build_payoff("物流 Agent", options)

    def evaluate_finance(self, context: dict[str, Any]) -> AgentPayoff:
        orders = context.get("orders", [])
        labels = [
            "A类优先分级保障",
            "全量高成本保障",
            "盈亏平衡截止",
        ]
        if not orders:
            return _build_payoff(
                "财务 Agent",
                [
                    StrategyOption(
                        label=label,
                        parameters={
                            "coverage_ratio": 0.0,
                            "cost_factor": 0.0,
                            "covered_order_ids": [],
                        },
                        own_utility=0.0,
                        system_utility=0.0,
                    )
                    for label in labels
                ],
            )

        a_orders = [order for order in orders if order.get("priority") == "A"]
        a_penalty = sum(
            max(_number(order, "penalty_cost"), 0.0)
            for order in a_orders
        )
        total_gross_profit = sum(
            max(_number(order, "gross_profit"), 0.0)
            for order in orders
        )
        base_cost_estimate = max(total_gross_profit * 0.10, 1.0)
        profitable_orders = [
            order
            for order in orders
            if _number(order, "gross_profit")
            > max(_number(order, "penalty_cost") * 0.75, 1.0)
        ]
        profitable_coverage = len(profitable_orders) / max(len(orders), 1)
        a_order_ratio = len(a_orders) / max(len(orders), 1)
        raw_options = [
            (labels[0], 0.80, 1.30, a_orders),
            (labels[1], 1.00, 2.50, orders),
            (labels[2], profitable_coverage, 1.00, profitable_orders),
        ]
        options: list[StrategyOption] = []

        for label, coverage_ratio, cost_factor, covered_orders in raw_options:
            penalty_saved = a_penalty * coverage_ratio
            extra_cost = cost_factor * base_cost_estimate
            net_benefit = max(penalty_saved - extra_cost, 0.0)
            normalized = (
                net_benefit / max(total_gross_profit, 1.0) * 100.0
            )
            own_utility = _clamp(normalized * 3.0)
            service_level = a_order_ratio * coverage_ratio * 100.0
            system_utility = service_level * 0.50 + own_utility * 0.50
            options.append(
                StrategyOption(
                    label=label,
                    parameters={
                        "coverage_ratio": coverage_ratio,
                        "cost_factor": cost_factor,
                        "covered_order_ids": [
                            order.get("order_id") for order in covered_orders
                        ],
                        "penalty_saved": penalty_saved,
                        "extra_cost": extra_cost,
                        "net_benefit": net_benefit,
                    },
                    own_utility=_utility(own_utility),
                    system_utility=_utility(system_utility),
                )
            )

        return _build_payoff("财务 Agent", options)
