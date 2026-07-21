from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.vector_store import get_vector_store


@dataclass(frozen=True)
class ExperienceReference:
    """One matched historical experience card, scored by keyword overlap."""

    case_id: str
    scenario: str
    recommended_pattern: str
    tags: list[str]
    similarity_score: float


@dataclass(frozen=True)
class RetrievalResult:
    """Output of one experience retrieval session."""

    query: str
    references: list[ExperienceReference]
    reference_count: int
    confidence_adjustment: float
    risk_hints: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExperienceFeedback:
    """Retrieve similar historical experience cards and annotate current decision."""

    def __init__(
        self,
        cards_path: str | Path = "data/experience_cards.json",
        top_k: int = 3,
        *,
        cards: list[dict[str, Any]] | None = None,
    ) -> None:
        self.cards_path = Path(cards_path)
        self.top_k = top_k
        self.cards = cards

    def retrieve(self, context: dict[str, Any]) -> RetrievalResult:
        query = self._build_query(context)
        if self.cards is None and not self.cards_path.exists() and not self.cards_path.is_absolute():
            project_path = Path(__file__).resolve().parents[1] / self.cards_path
            if not project_path.exists():
                return self._empty_result(query)
        elif self.cards is None and not self.cards_path.exists():
            return self._empty_result(query)

        query_terms = self._query_terms(query)
        matches = get_vector_store(mode="tfidf", path=self.cards_path, cards=self.cards).search(query)
        references = [
            ExperienceReference(
                case_id=str(card.get("case_id", "")),
                scenario=str(card.get("scenario", "")),
                recommended_pattern=str(card.get("recommended_pattern", "")),
                tags=[str(tag) for tag in card.get("tags", [])],
                similarity_score=self._score_reference(card, query_terms),
            )
            for card in matches
        ]
        references = [
            reference for reference in references if reference.similarity_score > 0
        ]
        references.sort(
            key=lambda reference: (
                reference.similarity_score,
                reference.case_id,
            ),
            reverse=True,
        )
        top_references = references[: self.top_k]
        confidence_adjustment = round(0.1 * min(len(top_references), 3), 1)
        risk_hints = [
            f"类似案例「{reference.scenario[:30]}」建议：{reference.recommended_pattern}"
            for reference in top_references
        ]
        return RetrievalResult(
            query=query,
            references=top_references,
            reference_count=len(top_references),
            confidence_adjustment=confidence_adjustment,
            risk_hints=risk_hints,
        )

    @staticmethod
    def _empty_result(query: str) -> RetrievalResult:
        return RetrievalResult(
            query=query,
            references=[],
            reference_count=0,
            confidence_adjustment=0.0,
            risk_hints=[],
        )

    @staticmethod
    def _build_query(context: dict[str, Any]) -> str:
        events = context.get("events") or []
        if not events:
            return "应急供应链响应"
        event = events[0]
        inventory = context.get("inventory", {})
        values = [
            event.get("event_type") or event.get("type"),
            event.get("title"),
            inventory.get("material_name"),
            event.get("severity"),
        ]
        terms: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                terms.append(text)
                seen.add(text)
        return " ".join(terms) if terms else "应急供应链响应"

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        return [term for term in query.strip().lower().split() if term]

    @staticmethod
    def _score_reference(card: dict[str, Any], query_terms: list[str]) -> float:
        if not query_terms:
            return 0.0
        searchable = " ".join(
            [
                str(card.get("scenario", "")),
                str(card.get("failed_reason", "")),
                str(card.get("improvement_strategy", "")),
                str(card.get("recommended_pattern", "")),
                " ".join(str(item) for item in card.get("trigger_conditions", [])),
                " ".join(str(item) for item in card.get("tags", [])),
            ]
        ).lower()
        hits = sum(1 for term in query_terms if term in searchable)
        return round(min(hits / max(len(query_terms), 1), 1.0), 2)
