from dataclasses import dataclass, field
from typing import Any

from src.config_loader import load_risk_weights, load_thresholds
from src.inventory_monitor import calculate_inventory_risk
from src.scenario_loader import ScenarioLoader


WATCH_THRESHOLD: float = 35.0
WARNING_THRESHOLD: float = 55.0
ACTION_THRESHOLD: float = 70.0

_STATUS_KEYS = ("normal", "watch", "warning", "action_required")


@dataclass(frozen=True)
class NodeStatus:
    event_id: str
    event_title: str
    event_type: str
    affected_material: str
    affected_supplier: str
    risk_index: float
    status: str
    recommended_action: str


@dataclass(frozen=True)
class MonitorReport:
    scanned: int
    skipped: int
    counts: dict[str, int]
    overall_health: str
    action_queue: list[NodeStatus]
    all_nodes: list[NodeStatus] = field(default_factory=list)


def classify_status(risk_index: float) -> tuple[str, str]:
    """Map an inventory risk value to a rule-based monitoring status."""
    if risk_index >= ACTION_THRESHOLD:
        return "action_required", "立即进入决策流程"
    if risk_index >= WARNING_THRESHOLD:
        return "warning", "准备预案，关注节点"
    if risk_index >= WATCH_THRESHOLD:
        return "watch", "持续观察"
    return "normal", "无需干预"


def scan_supply_chain(data_source: Any, *, limit: int = 200) -> MonitorReport:
    """Scan scenario events, compute inventory risk, and build an action queue."""
    risk_weights = load_risk_weights()
    thresholds = load_thresholds()

    try:
        loader = ScenarioLoader(getattr(data_source, "scenario_db_path", ""))
    except FileNotFoundError:
        return _empty_report()

    try:
        scenarios = loader.list_scenarios(limit=_effective_limit(limit))
    except Exception:
        return _empty_report()

    nodes: list[NodeStatus] = []
    skipped = 0

    for scenario in scenarios:
        try:
            event_id = str(scenario["event_id"])
            context = loader.load_context(event_id)
            risk = calculate_inventory_risk(
                context["inventory"],
                risk_weights,
                thresholds,
            )
            risk_index = _risk_index(risk)
            status, action = classify_status(risk_index)
            event = context["events"][0]
            nodes.append(
                NodeStatus(
                    event_id=str(event.get("event_id") or event_id),
                    event_title=str(event.get("title") or ""),
                    event_type=str(event.get("event_type") or ""),
                    affected_material=str(event.get("affected_material") or ""),
                    affected_supplier=str(event.get("affected_supplier") or ""),
                    risk_index=risk_index,
                    status=status,
                    recommended_action=action,
                )
            )
        except Exception:
            skipped += 1

    counts = _status_counts(nodes)
    action_queue = sorted(
        (
            node
            for node in nodes
            if node.status in {"warning", "action_required"}
        ),
        key=lambda node: node.risk_index,
        reverse=True,
    )
    return MonitorReport(
        scanned=len(nodes),
        skipped=skipped,
        counts=counts,
        overall_health=_overall_health(nodes),
        action_queue=action_queue,
        all_nodes=nodes,
    )


def _effective_limit(limit: int) -> int:
    if limit <= 0:
        return 1_000_000
    return limit


def _empty_report() -> MonitorReport:
    return MonitorReport(
        scanned=0,
        skipped=0,
        counts=_empty_counts(),
        overall_health="stable",
        action_queue=[],
        all_nodes=[],
    )


def _empty_counts() -> dict[str, int]:
    return {status: 0 for status in _STATUS_KEYS}


def _status_counts(nodes: list[NodeStatus]) -> dict[str, int]:
    counts = _empty_counts()
    for node in nodes:
        counts[node.status] = counts.get(node.status, 0) + 1
    return counts


def _overall_health(nodes: list[NodeStatus]) -> str:
    if any(node.status == "action_required" for node in nodes):
        return "at_risk"
    if any(node.status == "warning" for node in nodes):
        return "attention"
    return "stable"


def _risk_index(risk: dict[str, Any]) -> float:
    try:
        return float(risk.get("inventory_risk_index", 0.0))
    except (TypeError, ValueError):
        return 0.0
