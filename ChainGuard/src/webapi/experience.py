"""Tenant-scoped persistence and retrieval adapter for experience cards.

The decision engine remains unchanged.  This module adapts its existing TF-IDF
experience feedback to cards selected from the authenticated tenant's database.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.feedback import ExperienceFeedback, RetrievalResult
from src.learning import generate_experience_card

from .models import ExperienceCard, Incident, Job, Proposal, Task


def retrieval_cards_for_tenant(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    """Return retrieval payloads only after a mandatory tenant predicate."""
    rows = db.scalars(
        select(ExperienceCard)
        .where(ExperienceCard.tenant_id == tenant_id)
        .order_by(ExperienceCard.created_at.desc())
    ).all()
    return [copy.deepcopy(row.content.get("retrievalCard") or row.content) for row in rows]


def retrieve_tenant_experience(db: Session, tenant_id: str, context: dict[str, Any]) -> RetrievalResult:
    cards = retrieval_cards_for_tenant(db, tenant_id)
    return ExperienceFeedback(cards=cards).retrieve(context)


def attach_retrieval_result(result: Any, retrieval: RetrievalResult) -> Any:
    """Annotate a completed engine result with the existing retrieval output."""
    proposals = []
    for proposal in result.proposals:
        enriched = copy.deepcopy(proposal)
        enriched["experience_hints"] = retrieval.risk_hints
        enriched["experience_confidence"] = retrieval.confidence_adjustment
        proposals.append(enriched)
    card = generate_experience_card(result.context, proposals, result.arbitration, retrieval_result=retrieval)
    card["parameter_note"] = "真实租户决策结果；后续仅在同一租户内作为辅助经验检索。"
    return replace(result, proposals=proposals, experience_card=card, experience_references=retrieval.to_dict())


def _selected_proposal(result: Any, proposals: list[Proposal]) -> Proposal | None:
    recommended = next((item for item in proposals if item.tag == "recommended"), None)
    return recommended or (proposals[0] if proposals else None)


def persist_job_experience(
    db: Session,
    *,
    tenant_id: str,
    job: Job,
    incident: Incident,
    result: Any,
    proposals: list[Proposal],
) -> ExperienceCard:
    """Idempotently materialize one structured card for a real tenant job."""
    selected = _selected_proposal(result, proposals)
    card_data = copy.deepcopy(result.experience_card)
    card_data["tenant_id"] = tenant_id
    card_data["source_job_id"] = job.id
    card_data["source_incident_id"] = incident.id
    card_data["source_proposal_id"] = selected.id if selected else None
    card_data["execution_result"] = {"state": "decision_generated", "summary": "真实租户决策作业已完成，待审批/执行结果回填。"}
    metrics = {
        "inventoryRiskIndex": (result.inventory_risk or {}).get("inventory_risk_index"),
        "proposalCount": len(proposals),
        "recommendedTotalCost": selected.total_cost if selected else None,
        "recommendedLeadTimeImpact": selected.lead_time_impact if selected else None,
    }
    references = copy.deepcopy((result.experience_references or {}).get("references") or [])
    row = db.scalar(select(ExperienceCard).where(
        ExperienceCard.tenant_id == tenant_id,
        ExperienceCard.source_job_id == job.id,
    ))
    if row is None:
        row = ExperienceCard(
            id=f"exp-{uuid.uuid4().hex}", tenant_id=tenant_id,
            source_job_id=job.id, source_incident_id=incident.id,
            source_proposal_id=selected.id if selected else None,
            dedupe_key=f"decision:{job.id}", title=str(card_data.get("final_decision_title") or incident.title),
            content={"retrievalCard": card_data, "event": (result.context.get("events") or [{}])[0], "inventory": result.context.get("inventory") or {}, "proposalSummary": {"id": selected.id if selected else None, "name": selected.name if selected else None}},
            status="generated", outcome=card_data["execution_result"], metrics=metrics, references=references,
        )
        db.add(row)
    else:
        row.title = str(card_data.get("final_decision_title") or incident.title)
        row.content = {"retrievalCard": card_data, "event": (result.context.get("events") or [{}])[0], "inventory": result.context.get("inventory") or {}, "proposalSummary": {"id": selected.id if selected else None, "name": selected.name if selected else None}}
        row.source_proposal_id = selected.id if selected else None
        row.outcome, row.metrics, row.references = card_data["execution_result"], metrics, references
    return row


def mark_incident_experience_confirmed(db: Session, tenant_id: str, incident_id: str, proposal_id: str) -> None:
    """Approval confirmation enriches only cards in the same tenant/incident."""
    rows = db.scalars(select(ExperienceCard).where(
        ExperienceCard.tenant_id == tenant_id,
        ExperienceCard.source_incident_id == incident_id,
    )).all()
    for row in rows:
        row.status = "confirmed"
        row.source_proposal_id = proposal_id
        row.outcome = {"state": "approved_for_execution", "summary": "方案已确认并进入执行。"}


def mark_incident_experience_completed(db: Session, tenant_id: str, incident_id: str) -> None:
    """Close the card only when every execution task for the tenant is complete."""
    unfinished = db.scalar(select(Task.id).where(
        Task.tenant_id == tenant_id,
        Task.incident_id == incident_id,
        Task.status.not_in(("completed", "done")),
    ).limit(1))
    if unfinished is not None:
        return
    rows = db.scalars(select(ExperienceCard).where(
        ExperienceCard.tenant_id == tenant_id,
        ExperienceCard.source_incident_id == incident_id,
    )).all()
    for row in rows:
        row.status = "completed"
        row.outcome = {"state": "execution_completed", "summary": "关联执行任务均已完成。"}
