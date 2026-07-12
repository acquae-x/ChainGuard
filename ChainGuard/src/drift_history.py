from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.model_registry import ModelRegistry


_SNAPSHOT_FIELDS = (
    "sample_size",
    "success_rate",
    "baseline_success_rate",
    "success_rate_drop",
    "severity",
)


def drift_history_path_for(data_source: Any) -> Path:
    """Return the tenant-scoped drift snapshot file path."""
    audit_path = Path(getattr(data_source, "audit_log_path", "data/audit_log.jsonl"))
    parent = audit_path.parent
    tenant_id = getattr(data_source, "tenant_id", "default")
    kind = getattr(data_source, "kind", "demo")
    if kind == "demo" or tenant_id == "default":
        return parent / "drift_history.jsonl"
    return parent / f"drift_history.{tenant_id}.jsonl"


def _report_to_dict(report: Any) -> dict[str, Any]:
    if isinstance(report, dict):
        return report
    if is_dataclass(report) and not isinstance(report, type):
        return asdict(report)
    return {field: getattr(report, field, None) for field in _SNAPSHOT_FIELDS}


def append_snapshot(data_source: Any, report: Any) -> dict[str, Any]:
    """Append one drift snapshot with a UTC timestamp; return the written record."""
    data = _report_to_dict(report)
    raw_baseline = data.get("baseline_success_rate")
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_size": int(data.get("sample_size", 0) or 0),
        "success_rate": float(data.get("success_rate", 0.0) or 0.0),
        "success_rate_drop": float(data.get("success_rate_drop", 0.0) or 0.0),
        "severity": str(data.get("severity", "ok") or "ok"),
        "baseline_success_rate": (
            None if raw_baseline is None else float(raw_baseline)
        ),
    }
    path = drift_history_path_for(data_source)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    return snapshot


def load_snapshots(data_source: Any) -> list[dict[str, Any]]:
    """Load all snapshots in ascending time order; missing file returns []."""
    path = drift_history_path_for(data_source)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []
    snapshots: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            snapshots.append(obj)
    snapshots.sort(key=lambda snap: str(snap.get("timestamp", "")))
    return snapshots


def trend_series(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure: extract trend points sorted by time; empty input returns []."""
    series = [
        {
            "timestamp": snap.get("timestamp", ""),
            "success_rate": float(snap.get("success_rate", 0.0) or 0.0),
            "success_rate_drop": float(snap.get("success_rate_drop", 0.0) or 0.0),
            "severity": str(snap.get("severity", "ok") or "ok"),
        }
        for snap in snapshots
    ]
    series.sort(key=lambda point: str(point["timestamp"]))
    return series


def register_baseline(
    success_rate: float,
    *,
    registry: Any | None = None,
) -> dict[str, Any]:
    """Register the current success rate as the stable baseline (manual action)."""
    registry = registry or ModelRegistry()
    stamp = datetime.now(timezone.utc).isoformat()
    record = registry.register(
        f"baseline-{stamp}",
        {"success_rate": float(success_rate)},
        notes="人工注册基线",
    )
    registry.promote_stable(record.version_id)
    return {
        "version_id": record.version_id,
        "success_rate": float(success_rate),
        "promoted": True,
    }
