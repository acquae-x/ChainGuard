import datetime
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_PATH = "data/audit_log.jsonl"
RISK_APPROVAL_THRESHOLD: float = 80.0


@dataclass(frozen=True)
class AuditEntry:
    decision_id: str
    timestamp: str
    event_type: str
    event_severity: str
    inventory_risk_index: float
    constraint_feasible_count: int
    debate_converged: bool
    human_approval_required: bool
    decision_status: str
    error_message: str
    event_key: str = ""
    net_benefit: float = 0.0
    penalty_savings: float = 0.0
    profit_protected: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def approval_required(result: dict[str, Any]) -> bool:
    inventory_risk = result.get("inventory_risk") or {}
    debate_result = result.get("debate_result") or {}
    constraint_analysis = result.get("constraint_analysis") or {}
    challenger = result.get("challenger") or (result.get("rebuttal") or {}).get("challenger") or {}

    risk_index = float(inventory_risk.get("inventory_risk_index") or 0.0)
    converged = bool(debate_result.get("converged", True))
    feasible_count = int(constraint_analysis.get("feasible_count", 1) or 0)

    return (
        risk_index > RISK_APPROVAL_THRESHOLD
        or not converged
        or feasible_count == 0
        or bool(challenger.get("requires_manual_review", False))
    )


def build_audit_entry(
    result: dict[str, Any],
    *,
    status: str = "ok",
    error_message: str = "",
) -> AuditEntry:
    context = result.get("context") or {}
    events = context.get("events") or [{}]
    event = events[0] if events else {}
    inventory_risk = result.get("inventory_risk") or {}
    constraint_analysis = result.get("constraint_analysis") or {}
    debate_result = result.get("debate_result") or {}
    event_type = str(event.get("event_type") or event.get("type") or "unknown")
    title = str(event.get("title") or "")
    event_key = str(event.get("event_id") or f"{event_type}:{title}")
    try:
        from src.economic_impact import calculate_economic_impact

        impact = calculate_economic_impact(context)
        net_benefit = float(impact.net_benefit)
        penalty_savings = float(impact.penalty_savings)
        profit_protected = float(impact.profit_protected)
    except Exception:
        net_benefit = penalty_savings = profit_protected = 0.0

    return AuditEntry(
        decision_id=uuid.uuid4().hex,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        event_type=event_type,
        event_severity=str(event.get("severity") or event.get("weather_risk") or "unknown"),
        inventory_risk_index=float(inventory_risk.get("inventory_risk_index") or 0.0),
        constraint_feasible_count=int(constraint_analysis.get("feasible_count") or 0),
        debate_converged=bool(debate_result.get("converged", True)),
        human_approval_required=approval_required(result),
        decision_status=status,
        error_message=error_message,
        event_key=event_key,
        net_benefit=net_benefit,
        penalty_savings=penalty_savings,
        profit_protected=profit_protected,
    )


class AuditLog:
    def __init__(self, path: str | Path = DEFAULT_AUDIT_PATH) -> None:
        target = Path(path)
        self.path = target if target.is_absolute() else PROJECT_ROOT / target

    def append(self, entry: AuditEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def load(self) -> list[AuditEntry]:
        if not self.path.exists():
            return []
        entries: list[AuditEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                entries.append(AuditEntry(**json.loads(text)))
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
        return entries
