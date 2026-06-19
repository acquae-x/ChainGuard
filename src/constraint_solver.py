from dataclasses import asdict, dataclass, field
from itertools import product
from typing import Any

from src.game_model import AgentPayoff, StrategyOption


DEFAULT_MIN_SUPPLY_COVERAGE = 0.30
DEFAULT_MAX_DELIVERY_HOURS = 72.0
DEFAULT_MAX_COMBINED_COST_MULT = 5.0


@dataclass(frozen=True)
class ConstraintAnalysis:
    feasible_count: int
    feasible: bool
    optimal_combo: dict[str, str]
    optimal_system_utility: float
    individual_system_utility: float
    recommended_changes: list[str]
    constraint_violations: list[str]
    all_combos: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _AttrDict(asdict(self))


class _AttrDict(dict):
    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error


class ConstraintSolver:
    """Enumerate strategy combinations and select the best feasible one."""

    def solve(
        self,
        payoffs: dict[str, AgentPayoff],
        context: dict[str, Any],
        constraints: dict[str, float] | None = None,
    ) -> ConstraintAnalysis:
        constraint_values = self._resolve_constraints(context, constraints)
        procurement = payoffs["procurement"]
        logistics = payoffs["logistics"]
        finance = payoffs["finance"]

        individual_options = {
            "procurement": procurement.selected,
            "logistics": logistics.selected,
            "finance": finance.selected,
        }
        individual_system_utility = self._combined_system_utility(
            individual_options,
        )

        feasible_combos: list[tuple[dict[str, StrategyOption], float]] = []
        infeasible_combos: list[
            tuple[dict[str, StrategyOption], float, list[str]]
        ] = []

        for p_option, l_option, f_option in product(
            procurement.options,
            logistics.options,
            finance.options,
        ):
            combo = {
                "procurement": p_option,
                "logistics": l_option,
                "finance": f_option,
            }
            combined_utility = self._combined_system_utility(combo)
            violations = self._check_constraints(combo, constraint_values)
            if violations:
                infeasible_combos.append((combo, combined_utility, violations))
            else:
                feasible_combos.append((combo, combined_utility))

        if feasible_combos:
            optimal_combo, optimal_utility = max(
                feasible_combos,
                key=lambda item: item[1],
            )
            feasible = True
            violations: list[str] = []
        else:
            optimal_combo, optimal_utility, violations = max(
                infeasible_combos,
                key=lambda item: item[1],
            )
            feasible = False

        optimal_labels = self._combo_labels(optimal_combo)
        all_combos: list[dict] = []
        for combo, utility in feasible_combos:
            labels = self._combo_labels(combo)
            all_combos.append(
                {
                    "cost_multiplier": self._combined_cost(combo),
                    "system_utility": round(utility, 2),
                    "feasible": True,
                    "is_optimal": labels == optimal_labels,
                    "label": "/".join(value[:5] for value in labels.values()),
                }
            )
        for combo, utility, _combo_violations in infeasible_combos:
            labels = self._combo_labels(combo)
            all_combos.append(
                {
                    "cost_multiplier": self._combined_cost(combo),
                    "system_utility": round(utility, 2),
                    "feasible": False,
                    "is_optimal": False,
                    "label": "/".join(value[:5] for value in labels.values()),
                }
            )

        return ConstraintAnalysis(
            feasible_count=len(feasible_combos),
            feasible=feasible,
            optimal_combo=self._combo_labels(optimal_combo),
            optimal_system_utility=round(optimal_utility, 2),
            individual_system_utility=round(individual_system_utility, 2),
            recommended_changes=self._recommended_changes(
                individual_options,
                optimal_combo,
            ),
            constraint_violations=violations if not feasible else [],
            all_combos=all_combos,
        )

    @staticmethod
    def _resolve_constraints(
        context: dict[str, Any],
        constraints: dict[str, float] | None,
    ) -> dict[str, float]:
        provided = constraints or {}
        return {
            "MIN_SUPPLY_COVERAGE": float(
                provided.get(
                    "MIN_SUPPLY_COVERAGE",
                    DEFAULT_MIN_SUPPLY_COVERAGE,
                )
            ),
            "MAX_DELIVERY_HOURS": float(
                provided.get(
                    "MAX_DELIVERY_HOURS",
                    context.get("min_deadline_hours", DEFAULT_MAX_DELIVERY_HOURS),
                )
            ),
            "MAX_COMBINED_COST_MULT": float(
                provided.get(
                    "MAX_COMBINED_COST_MULT",
                    DEFAULT_MAX_COMBINED_COST_MULT,
                )
            ),
        }

    @staticmethod
    def _combined_system_utility(
        combo: dict[str, StrategyOption],
    ) -> float:
        return sum(option.system_utility for option in combo.values())

    @staticmethod
    def _combined_cost(combo: dict[str, StrategyOption]) -> float:
        def _get(option: StrategyOption, *keys: str) -> float:
            for key in keys:
                if key in option.parameters:
                    value = option.parameters[key]
                    return float(value) if value is not None else 1.0
            return 1.0

        return round(
            _get(combo["procurement"], "avg_cost_mult", "cost_multiplier")
            + _get(combo["logistics"], "cost_mult", "cost_multiplier"),
            3,
        )

    @staticmethod
    def _combo_labels(combo: dict[str, StrategyOption]) -> dict[str, str]:
        return {
            "procurement": combo["procurement"].label,
            "logistics": combo["logistics"].label,
            "finance": combo["finance"].label,
        }

    def _recommended_changes(
        self,
        individual_options: dict[str, StrategyOption],
        optimal_combo: dict[str, StrategyOption],
    ) -> list[str]:
        labels = {
            "procurement": "采购",
            "logistics": "物流",
            "finance": "财务",
        }
        changes: list[str] = []
        for key in ("procurement", "logistics", "finance"):
            current = individual_options[key]
            optimal = optimal_combo[key]
            if current.label == optimal.label:
                continue
            utility_delta = optimal.system_utility - current.system_utility
            changes.append(
                f"{labels[key]}：建议从「{current.label}」切换到"
                f"「{optimal.label}」（系统效用{utility_delta:+.2f}）"
            )
        return changes

    def _check_constraints(
        self,
        combo: dict[str, StrategyOption],
        constraints: dict[str, float],
    ) -> list[str]:
        procurement = combo["procurement"]
        logistics = combo["logistics"]

        coverage_rate = self._parameter(
            procurement,
            "coverage_rate",
            default=1.0,
        )
        estimated_hours = self._parameter(
            logistics,
            "estimated_hours",
            default=0.0,
        )
        procurement_cost = self._first_parameter(
            procurement,
            ("avg_cost_mult", "cost_multiplier"),
            default=1.0,
        )
        logistics_cost = self._first_parameter(
            logistics,
            ("cost_mult", "cost_multiplier"),
            default=1.0,
        )
        combined_cost = procurement_cost + logistics_cost

        violations: list[str] = []
        min_supply = constraints["MIN_SUPPLY_COVERAGE"]
        max_delivery = constraints["MAX_DELIVERY_HOURS"]
        max_cost = constraints["MAX_COMBINED_COST_MULT"]

        if coverage_rate < min_supply:
            violations.append(
                f"供给覆盖率 {coverage_rate:.2f} < {min_supply:.2f}"
            )
        if estimated_hours > max_delivery:
            violations.append(
                f"交期 {estimated_hours:.2f}h > {max_delivery:.2f}h"
            )
        if combined_cost > max_cost:
            violations.append(
                f"采购+物流成本倍数 {combined_cost:.2f} > {max_cost:.2f}"
            )
        return violations

    @staticmethod
    def _parameter(
        option: StrategyOption,
        key: str,
        default: float,
    ) -> float:
        value = option.parameters.get(key, default)
        if value is None:
            return default
        return float(value)

    def _first_parameter(
        self,
        option: StrategyOption,
        keys: tuple[str, ...],
        default: float,
    ) -> float:
        for key in keys:
            if key in option.parameters:
                return self._parameter(option, key, default)
        return default
