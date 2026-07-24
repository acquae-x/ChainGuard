"""Replay a frozen multi-signal supply scan without reading outcome labels.

The script consumes the deterministic enterprise CSV fixture and writes only
under ``.workspace/`` by default.  It does not change production config or
the legacy inventory-only ``scan_supply_chain`` implementation.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.proactive_monitor import SignalFinding, scan_multisignal  # noqa: E402


DEFAULT_DATA_DIR = PROJECT_ROOT / "demo_assets" / "enterprise" / "csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".workspace" / "proactive-multisignal-scan"
EVALUATION_START = date(2026, 5, 30)
EVALUATION_END = date(2026, 6, 15)
LOOKBACK_DAYS = 14
BASELINE_SAFETY_RATIO = 0.80
BASELINE_SUPPORT_HOURS = 72.0


def main() -> int:
    args = _arguments()
    result = replay(Path(args.data_dir))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "replay-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "replay-report.md").write_text(_markdown(result), encoding="utf-8")
    print(json.dumps(result["comparison"], ensure_ascii=False, indent=2))
    print(f"Wrote {output_dir / 'replay-results.json'}")
    return 0


def replay(data_dir: Path) -> dict[str, Any]:
    tables = {
        name: _read_csv(data_dir / f"{name}.csv")
        for name in (
            "disruption_events",
            "supplier_performance",
            "sales_orders",
            "sales_order_lines",
            "quality_inspections",
            "shipments",
            "purchase_order_lines",
            "inventory_snapshots",
            "materials",
        )
    }
    events = [
        row
        for row in tables["disruption_events"]
        if EVALUATION_START <= _date(row["started_at"]) <= EVALUATION_END
    ]
    if not events:
        raise ValueError("No events in the frozen evaluation window")

    scan_start = EVALUATION_START - timedelta(days=LOOKBACK_DAYS)
    scan_end = min(EVALUATION_END, max(_date(row["started_at"]) for row in events))
    scan_dates = list(_date_range(scan_start, scan_end))
    multi_alerts = _unique_findings(
        finding
        for as_of in scan_dates
        for finding in scan_multisignal(
            as_of=as_of,
            supplier_performance=tables["supplier_performance"],
            sales_orders=tables["sales_orders"],
            sales_order_lines=tables["sales_order_lines"],
            quality_inspections=tables["quality_inspections"],
            shipments=tables["shipments"],
            purchase_order_lines=tables["purchase_order_lines"],
        )
    )
    baseline_alerts = _inventory_baseline_findings(
        scan_dates, tables["inventory_snapshots"], tables["materials"]
    )
    multi_score = _score("multisignal", multi_alerts, events, scan_dates)
    baseline_score = _score("inventory_only", baseline_alerts, events, scan_dates)
    common = _lead_deltas(multi_score["event_matches"], baseline_score["event_matches"])
    transit_rows = tables["shipments"]
    return {
        "protocol": {
            "evaluation_start": EVALUATION_START.isoformat(),
            "evaluation_end": EVALUATION_END.isoformat(),
            "events_evaluated": len(events),
            "scan_days": len(scan_dates),
            "lookback_days": LOOKBACK_DAYS,
            "baseline": {
                "available_stock_below_safety_ratio": BASELINE_SAFETY_RATIO,
                "support_hours_below": BASELINE_SUPPORT_HOURS,
            },
            "strict_point_in_time_rule": "Fields without an observation timestamp are not used as historical signals.",
        },
        "data_availability": {
            "shipment_rows": len(transit_rows),
            "shipment_rows_with_observed_at": sum(bool(row.get("observed_at")) for row in transit_rows),
            "in_transit_signal_used": any(alert.signal == "in_transit_delay" for alert in multi_alerts),
        },
        "baseline": baseline_score,
        "multisignal": multi_score,
        "comparison": {
            "recall_delta": round(multi_score["recall"] - baseline_score["recall"], 4),
            "additional_events_captured": len(
                set(multi_score["captured_event_ids"])
                - set(baseline_score["captured_event_ids"])
            ),
            "common_captured_events": len(common),
            "median_days_earlier_than_baseline": (
                round(float(median(common)), 2) if common else None
            ),
            "false_alerts_per_non_event_day": multi_score["false_alerts_per_non_event_day"],
        },
    }


def _inventory_baseline_findings(
    scan_dates: Iterable[date], snapshots: Iterable[dict[str, Any]], materials: Iterable[dict[str, Any]]
) -> list[SignalFinding]:
    daily_consumption = {
        str(row["material_id"]): _float(row.get("daily_consumption")) for row in materials
    }
    totals: dict[tuple[date, str], list[float]] = {}
    for row in snapshots:
        snapshot_date = _date(row["snapshot_date"])
        key = (snapshot_date, str(row["material_id"]))
        values = totals.setdefault(key, [0.0, 0.0])
        values[0] += _float(row.get("available_qty"))
        values[1] += _float(row.get("safety_stock_qty"))

    findings: list[SignalFinding] = []
    for as_of in scan_dates:
        for (snapshot_date, material_id), (available, safety) in totals.items():
            if snapshot_date != as_of or safety <= 0:
                continue
            support_hours = available / max(daily_consumption.get(material_id, 0.0) / 24, 1e-9)
            if available < safety * BASELINE_SAFETY_RATIO or support_hours < BASELINE_SUPPORT_HOURS:
                findings.append(
                    SignalFinding(
                        signal="inventory_only",
                        as_of=as_of,
                        supplier_id=None,
                        material_id=material_id,
                        evidence={
                            "available_qty": round(available, 2),
                            "safety_stock_qty": round(safety, 2),
                            "support_hours": round(support_hours, 2),
                        },
                    )
                )
    return _unique_findings(findings)


def _score(
    name: str,
    alerts: list[SignalFinding],
    events: list[dict[str, Any]],
    scan_dates: list[date],
) -> dict[str, Any]:
    matches: dict[str, dict[str, Any]] = {}
    covered_alerts: set[tuple[Any, ...]] = set()
    for event in events:
        event_date = _date(event["started_at"])
        eligible = [
            alert
            for alert in alerts
            if 0 <= (event_date - alert.as_of).days <= LOOKBACK_DAYS
            and _matches(alert, event)
        ]
        if eligible:
            earliest = min(eligible, key=lambda alert: alert.as_of)
            matches[str(event["event_id"])] = {
                "alert_date": earliest.as_of.isoformat(),
                "lead_days": (event_date - earliest.as_of).days,
                "signals": sorted({alert.signal for alert in eligible}),
            }
            covered_alerts.update(_finding_key(alert) for alert in eligible)

    false_alerts = [alert for alert in alerts if _finding_key(alert) not in covered_alerts]
    event_dates = {_date(event["started_at"]) for event in events}
    non_event_days = max(sum(day not in event_dates for day in scan_dates), 1)
    return {
        "name": name,
        "alerts": len(alerts),
        "alerts_by_signal": dict(sorted(Counter(alert.signal for alert in alerts).items())),
        "captured_events": len(matches),
        "captured_event_ids": sorted(matches),
        "recall": round(len(matches) / len(events), 4),
        "event_matches": matches,
        "false_alerts": len(false_alerts),
        "false_discovery_rate": round(len(false_alerts) / len(alerts), 4) if alerts else 0.0,
        "false_alerts_per_non_event_day": round(len(false_alerts) / non_event_days, 4),
    }


def _lead_deltas(multi: dict[str, Any], baseline: dict[str, Any]) -> list[int]:
    return [
        int(multi[event_id]["lead_days"]) - int(baseline[event_id]["lead_days"])
        for event_id in set(multi) & set(baseline)
    ]


def _matches(alert: SignalFinding, event: dict[str, Any]) -> bool:
    supplier = str(event.get("affected_supplier_id") or "")
    material = str(event.get("affected_material_id") or "")
    if alert.supplier_id and alert.material_id:
        return alert.supplier_id == supplier and alert.material_id == material
    if alert.supplier_id:
        return alert.supplier_id == supplier
    return alert.material_id == material


def _unique_findings(findings: Iterable[SignalFinding]) -> list[SignalFinding]:
    by_key = {_finding_key(finding): finding for finding in findings}
    return sorted(by_key.values(), key=_finding_key)


def _finding_key(finding: SignalFinding) -> tuple[Any, ...]:
    return (finding.as_of, finding.signal, finding.supplier_id, finding.material_id)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _markdown(result: dict[str, Any]) -> str:
    comparison = result["comparison"]
    multi = result["multisignal"]
    baseline = result["baseline"]
    return f"""# 多信号主动扫描回放结果

