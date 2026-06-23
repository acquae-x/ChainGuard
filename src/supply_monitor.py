import statistics
from dataclasses import dataclass, field
from typing import Any

from src.config_loader import load_risk_weights, load_thresholds
from src.inventory_monitor import calculate_inventory_risk
from src.scenario_loader import ScenarioLoader


# 回退阈值（仅在样本不足/无离散度时使用）。正常情况下 scan_supply_chain 会用
# calibrate_monitor_thresholds 从本次扫描的真实风险分布数据驱动地推导阈值，
# 不再依赖这三个专家拍板的固定值。
WATCH_THRESHOLD: float = 35.0
WARNING_THRESHOLD: float = 55.0
ACTION_THRESHOLD: float = 70.0

# 数据驱动校准所需的最小节点数；低于此用回退常量。
MIN_CALIBRATION_NODES: int = 8
# z-score 离群系数：均值 + k·标准差。识别"相对最高风险"的节点而非依赖绝对硬阈值。
_WATCH_K: float = 0.5
_WARNING_K: float = 1.5
_ACTION_K: float = 2.5

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
    calibrated_thresholds: tuple[float, float, float] | None = None


def calibrate_monitor_thresholds(
    risk_values: list[float],
) -> tuple[float, float, float]:
    """从本次扫描的风险分布数据驱动地推导 (watch, warning, action) 阈值。

    方法：均值 + k·标准差（z-score 离群）。这样阈值随真实数据自适应——既不会因
    专家硬阈值定得过高而永远触发不了，也不会把整批低风险节点误判为高危。
    样本不足（< MIN_CALIBRATION_NODES）或分布无离散度 → 回退专家常量。
    """
    values = [float(v) for v in risk_values if v is not None]
    if len(values) < MIN_CALIBRATION_NODES:
        return WATCH_THRESHOLD, WARNING_THRESHOLD, ACTION_THRESHOLD
    mean = statistics.mean(values)
    sd = statistics.pstdev(values)
    if sd <= 1e-6:
        return WATCH_THRESHOLD, WARNING_THRESHOLD, ACTION_THRESHOLD
    return (mean + _WATCH_K * sd, mean + _WARNING_K * sd, mean + _ACTION_K * sd)


def classify_status(
    risk_index: float,
    *,
    thresholds: tuple[float, float, float] | None = None,
) -> tuple[str, str]:
    """Map an inventory risk value to a rule-based monitoring status.

    thresholds=(watch, warning, action)；缺省时用专家回退常量（保持纯函数默认行为）。
    """
    watch, warning, action = thresholds or (
        WATCH_THRESHOLD,
        WARNING_THRESHOLD,
        ACTION_THRESHOLD,
    )
    if risk_index >= action:
        return "action_required", "立即进入决策流程"
    if risk_index >= warning:
        return "warning", "准备预案，关注节点"
    if risk_index >= watch:
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

    # Pass 1：逐事件算真实风险，先不分级（分级阈值要等整体分布出来后再数据驱动校准）。
    raw: list[dict[str, Any]] = []
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
            event = context["events"][0]
            raw.append(
                {
                    "event_id": str(event.get("event_id") or event_id),
                    "event_title": str(event.get("title") or ""),
                    "event_type": str(event.get("event_type") or ""),
                    "affected_material": str(event.get("affected_material") or ""),
                    "affected_supplier": str(event.get("affected_supplier") or ""),
                    "risk_index": risk_index,
                }
            )
        except Exception:
            skipped += 1

    # Pass 2：从真实风险分布数据驱动地校准阈值，再据此分级。
    monitor_thresholds = calibrate_monitor_thresholds([r["risk_index"] for r in raw])
    nodes: list[NodeStatus] = []
    for item in raw:
        status, action = classify_status(
            item["risk_index"], thresholds=monitor_thresholds
        )
        nodes.append(
            NodeStatus(
                event_id=item["event_id"],
                event_title=item["event_title"],
                event_type=item["event_type"],
                affected_material=item["affected_material"],
                affected_supplier=item["affected_supplier"],
                risk_index=item["risk_index"],
                status=status,
                recommended_action=action,
            )
        )

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
        calibrated_thresholds=monitor_thresholds,
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
