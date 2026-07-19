import copy
from dataclasses import replace
from typing import Any

from src.agents import generate_all_proposals
from src.arbitrator import arbitrate
from src.audit import AuditLog, build_audit_entry
from src.config_loader import load_thresholds
from src.conflict_detector import detect_conflict
from src.constraint_solver import ConstraintSolver
from src.data_source import DataSource, demo_source
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

    @staticmethod
    def _build_experience_feedback(ds: DataSource) -> Any:
        try:
            return ExperienceFeedback(cards_path=ds.experience_cards_path)
        except TypeError:
            return ExperienceFeedback()

    @staticmethod
    def _append_audit(entry: Any, ds: DataSource) -> None:
        try:
            audit_log = AuditLog(ds.audit_log_path)
        except TypeError:
            audit_log = AuditLog()
        audit_log.append(entry)

    def run_demo(self, *, data_source: DataSource | None = None) -> DecisionResult:
        ds = data_source or demo_source()
        context: dict[str, Any] = {}
        try:
            thresholds = load_thresholds()
            context = load_demo_context()
            risk_weights = self._resolve_risk_weights()
            return self._run_context(context, risk_weights, thresholds, data_source=ds)
        except Exception as error:
            self._log_error_audit(context, error, data_source=ds)
            raise

    def run_scenario(
        self,
        event_id: str,
        loader: ScenarioLoader,
        *,
        data_source: DataSource | None = None,
    ) -> DecisionResult:
        ds = data_source or demo_source()
        context: dict[str, Any] = {}
        try:
            thresholds = load_thresholds()
            context = loader.load_context(event_id)
            risk_weights = self._resolve_risk_weights()
            return self._run_context(context, risk_weights, thresholds, data_source=ds)
        except Exception as error:
            self._log_error_audit(context, error, data_source=ds)
            raise

    def run_tenant_scenario(
        self,
        context: dict[str, Any],
        *,
        risk_weights: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> DecisionResult:
        """Run a Web tenant context without consulting any demo/file-state data.

        The caller owns tenant-scoped database access and supplies a fully validated
        context plus resolved tenant configuration.  File experience retrieval,
        experience-card writes and JSONL audit writes are deliberately disabled for
        this path; the Web job persists its detail/audit in tenant-scoped DB tables.
        """
        result = self._run_context(
            copy.deepcopy(context),
            copy.deepcopy(risk_weights),
            copy.deepcopy(thresholds),
            data_source=None,
            allow_file_state=False,
        )
        return self._attach_tenant_economics(result)

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
    def _log_error_audit(
        context: dict[str, Any],
        error: Exception,
        *,
        data_source: DataSource | None = None,
    ) -> None:
        try:
            ds = data_source or demo_source()
            entry = build_audit_entry(
                {"context": context},
                status="error",
                error_message=f"{type(error).__name__}: {error}",
            )
            DecisionOrchestrator._append_audit(entry, ds)
        except Exception:
            pass

    def _run_context(
        self,
        context: dict[str, Any],
        risk_weights: dict[str, Any],
        thresholds: dict[str, Any],
        *,
        data_source: DataSource | None,
        allow_file_state: bool = True,
    ) -> DecisionResult:
        ds = data_source
        calibrated_trigger = risk_weights.get("_trigger_threshold_value")
        if calibrated_trigger is not None:
            thresholds = {
                **thresholds,
                "inventory_warning": {
                    **thresholds["inventory_warning"],
                    "inventory_risk_trigger": calibrated_trigger,
                },
            }
        if allow_file_state:
            assert ds is not None
            retrieval_result = self._build_experience_feedback(ds).retrieve(context)
        else:
            query = ExperienceFeedback._build_query(context)
            retrieval_result = ExperienceFeedback._empty_result(query)
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
        if allow_file_state:
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
        if allow_file_state:
            assert ds is not None
            try:
                self._append_audit(audit_entry_obj, ds)
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

    @staticmethod
    def _attach_tenant_economics(result: DecisionResult) -> DecisionResult:
        """Add explainable CNY/lead-time outputs from tenant entity values.

        Existing agents intentionally score normalized multipliers.  The Web adapter
        additionally materializes those recommendations into currency and days using
        supplier quotes, required quantity and transport choices from the same context.
        """
        context = result.context
        inventory = context.get("inventory") or {}
        derived = context.get("derived_metrics") or {}
        suppliers = list(context.get("suppliers") or [])
        transports = list(context.get("transport_options") or [])
        orders = list(context.get("orders") or [])
        quantity = max(
            float(derived.get("inventory_shortage_qty") or 0),
            float(inventory.get("critical_order_demand") or 0)
            - float(derived.get("available_inventory_qty") or inventory.get("current_stock") or 0),
            float(inventory.get("hourly_consumption") or 0) * 24.0,
            1.0,
        )
        quoted = [supplier for supplier in suppliers if supplier.get("supplier_price") is not None]
        fallback_supplier = min(
            quoted,
            key=lambda supplier: (
                float(supplier.get("supplier_price") or 0)
                * float(supplier.get("cost_multiplier") or 1),
                int(supplier.get("supplier_rank") or 2**31 - 1),
            ),
        ) if quoted else None
        total_penalty = sum(float(order.get("penalty_cost") or 0) for order in orders)
        enriched: list[dict[str, Any]] = []
        for original in result.proposals:
            proposal = copy.deepcopy(original)
            title = str(proposal.get("proposal_title") or "")
            agent = str(proposal.get("agent_name") or "")
            supplier = next(
                (
                    item for item in suppliers
                    if str(item.get("supplier_name") or "") in title
                    or str(item.get("supplier_id") or "") in title
                ),
                fallback_supplier,
            )
            if "采购" in agent and supplier is not None:
                unit_price = float(supplier["supplier_price"])
                multiplier = float(supplier.get("cost_multiplier") or 1)
                proposal["total_cost"] = round(quantity * unit_price * multiplier, 2)
                proposal["lead_time_impact"] = float(supplier.get("lead_time_hours") or 0) / 24.0
                proposal["economic_basis"] = {
                    "source": "tenant_supplier_quote",
                    "supplier_id": supplier.get("supplier_id"),
                    "quantity": quantity,
                    "unit_price_cny": unit_price,
                    "cost_multiplier": multiplier,
                }
            elif "物流" in agent:
                transport = next(
                    (
                        item for item in transports
                        if str(item.get("name") or "") in title
                        or str(item.get("mode") or "") in title
                    ),
                    None,
                )
                if transport is not None and supplier is not None:
                    base = quantity * float(supplier["supplier_price"])
                    multiplier = float(transport.get("cost_multiplier") or 1)
                    proposal["total_cost"] = round(base * multiplier, 2)
                    proposal["lead_time_impact"] = float(transport.get("estimated_hours") or 0) / 24.0
                    proposal["economic_basis"] = {
                        "source": "tenant_quote_and_transport",
                        "quantity": quantity,
                        "base_procurement_cny": round(base, 2),
                        "transport_mode": transport.get("mode"),
                        "cost_multiplier": multiplier,
                    }
            elif "财务" in agent:
                coverage = 0.0
                options = list(proposal.get("strategy_options") or [])
                selected = next((item for item in options if item.get("selected")), None)
                if selected:
                    label = str(selected.get("label") or "")
                    coverage = 1.0 if "全部" in label else 0.7 if "关键" in label or "分级" in label else 0.5
                proposal["total_cost"] = round(total_penalty * max(1.0 - coverage, 0.0), 2)
                proposal["economic_basis"] = {
                    "source": "tenant_order_penalty_exposure",
                    "total_penalty_cny": total_penalty,
                    "protected_ratio": coverage,
                }
            enriched.append(proposal)
        experience_card = copy.deepcopy(result.experience_card)
        experience_card["parameter_note"] = (
            "基于当前租户结构化实体数据生成；C1 不写入经验库，待后续经验闭环审核。"
        )
        return replace(result, proposals=enriched, experience_card=experience_card)
