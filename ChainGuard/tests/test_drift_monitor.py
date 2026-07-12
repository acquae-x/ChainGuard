import sqlite3

from src.drift_monitor import (
    CRITICAL_DROP,
    WARN_DROP,
    calibrate_drift_thresholds,
    compute_drift,
    load_historical_decisions,
    run_recalibration_cycle,
)
from src.model_registry import ModelRegistry
from src.notifier import MockNotifier


def _rec(outcome, predicted_delay=10, actual_delay=12, predicted_cost=1000, actual_cost=1100):
    return {
        "outcome_status": outcome,
        "covered_demand_rate": 0.9 if outcome == "success" else 0.35,
        "predicted_delay_hours": predicted_delay,
        "actual_delay_hours": actual_delay,
        "predicted_cost": predicted_cost,
        "actual_cost": actual_cost,
        "production_downtime_hours": 0,
        "lost_orders": 0 if outcome == "success" else 2,
        "human_rating": 4 if outcome == "success" else 2,
    }


def _registry(tmp_path):
    return ModelRegistry(tmp_path / "registry.json")


def test_drift_no_baseline_is_ok():
    report = compute_drift([_rec("success") for _ in range(5)])

    assert report.drift_detected is False
    assert report.severity == "ok"
    assert report.recommended_action == "none"


def test_drift_critical_triggers_rollback():
    records = [_rec("success"), _rec("failed")]
    report = compute_drift(records, baseline_success_rate=0.9)

    assert report.severity == "critical"
    assert report.recommended_action == "review_rollback"
    assert report.drift_detected is True


def test_drift_warn_triggers_recalibrate():
    records = [_rec("success") for _ in range(17)] + [_rec("failed") for _ in range(3)]
    report = compute_drift(records, baseline_success_rate=0.9)

    assert WARN_DROP <= report.success_rate_drop < CRITICAL_DROP
    assert report.severity == "warn"
    assert report.recommended_action == "recalibrate"


def test_delay_error_computed():
    records = [
        _rec("success", predicted_delay=10, actual_delay=14),
        _rec("success", predicted_delay=7, actual_delay=10),
    ]
    report = compute_drift(records)

    assert abs(report.avg_delay_error - 3.5) < 0.01


def test_input_changes_output():
    all_success = [_rec("success") for _ in range(5)]
    many_failed = [_rec("success") for _ in range(2)] + [_rec("failed") for _ in range(3)]

    assert compute_drift(all_success).success_rate != compute_drift(many_failed).success_rate


def test_empty_records_no_crash():
    report = compute_drift([])

    assert report.sample_size == 0
    assert report.success_rate == 0.0
    assert report.severity == "ok"


def test_recalibration_registers_version_no_promote(tmp_path):
    registry = _registry(tmp_path)
    stable = registry.register("stable-v1", {"success_rate": 0.8})
    registry.promote_stable(stable.version_id)
    before_stable = registry.get_stable().version_id
    before_count = len(registry.load_all())

    run_recalibration_cycle([_rec("success")], registry=registry)

    assert len(registry.load_all()) == before_count + 1
    assert registry.get_stable().version_id == before_stable


def test_recalibration_alert_on_drift(tmp_path):
    drift_notifier = MockNotifier()
    drift_result = run_recalibration_cycle(
        [_rec("failed") for _ in range(5)],
        registry=_registry(tmp_path / "drift"),
        notifier=drift_notifier,
        baseline_success_rate=0.9,
    )

    assert drift_result["alert_sent"] is True
    assert len(drift_notifier.sent) == 1

    ok_notifier = MockNotifier()
    ok_result = run_recalibration_cycle(
        [_rec("success") for _ in range(5)],
        registry=_registry(tmp_path / "ok"),
        notifier=ok_notifier,
        baseline_success_rate=0.9,
    )

    assert ok_result["alert_sent"] is False
    assert ok_notifier.sent == []


def test_load_missing_table_returns_empty(tmp_path):
    db_path = tmp_path / "empty.db"
    sqlite3.connect(db_path).close()

    assert load_historical_decisions(db_path) == []


def test_offline_no_optional_deps(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    result = run_recalibration_cycle(
        [_rec("success")],
        registry=_registry(tmp_path),
        notifier=MockNotifier(),
    )

    assert {
        "drift",
        "suggestions",
        "registered_version",
        "should_promote",
        "alert_sent",
        "drift_thresholds",
    } <= set(result)


def test_calibrate_thresholds_from_registry(tmp_path):
    registry = _registry(tmp_path)
    for index, rate in enumerate([0.9, 0.7, 0.5]):
        registry.register(f"v{index}", {"success_rate": rate})

    warn_drop, critical_drop = calibrate_drift_thresholds(registry)

    assert warn_drop != WARN_DROP
    assert critical_drop > warn_drop


def test_calibrate_fallback_few_versions(tmp_path):
    registry = _registry(tmp_path)
    registry.register("v1", {"success_rate": 0.9})
    registry.register("v2", {"success_rate": 0.8})

    assert calibrate_drift_thresholds(registry) == (WARN_DROP, CRITICAL_DROP)


def test_recalibration_returns_threshold_source(tmp_path):
    result = run_recalibration_cycle(
        [_rec("success")],
        registry=_registry(tmp_path),
        notifier=MockNotifier(),
    )

    assert {"warn_drop", "critical_drop", "source"} <= set(result["drift_thresholds"])
    assert result["drift_thresholds"]["source"] in {"calibrated", "default"}
