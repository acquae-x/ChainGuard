from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TimelineValue:
    cumulative_net_benefit: float
    event_count: int
    average_net_benefit: float
    latest_event_key: str
    latest_event_net_benefit: float
    latest_event_timestamp: str
    per_event_series: list[dict[str, Any]] = field(default_factory=list)


def aggregate_timeline_value(audit_entries: list[dict[str, Any]]) -> TimelineValue:
    _ZERO = TimelineValue(
        cumulative_net_benefit=0.0,
        event_count=0,
        average_net_benefit=0.0,
        latest_event_key="",
        latest_event_net_benefit=0.0,
        latest_event_timestamp="",
        per_event_series=[],
    )
    if not audit_entries:
        return _ZERO

    # 按 event_key 分组，保留 timestamp 最新的一条
    latest_by_key: dict[str, dict[str, Any]] = {}
    for entry in audit_entries:
        if "net_benefit" not in entry:
            continue  # 旧记录无经济字段，视为未测量
        key = str(entry.get("event_key") or "")
        if not key:
            continue
        ts = str(entry.get("timestamp") or "")
        prev = latest_by_key.get(key)
        if prev is None or ts >= str(prev.get("timestamp") or ""):
            latest_by_key[key] = entry

    if not latest_by_key:
        return _ZERO

    deduped = sorted(
        latest_by_key.values(),
        key=lambda e: str(e.get("timestamp") or ""),
    )
    cumulative = float(sum(float(e.get("net_benefit", 0) or 0) for e in deduped))
    count = len(deduped)
    latest = deduped[-1]

    return TimelineValue(
        cumulative_net_benefit=cumulative,
        event_count=count,
        average_net_benefit=(cumulative / count) if count else 0.0,
        latest_event_key=str(latest.get("event_key") or ""),
        latest_event_net_benefit=float(latest.get("net_benefit", 0) or 0),
        latest_event_timestamp=str(latest.get("timestamp") or ""),
        per_event_series=[
            {
                "event_key": str(e.get("event_key") or ""),
                "timestamp": str(e.get("timestamp") or ""),
                "net_benefit": float(e.get("net_benefit", 0) or 0),
            }
            for e in deduped
        ],
    )
