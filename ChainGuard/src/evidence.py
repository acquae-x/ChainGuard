from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Evidence:
    """Structured evidence for one strategy-change challenge."""

    agent: str
    metric: str
    current_strategy: str
    recommended_strategy: str
    system_utility_current: float
    system_utility_recommended: float
    system_utility_delta: float


@dataclass(frozen=True)
class DebateRound:
    """One round of challenge and response."""

    round_number: int
    target_agent: str
    evidence: Evidence
    action: str
    own_utility_before: float
    own_utility_after: float
    own_utility_delta: float


@dataclass(frozen=True)
class DebateResult:
    """Complete output of one structured debate session."""

    rounds: list[DebateRound]
    final_strategies: dict[str, str]
    strategies_updated: list[str]
    converged: bool
    total_rounds: int
    system_utility_before: float
    system_utility_after: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
