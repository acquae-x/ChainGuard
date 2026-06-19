from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.game_model import AgentPayoff, StrategyOption


AGENT_ORDER: tuple[str, ...] = ("procurement", "logistics", "finance")


@dataclass(frozen=True)
class AgentCoordination:
    """Per-agent coordination metrics."""

    agent: str
    selfish_strategy: str
    selfish_own_utility: float
    selfish_system_utility: float
    optimal_strategy: str
    optimal_own_utility: float
    optimal_system_utility: float
    own_utility_delta: float
    loss_ratio: float
    within_threshold: bool
    accepted: bool


@dataclass(frozen=True)
class GameAnalysisResult:
    """Full game-theoretic analysis of a single decision round."""

    agents: tuple[str, ...]
    strategy_space_size: int
    individual_choices: dict[str, str]
    individual_system_utility: float
    optimal_choices: dict[str, str]
    optimal_system_utility: float
    coordination_gain: float
    coordination_gain_pct: float
    agent_coordination: tuple[AgentCoordination, ...]
    all_within_threshold: bool
    mechanism_type: str
    is_nash_equilibrium: bool


class GameAnalyzer:
    def __init__(
        self,
        *,
        acceptance_threshold: float = 0.20,
    ) -> None:
        self.acceptance_threshold = acceptance_threshold

    def analyze(
        self,
        payoffs: dict[str, AgentPayoff],
        constraint_analysis: dict[str, Any],
        debate_result: dict[str, Any],
    ) -> GameAnalysisResult:
        """Compute game-theoretic metrics for one decision round."""

        individual_choices = {
            key: payoffs[key].selected_label for key in AGENT_ORDER
        }
        individual_system_utility = float(
            constraint_analysis["individual_system_utility"]
        )
        optimal_choices = dict(constraint_analysis["optimal_combo"])
        optimal_system_utility = float(
            constraint_analysis["optimal_system_utility"]
        )

        coordination_gain = round(
            optimal_system_utility - individual_system_utility,
            2,
        )
        coordination_gain_pct = (
            round(coordination_gain / individual_system_utility * 100, 1)
            if individual_system_utility > 0
            else 0.0
        )
        accepted_agents = set(debate_result.get("strategies_updated", []))

        agent_coordination = tuple(
            self._agent_coordination(
                key,
                payoffs[key],
                optimal_choices[key],
                accepted_agents,
            )
            for key in AGENT_ORDER
        )

        return GameAnalysisResult(
            agents=AGENT_ORDER,
            strategy_space_size=self._strategy_space_size(payoffs),
            individual_choices=individual_choices,
            individual_system_utility=individual_system_utility,
            optimal_choices=optimal_choices,
            optimal_system_utility=optimal_system_utility,
            coordination_gain=coordination_gain,
            coordination_gain_pct=coordination_gain_pct,
            agent_coordination=agent_coordination,
            all_within_threshold=all(
                item.within_threshold for item in agent_coordination
            ),
            mechanism_type="cooperative_mechanism_design",
            is_nash_equilibrium=False,
        )

    def _agent_coordination(
        self,
        agent: str,
        payoff: AgentPayoff,
        optimal_label: str,
        accepted_agents: set[str],
    ) -> AgentCoordination:
        selfish_opt = payoff.options[payoff.selected_index]
        optimal_opt = self._find_option(payoff.options, optimal_label)
        if optimal_opt is None:
            optimal_opt = selfish_opt

        own_utility_delta = round(
            optimal_opt.own_utility - selfish_opt.own_utility,
            2,
        )
        loss_ratio = round(
            max(-own_utility_delta / max(selfish_opt.own_utility, 0.01), 0.0),
            4,
        )

        return AgentCoordination(
            agent=agent,
            selfish_strategy=payoff.selected_label,
            selfish_own_utility=selfish_opt.own_utility,
            selfish_system_utility=selfish_opt.system_utility,
            optimal_strategy=optimal_label,
            optimal_own_utility=optimal_opt.own_utility,
            optimal_system_utility=optimal_opt.system_utility,
            own_utility_delta=own_utility_delta,
            loss_ratio=loss_ratio,
            within_threshold=loss_ratio <= self.acceptance_threshold,
            accepted=agent in accepted_agents,
        )

    @staticmethod
    def _find_option(
        options: list[StrategyOption],
        label: str,
    ) -> StrategyOption | None:
        return next((option for option in options if option.label == label), None)

    @staticmethod
    def _strategy_space_size(payoffs: dict[str, AgentPayoff]) -> int:
        size = 1
        for key in AGENT_ORDER:
            size *= len(payoffs[key].options)
        return size
