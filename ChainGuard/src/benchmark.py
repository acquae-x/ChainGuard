from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import src.orchestrator as orchestrator_module
from src.audit import approval_required
from src.orchestrator import DecisionOrchestrator
from src.sensitivity import run_sensitivity



class _MemoryAuditLog:
    def __init__(self, entries: list[Any]) -> None:
        self._entries = entries

    def append(self, entry: Any) -> None:
        self._entries.append(entry)

    def load(self) -> list[Any]:
        return list(self._entries)


class _EmptyRetrievalResult:
    query = ""
    references: list[Any] = []
    reference_count = 0
    confidence_adjustment = 0.0
    risk_hints: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "references": [],
            "reference_count": self.reference_count,
            "confidence_adjustment": self.confidence_adjustment,
            "risk_hints": [],
        }


class _EmptyExperienceFeedback:
    def retrieve(self, context: dict[str, Any]) -> _EmptyRetrievalResult:
        return _EmptyRetrievalResult()


@contextmanager
def _isolated_orchestrator(
    *,
    no_experience_retrieval: bool = False,
    remove_logistics_agent: bool = False,
) -> Iterator[list[Any]]:
    audit_entries: list[Any] = []
    original_audit_log = orchestrator_module.AuditLog
    original_save_experience_card = orchestrator_module.save_experience_card
    original_experience_feedback = orchestrator_module.ExperienceFeedback
    original_generate_all_proposals = orchestrator_module.generate_all_proposals

    def audit_log_factory() -> _MemoryAuditLog:
        return _MemoryAuditLog(audit_entries)

    def save_experience_card_noop(card: dict[str, Any]) -> dict[str, Any]:
        return {
            "path": "memory://experience_cards",
            "saved_count": 1,
            "case_id": card.get("case_id", ""),
        }

    def generate_without_logistics(context: dict[str, Any]) -> list[dict[str, Any]]:
        proposals = original_generate_all_proposals(context)
        return [
            proposal
            for index, proposal in enumerate(proposals)
            if index != 1
        ]

    orchestrator_module.AuditLog = audit_log_factory
    orchestrator_module.save_experience_card = save_experience_card_noop
    if no_experience_retrieval:
        orchestrator_module.ExperienceFeedback = _EmptyExperienceFeedback
    if remove_logistics_agent:
        orchestrator_module.generate_all_proposals = generate_without_logistics

    try:
        yield audit_entries
    finally:
        orchestrator_module.AuditLog = original_audit_log
        orchestrator_module.save_experience_card = original_save_experience_card
        orchestrator_module.ExperienceFeedback = original_experience_feedback
        orchestrator_module.generate_all_proposals = original_generate_all_proposals


def _run_demo_isolated(*, no_experience_retrieval: bool = False) -> Any:
    with _isolated_orchestrator(no_experience_retrieval=no_experience_retrieval):
        return DecisionOrchestrator().run_demo()


def run_baseline() -> dict[str, Any]:
    """Run the fixed demo and return benchmark metrics."""
    result = _run_demo_isolated()
    audit_entry = result.audit_entry
    return {
        "inventory_risk_index": result.inventory_risk["inventory_risk_index"],
        "feasible_count": result.constraint_analysis["feasible_count"],
        "debate_converged": result.debate_result["converged"],
        "human_approval": audit_entry["human_approval_required"],
        "decision_status": audit_entry["decision_status"],
        "top_proposal": result.arbitration["final_decision_title"],
    }


def run_ablation() -> list[dict[str, Any]]:
    """Return four deterministic ablation rows for presentation."""
    baseline_result = _run_demo_isolated()
    no_retrieval_result = _run_demo_isolated(no_experience_retrieval=True)
    low_stock = run_sensitivity("current_stock", [720])[0]
    low_stock_approval = approval_required(
        {"inventory_risk": {"inventory_risk_index": low_stock["inventory_risk_index"]}}
    )
    no_converge_approval = approval_required(
        {"debate_result": {"converged": False}}
    )

    return [
        {
            "scenario": "baseline_all_modules",
            "inventory_risk_index": baseline_result.inventory_risk[
                "inventory_risk_index"
            ],
            "human_approval": baseline_result.audit_entry[
                "human_approval_required"
            ],
            "decision_status": baseline_result.audit_entry["decision_status"],
            "note": "All modules enabled; audit approval is not required.",
            "experience_reference_count": baseline_result.experience_references.get(
                "reference_count",
                0,
            ),
            "experience_confidence": baseline_result.experience_references.get(
                "confidence_adjustment",
                0.0,
            ),
        },
        {
            "scenario": "without_experience_retrieval",
            "inventory_risk_index": no_retrieval_result.inventory_risk[
                "inventory_risk_index"
            ],
            "human_approval": no_retrieval_result.audit_entry[
                "human_approval_required"
            ],
            "decision_status": no_retrieval_result.audit_entry["decision_status"],
            "note": (
                "Historical retrieval is disabled; reference_count="
                f"{no_retrieval_result.experience_references['reference_count']}."
            ),
            "experience_reference_count": (
                no_retrieval_result.experience_references.get("reference_count", 0)
            ),
            "experience_confidence": no_retrieval_result.experience_references.get(
                "confidence_adjustment",
                0.0,
            ),
        },
        {
            "scenario": "low_stock_current_stock_720",
            "inventory_risk_index": low_stock["inventory_risk_index"],
            "human_approval": low_stock_approval,
            "decision_status": "ok",
            "note": "Low stock pushes risk above 80 and requires approval.",
            "experience_reference_count": None,
            "experience_confidence": None,
        },
        {
            "scenario": "debate_not_converged",
            "inventory_risk_index": 0.0,
            "human_approval": no_converge_approval,
            "decision_status": "ok",
            "note": "A non-converged debate requires manual approval.",
            "experience_reference_count": None,
            "experience_confidence": None,
        },
    ]


def run_failure_case() -> dict[str, Any]:
    """Trigger the orchestrator error path and capture the audit entry."""
    triggered_error = False
    error_type = ""
    error_message = ""

    with _isolated_orchestrator(remove_logistics_agent=True) as audit_entries:
        try:
            DecisionOrchestrator().run_demo()
        except Exception as error:
            triggered_error = True
            error_type = type(error).__name__
            error_message = str(error)

        entries = list(audit_entries)

    latest = entries[-1].to_dict() if entries else {}
    return {
        "triggered_error": triggered_error,
        "error_type": error_type,
        "audit_status": latest.get("decision_status", "missing"),
        "error_in_message": error_type in latest.get("error_message", ""),
        "caught_message": error_message,
    }
