from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DecisionResult:
    """Complete output of one ChainGuard decision workflow."""

    risk_weights: dict[str, Any]
    thresholds: dict[str, Any]
    context: dict[str, Any]
    inventory_risk: dict[str, Any]
    proposals: list[dict[str, Any]]
    conflict: dict[str, Any]
    rebuttal: dict[str, Any]
    arbitration: dict[str, Any]
    decision_confidence: dict[str, Any]
    experience_card: dict[str, Any]
    constraint_analysis: dict[str, Any]
    debate_result: dict[str, Any]
    experience_references: dict[str, Any]
    explanation: dict[str, Any]
    audit_entry: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a deep-copied, JSON-serializable representation."""
        return asdict(self)
