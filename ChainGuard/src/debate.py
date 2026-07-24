from typing import Any

from src.challenger import challenge_recommendation
from src.constraint_solver import ConstraintAnalysis
from src.evidence import DebateResult, DebateRound, Evidence
from src.game_model import AgentPayoff, StrategyOption


DEFAULT_ACCEPTANCE_THRESHOLD = 0.20
MAX_ROUNDS = 3
AGENT_ORDER = ("procurement", "logistics", "finance")


def _proposal_text(proposal: dict[str, Any]) -> str:
    parts = [
        str(proposal.get("agent_name", "")),
        str(proposal.get("role", "")),
        str(proposal.get("proposal_title", "")),
        str(proposal.get("proposal", "")),
    ]
    for key in ("reasoning", "risks", "actions"):
        value = proposal.get(key, [])
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return " ".join(parts)


def _is_agent(proposal: dict[str, Any], keyword: str) -> bool:
    return keyword in str(proposal.get("agent_name", ""))


def _lacks_backup_supplier(proposal: dict[str, Any], proposal_text: str) -> bool:
    """Check whether the proposal lacks backup supplier arrangement."""
    strategy_options = proposal.get("strategy_options")
    if strategy_options is not None:
        selected = next(
            (opt for opt in strategy_options if opt.get("selected")),
            None,
        )
        if selected is not None:
            supplier_ids = selected.get("parameters", {}).get("supplier_ids", [])
            return len(supplier_ids) <= 1

    scores = proposal.get("scores", {})
    if "risk_reduction" in scores:
        return float(scores["risk_reduction"]) < 50

    return "备用供应商" not in proposal_text


