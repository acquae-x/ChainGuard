from types import SimpleNamespace

from src.model_registry import ModelRegistry
from src.drift_history import (
    append_snapshot,
    drift_history_path_for,
    load_snapshots,
    register_baseline,
    trend_series,
)


def _source(tmp_path, tenant_id: str = "tenant_i55"):
    return SimpleNamespace(
        kind="enterprise",
        tenant_id=tenant_id,
        audit_log_path=str(tmp_path / f"audit_log.{tenant_id}.jsonl"),
    )


def _report(success_rate=0.8, drop=0.0, severity="ok", sample_size=100):
    return {
        "sample_size": sample_size,
        "success_rate": success_rate,
        "baseline_success_rate": 0.85,
        "success_rate_drop": drop,
        "severity": severity,
    }


def test_append_and_load_roundtrip(tmp_path):
    data_source = _source(tmp_path)

    append_snapshot(data_source, _report(success_rate=0.80))
    append_snapshot(data_source, _report(success_rate=0.70, drop=0.10, severity="warn"))

    snapshots = load_snapshots(data_source)

    assert len(snapshots) == 2
    assert snapshots[0]["timestamp"] <= snapshots[1]["timestamp"]
    assert snapshots[1]["severity"] == "warn"


def test_load_missing_returns_empty(tmp_path):
    assert load_snapshots(_source(tmp_path)) == []


def test_load_skips_corrupt_lines(tmp_path):
    data_source = _source(tmp_path)
    append_snapshot(data_source, _report())
    path = drift_history_path_for(data_source)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not valid json\n")

    snapshots = load_snapshots(data_source)

    assert len(snapshots) == 1


def test_trend_series_fields(tmp_path):
    data_source = _source(tmp_path)
    append_snapshot(data_source, _report())

    series = trend_series(load_snapshots(data_source))

    assert series
    for point in series:
        assert set(point) == {
            "timestamp",
            "success_rate",
            "success_rate_drop",
            "severity",
        }


def test_trend_series_empty():
    assert trend_series([]) == []


def test_history_path_isolation(tmp_path):
    demo = SimpleNamespace(
        kind="demo",
        tenant_id="default",
        audit_log_path=str(tmp_path / "audit_log.jsonl"),
    )
    tenant = _source(tmp_path, "acme_i55")

    assert drift_history_path_for(demo) == tmp_path / "drift_history.jsonl"
    assert drift_history_path_for(tenant) == tmp_path / "drift_history.acme_i55.jsonl"
    assert drift_history_path_for(demo) != drift_history_path_for(tenant)


def test_register_baseline_promotes(tmp_path):
    registry = ModelRegistry(tmp_path / "model_registry.json")

    result = register_baseline(0.8, registry=registry)

    assert result["promoted"] is True
    stable = registry.get_stable()
    assert stable is not None
    assert stable.metrics["success_rate"] == 0.8


def test_input_changes_output():
    high = [{"timestamp": "2026-01-01T00:00:00", "success_rate": 0.9}]
    low = [{"timestamp": "2026-01-01T00:00:00", "success_rate": 0.4}]

    high_series = trend_series(high)
    low_series = trend_series(low)

    assert [p["success_rate"] for p in high_series] != [
        p["success_rate"] for p in low_series
    ]
