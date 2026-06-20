from typing import Any

from src.agents import generate_all_proposals
from src.arbitrator import arbitrate
from src.audit import AuditLog, build_audit_entry
from src.config_loader import load_thresholds
from src.conflict_detector import detect_conflict
from src.constraint_solver import ConstraintSolver
from src.data_loader import load_demo_context
from src.debate import DebateEngine, generate_rebuttal
from src.domain_models import DecisionResult
from src.explainer import DecisionExplainer
from src.feedback import ExperienceFeedback
from src.game_model import PayoffModel
from src.history_pipeline import HistoryPipeline
from src.inventory_monitor import calculate_inventory_risk
from src.learning import generate_experience_card, save_experience_card
from src.scenario_loader import ScenarioLoader
from src.scoring import attach_total_scores
from src.weight_manager import WeightManager


class DecisionOrchestrator:
    """Run the deterministic ChainGuard MVP decision workflow."""

    @staticmethod
    def _find_proposal(proposals: list[dict[str, Any]], role: str) -> dict[str, Any]:
        for proposal in proposals:
            if role in str(proposal.get("agent_name", "")):
                return proposal
        raise ValueError(f"未找到 {role} Agent 方案。")

    def run_demo(self) -> DecisionResult:
        context: dict[str, Any] = {}
        try:
            thresholds = load_thresholds()
            context = load_demo_context()
            risk_weights = self._resolve_risk_weights()
            return self._run_context(context, risk_weights, thresholds)
        except Exception as error:
            self._log_error_audit(context, error)
            raise

    def run_scenario(
        self,
        event_id: str,
        loader: ScenarioLoader,
    ) -> DecisionResult:
        context: dict[str, Any] = {}
        try:
            thresholds = load_thresholds()
            context = loader.load_context(event_id)
            risk_weights = self._resolve_risk_weights()
            return self._run_context(context, risk_weights, thresholds)
        except Exception as error:
            self._log_error_audit(context, error)
            raise

    @staticmethod
    def _resolve_risk_weights(
        history_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        manager = WeightManager()
        if history_records is None:
            try:
                history_records = HistoryPipeline().load_outcomes()
            except Exception:
                history_records = []
        inventory_weights = manager.resolve_inventory_risk_weights(history_records)
        score_weights = manager.resolve_decision_score_weights(history_records)
        payoff_weights = manager.resolve_payoff_weights()
        trigger_meta = manager.resolve_trigger_threshold(
            history_records, inventory_weights.values
        )
        return {
            "inventory_risk_weights": inventory_weights.values,
            "decision_score_weights": score_weights.values,
            "payoff_weights": payoff_weights.values,
            "_inventory_weight_source": inventory_weights.source,
            "_inventory_weight_sample_size": inventory_weights.sample_size,
            "_inventory_weight_note": inventory_weights.note,
            "_score_weight_source": score_weights.source,
            "_score_weight_note": score_weights.note,
            "_payoff_weight_source": payoff_weights.source,
            "_trigger_threshold_value": trigger_meta["value"],
            "_trigger_threshold_source": trigger_meta["_source"],
            "_trigger_threshold_note": trigger_meta["_note"],
            "_trigger_threshold_sample_size": trigger_meta["_sample_size"],
        }

    @staticmethod
    def _log_error_audit(context: dict[str, Any], error: Exception) -> None:
        try:
            entry = build_audit_entry(
                {"context": context},
                status="error",
                error_message=f"{type(error).__name__}: {error}",
            )
            AuditLog().append(entry)
        except Exception:
            pass

    def _run_context(
        self,
        context: dict[str, Any],
        risk_weights: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> DecisionResult:
        calibrated_trigger = risk_weights.get("_trigger_threshold_value")
        if calibrated_trigger is not None:
            thresholds = {
                **thresholds,
                "inventory_warning": {
                    **thresholds["inventory_warning"],
                    "inventory_risk_trigger": calibrated_trigger,
                },
            }
        retrieval_result = ExperienceFeedback().retrieve(context)
        inventory_risk = calculate_inventory_risk(
            context["inventory"],
            risk_weights,
            thresholds,
        )
        proposals = attach_total_scores(
            generate_all_proposals(context),
            risk_weights["decision_score_weights"],
        )
        for proposal in proposals:
            proposal["experience_hints"] = retrieval_result.risk_hints
            proposal["experience_confidence"] = retrieval_result.confidence_adjustment

        conflict = detect_conflict(proposals, thresholds)
        rebuttal = generate_rebuttal(
            self._find_proposal(proposals, "物流"),
            self._find_proposal(proposals, "财务"),
            context,
        )
        arbitration = arbitrate(proposals, conflict, rebuttal, context)
        experience_card = generate_experience_card(
            context,
            proposals,
            arbitration,
            retrieval_result=retrieval_result,
        )
        try:
            save_experience_card(experience_card)
        except Exception:
            pass
        payoff_model = PayoffModel(payoff_weights=risk_weights.get("payoff_weights"))
        payoffs = {
            "procurement": payoff_model.evaluate_procurement(context),
            "logistics": payoff_model.evaluate_logistics(context),
            "finance": payoff_model.evaluate_finance(context),
        }
        constraint_analysis_obj = ConstraintSolver().solve(
            payoffs,
            context,
        )
        constraint_analysis = constraint_analysis_obj.to_dict()
        debate_result = DebateEngine().run(
            payoffs,
            constraint_analysis_obj,
        ).to_dict()
        try:
            explanation = DecisionExplainer().explain(
                {
                    "proposals": proposals,
                    "arbitration": arbitration,
                    "debate_result": debate_result,
                    "constraint_analysis": constraint_analysis,
                }
            ).to_dict()
        except Exception:
            explanation = DecisionExplainer._template_result(
                {
                    "proposals": proposals,
                    "arbitration": arbitration,
                    "debate_result": debate_result,
                    "constraint_analysis": constraint_analysis,
                }
            ).to_dict()
        audit_context = {
            "context": context,
            "inventory_risk": inventory_risk,
            "debate_result": debate_result,
            "constraint_analysis": constraint_analysis,
            "experience_confidence": retrieval_result.confidence_adjustment,
        }
        audit_entry_obj = build_audit_entry(audit_context)
        try:
            AuditLog().append(audit_entry_obj)
        except Exception:
            pass

        return DecisionResult(
            risk_weights=risk_weights,
            thresholds=thresholds,
            context=context,
            inventory_risk=inventory_risk,
            proposals=proposals,
            conflict=conflict,
            rebuttal=rebuttal,
            arbitration=arbitration,
            experience_card=experience_card,
            constraint_analysis=constraint_analysis,
            debate_result=debate_result,
            experience_references=retrieval_result.to_dict(),
            explanation=explanation,
            audit_entry=audit_entry_obj.to_dict(),
        )