def generate_rebuttal(
    lowest_proposal: dict[str, Any],
    highest_proposal: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Generate a debate rebuttal while preserving structured branch rules.

    By default, the lower-scored proposal rebuts the higher-scored proposal.
    For the fixed demo scenario, a stronger special rule is used: when the
    logistics proposal advocates full air freight and the finance proposal is
    present, Finance rebuts Logistics to make the cost-vs-timeliness conflict
    clear for presentation.
    """
    from src.text_generator import TextGenerator

    second_text = _proposal_text(highest_proposal)
    orders = context.get("orders", [])
    events = context.get("events") or [{}]
    event_title = str(events[0].get("title") or "当前中断事件")
    material_name = str(context.get("inventory", {}).get("material_name") or "关键物料")
    critical_orders = [order for order in orders if order.get("priority") == "A"]
    context_data = {
        "event_title": event_title,
        "material_name": material_name,
        "critical_orders_count": len(critical_orders),
    }
    text_generator = TextGenerator()

    def build_rebuttal(
        *,
        branch: str,
        debater_proposal: dict[str, Any],
        target_proposal: dict[str, Any],
    ) -> dict[str, Any]:
        debater_name = str(debater_proposal.get("agent_name", ""))
        target_name = str(target_proposal.get("agent_name", ""))
        text_content = text_generator.generate_rebuttal_content(
            branch=branch,
            debater=debater_name,
            target=target_name,
            proposal_data=target_proposal,
            context_data=context_data,
        )
        return {
            "debater": debater_name,
            "target": target_name,
            **text_content,
            "challenger": challenge_recommendation(target_proposal, context),
        }

    lowest_scores = lowest_proposal.get("scores", {})
    highest_scores = highest_proposal.get("scores", {})
    lowest_has_high_transport_cost = float(lowest_scores.get("cost", 100)) < 40
    highest_has_high_transport_cost = float(highest_scores.get("cost", 100)) < 40

    if (
        _is_agent(lowest_proposal, "物流")
        and lowest_has_high_transport_cost
        and _is_agent(highest_proposal, "财务")
    ):
        return build_rebuttal(
            branch="high_cost",
            debater_proposal=highest_proposal,
            target_proposal=lowest_proposal,
        )

    if (
        _is_agent(highest_proposal, "物流")
        and highest_has_high_transport_cost
        and _is_agent(lowest_proposal, "财务")
    ):
        return build_rebuttal(
            branch="high_cost",
            debater_proposal=lowest_proposal,
            target_proposal=highest_proposal,
        )

    if _is_agent(lowest_proposal, "采购") and _lacks_backup_supplier(highest_proposal, second_text):
        return build_rebuttal(
            branch="missing_backup",
            debater_proposal=lowest_proposal,
            target_proposal=highest_proposal,
        )

    target_scores = highest_proposal.get("scores", {})
    target_is_conservative = float(target_scores.get("timeliness", 100)) < 75
    if _is_agent(lowest_proposal, "物流") and target_is_conservative:
        return build_rebuttal(
            branch="conservative",
            debater_proposal=lowest_proposal,
            target_proposal=highest_proposal,
        )

    return build_rebuttal(
        branch="fallback",
        debater_proposal=lowest_proposal,
        target_proposal=highest_proposal,
    )


class DebateEngine:
    """Evidence-driven multi-round debate that updates agent strategies."""

    def run(
        self,
        payoffs: dict[str, AgentPayoff],
        constraint_analysis: ConstraintAnalysis,
        *,
        acceptance_threshold: float = DEFAULT_ACCEPTANCE_THRESHOLD,
        max_rounds: int = MAX_ROUNDS,
    ) -> DebateResult:
        current_selections = {
            key: payoffs[key].selected
            for key in AGENT_ORDER
        }
        rounds: list[DebateRound] = []
        strategies_updated: list[str] = []
        truncated = False

        for agent_key in AGENT_ORDER:
            if len(rounds) >= max_rounds:
                truncated = True
                break

            optimal_label = constraint_analysis.optimal_combo[agent_key]
            current_option = current_selections[agent_key]
            if current_option.label == optimal_label:
                continue

            recommended_option = self._find_option(
                payoffs[agent_key].options,
                optimal_label,
            )
            if recommended_option is None:
                continue

            system_delta = round(
                recommended_option.system_utility - current_option.system_utility,
                2,
            )
            if system_delta <= 0:
                continue

            evidence = Evidence(
                agent=agent_key,
                metric="system_utility",
                current_strategy=current_option.label,
                recommended_strategy=recommended_option.label,
                system_utility_current=current_option.system_utility,
                system_utility_recommended=recommended_option.system_utility,
                system_utility_delta=system_delta,
            )
            own_delta = round(
                recommended_option.own_utility - current_option.own_utility,
                2,
            )
            loss_ratio = (
                -own_delta / max(current_option.own_utility, 0.01)
                if own_delta < 0
                else 0.0
            )

            if loss_ratio <= acceptance_threshold:
                action = "accepted"
                current_selections[agent_key] = recommended_option
                strategies_updated.append(agent_key)
                own_after = recommended_option.own_utility
            else:
                action = "countered"
                own_after = current_option.own_utility

            rounds.append(
                DebateRound(
                    round_number=len(rounds) + 1,
                    target_agent=agent_key,
                    evidence=evidence,
                    action=action,
                    own_utility_before=current_option.own_utility,
                    own_utility_after=own_after,
                    own_utility_delta=round(
                        own_after - current_option.own_utility,
                        2,
                    ),
                )
            )

        final_strategies = {
            key: option.label
            for key, option in current_selections.items()
        }
        system_utility_after = round(
            sum(option.system_utility for option in current_selections.values()),
            2,
        )

        return DebateResult(
            rounds=rounds,
            final_strategies=final_strategies,
            strategies_updated=strategies_updated,
            converged=not truncated,
            total_rounds=len(rounds),
            system_utility_before=constraint_analysis.individual_system_utility,
            system_utility_after=system_utility_after,
        )

    @staticmethod
    def _find_option(
        options: list[StrategyOption],
        label: str,
    ) -> StrategyOption | None:
        for option in options:
            if option.label == label:
                return option
        return None