## 口径

- 评估事件：{result['protocol']['events_evaluated']}；扫描日：{result['protocol']['scan_days']}；提前窗口：{result['protocol']['lookback_days']} 天。
- 仅使用扫描时点可观测的字段。运输表没有 `observed_at`，所以在途延误信号未进入严格回放。
- 基线为库存单维反事实：可用库存低于安全库存 80%，或库存支撑低于 72 小时。

## 结果

| 指标 | 库存单维 | 多信号 |
| --- | ---: | ---: |
| 告警数 | {baseline['alerts']} | {multi['alerts']} |
| 捕获事件 | {baseline['captured_events']} | {multi['captured_events']} |
| 召回率 | {baseline['recall']:.1%} | {multi['recall']:.1%} |
| 误报数 | {baseline['false_alerts']} | {multi['false_alerts']} |
| 误发现率 | {baseline['false_discovery_rate']:.1%} | {multi['false_discovery_rate']:.1%} |

- 额外捕获：{comparison['additional_events_captured']} 起；召回变化：{comparison['recall_delta']:.1%}。
- 共同捕获 {comparison['common_captured_events']} 起；多信号相对基线中位提前：{comparison['median_days_earlier_than_baseline']} 天。
- 多信号每个无事件日误报：{comparison['false_alerts_per_non_event_day']:.2f} 条。

## 决定

该报告只呈现冻结规则的首轮结果。只有在预注册的三项成功标准全部满足时，才能进入“采纳”阶段；否则应归档为失败考古，且不得以本次结果改动阈值。
"""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
