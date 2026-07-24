"""Deterministic critic for recommendations that should not be auto-approved."""

from __future__ import annotations

from typing import Any


def _text(value: dict[str, Any]) -> str:
    pieces = []
    for key in ("proposal", "proposal_title", "selected_strategy", "final_strategy"):
        pieces.append(str(value.get(key) or ""))
    return " ".join(pieces).lower()


def _selected_parameters(proposal: dict[str, Any]) -> dict[str, Any]:
    for option in proposal.get("strategy_options") or []:
        if option.get("selected"):
            return dict(option.get("parameters") or {})
    return dict(proposal.get("parameters") or {})


def _finding(code: str, message: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "high", "message": message, "evidence": evidence}


def challenge_recommendation(
    recommendation: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Return evidence-labelled objections without changing the recommendation.

    The checks are intentionally explicit: an operator can see why a decision
    was escalated and a test can reproduce every rejection condition.
    """
    findings: list[dict[str, Any]] = []
    params = _selected_parameters(recommendation)
    strategy_text = _text(recommendation)

    supplier_ids = params.get("supplier_ids")
    requires_backup = bool(
        context.get("requires_backup_supplier")
        or (context.get("constraints") or {}).get("required_backup_suppliers")
    )
    if requires_backup and isinstance(supplier_ids, list) and len(supplier_ids) < 2:
        findings.append(_finding(
            "missing_backup_supplier",
            "Recommendation depends on fewer than two approved suppliers.",
            {"supplier_count": len(supplier_ids), "required": 2},
        ))

    constraints = dict(context.get("constraints") or {})
    estimated_cost = params.get("estimated_cost", recommendation.get("estimated_cost"))
    if constraints.get("max_budget") is not None and estimated_cost is not None:
        if float(estimated_cost) > float(constraints["max_budget"]):
            findings.append(_finding(
                "hard_budget_violation",
                "Estimated cost exceeds the declared maximum budget.",
                {"estimated_cost": float(estimated_cost), "max_budget": float(constraints["max_budget"])},
            ))

    required_coverage = constraints.get("min_coverage_rate")
    coverage = params.get("coverage_rate", recommendation.get("coverage_rate"))
    if required_coverage is not None and coverage is not None and float(coverage) < float(required_coverage):
        findings.append(_finding(
            "mandatory_coverage_ignored",
            "Recommendation does not meet the required demand coverage.",
            {"coverage_rate": float(coverage), "min_coverage_rate": float(required_coverage)},
        ))

    available_roles = set(context.get("available_agent_roles") or [])
    considered_roles = set(recommendation.get("considered_agent_roles") or [])
    if len(available_roles) >= 2 and considered_roles and considered_roles != available_roles:
        findings.append(_finding(
            "one_sided_recommendation",
            "Recommendation omits available specialist views.",
            {"considered_roles": sorted(considered_roles), "available_roles": sorted(available_roles)},
        ))

    for pattern in context.get("historical_failure_patterns") or []:
        marker = str(pattern.get("strategy_marker") or "").lower().strip()
        if marker and marker in strategy_text:
            findings.append(_finding(
                "historical_failure_pattern",
                "Recommendation matches a recorded historical failure pattern.",
                {"strategy_marker": marker, "failure_mode": str(pattern.get("failure_mode") or "unspecified")},
            ))

    return {
        "status": "challenged" if findings else "no_material_objection",
        "requires_manual_review": bool(findings),
        "findings": findings,
    }
