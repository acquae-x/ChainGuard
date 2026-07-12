from types import SimpleNamespace

from src.data_source import demo_source
from src.supply_monitor import (
    ACTION_THRESHOLD,
    MonitorReport,
    NodeStatus,
    _overall_health,
    classify_status,
    scan_supply_chain,
)


def test_classify_normal():
    status, _ = classify_status(10)

    assert status == "normal"


def test_classify_watch():
    status, _ = classify_status(40)

    assert status == "watch"


def test_classify_warning():
    status, _ = classify_status(60)

    assert status == "warning"


def test_classify_action():
    assert classify_status(85) == ("action_required", "立即进入决策流程")


def test_classify_boundary():
    status, _ = classify_status(ACTION_THRESHOLD)

    assert status == "action_required"


def test_scan_demo_returns_report():
    report = scan_supply_chain(demo_source())

    assert isinstance(report, MonitorReport)
    assert report.scanned >= 1
    assert report.all_nodes
    assert {"normal", "watch", "warning", "action_required"} <= set(report.counts)


def test_action_queue_sorted_desc():
    report = scan_supply_chain(demo_source())
    risk_indexes = [node.risk_index for node in report.action_queue]

    assert risk_indexes == sorted(risk_indexes, reverse=True)


def test_action_queue_subset():
    report = scan_supply_chain(demo_source())

    assert all(
        node.status in {"warning", "action_required"}
        for node in report.action_queue
    )


def test_overall_health_logic():
    normal = _node("normal")
    warning = _node("warning")
    action = _node("action_required")

    assert _overall_health([normal, action]) == "at_risk"
    assert _overall_health([normal, warning]) == "attention"
    assert _overall_health([normal]) == "stable"


def test_scan_missing_db_empty():
    source = SimpleNamespace(
        scenario_db_path="tests/_runtime_tmp/missing_supply_monitor.db"
    )

    report = scan_supply_chain(source)

    assert report.scanned == 0
    assert report.skipped == 0
    assert report.overall_health == "stable"
    assert report.action_queue == []


def test_input_changes_output():
    low_status, _ = classify_status(10)
    high_status, _ = classify_status(85)

    assert low_status != high_status


def _node(status: str) -> NodeStatus:
    return NodeStatus(
        event_id=f"EVT-{status}",
        event_title=status,
        event_type="test",
        affected_material="MAT-1",
        affected_supplier="SUP-1",
        risk_index=0.0,
        status=status,
        recommended_action="test",
    )


# --- 数据驱动阈值校准（修复"行动队列永远为空"）---
from src.supply_monitor import (  # noqa: E402
    WATCH_THRESHOLD,
    WARNING_THRESHOLD,
    calibrate_monitor_thresholds,
)


def test_calibrate_thresholds_ordered_and_data_driven():
    # 有离散度的真实分布 → 阈值有序且不等于专家回退常量
    values = [10, 12, 15, 18, 20, 25, 30, 45, 50, 52]
    watch, warning, action = calibrate_monitor_thresholds(values)
    assert watch < warning < action
    assert (watch, warning, action) != (
        WATCH_THRESHOLD,
        WARNING_THRESHOLD,
        ACTION_THRESHOLD,
    )


def test_calibrate_thresholds_few_nodes_fallback():
    assert calibrate_monitor_thresholds([10, 20, 30]) == (
        WATCH_THRESHOLD,
        WARNING_THRESHOLD,
        ACTION_THRESHOLD,
    )


def test_calibrate_thresholds_no_spread_fallback():
    assert calibrate_monitor_thresholds([40.0] * 12) == (
        WATCH_THRESHOLD,
        WARNING_THRESHOLD,
        ACTION_THRESHOLD,
    )


def test_calibrate_makes_top_node_actionable():
    # 数据驱动阈值下，分布顶端的离群值应被判为 action_required（否则队列永远空）
    values = [10, 12, 15, 18, 20, 22, 25, 28, 30, 52]
    thresholds = calibrate_monitor_thresholds(values)
    status, _ = classify_status(52, thresholds=thresholds)
    assert status == "action_required"


def test_scan_demo_action_queue_nonempty():
    report = scan_supply_chain(demo_source())
    assert len(report.action_queue) >= 1
    assert report.calibrated_thresholds is not None
