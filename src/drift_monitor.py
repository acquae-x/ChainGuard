from __future__ import annotations

import math
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.parameter_calibration import evaluate_decision_outcomes


WARN_DROP: float = 0.05
CRITICAL_DROP: float = 0.15


@dataclass(frozen=True)
class DriftReport:
    sample_size: int
    success_rate: float
    avg_delay_error: float
    avg_cost_error_ratio: float
    baseline_success_rate: float | None
    success_rate_drop: float
    drift_detected: bool
    severity: str
    findings: list[str] = field(default_factory=list)
    recommended_action: str = "none"


def calibrate_drift_thresholds(registry: Any) -> tuple[float, float]:
    """Infer drift thresholds from registry success_rate variance."""
    rates: list[float] = []
    for record in registry.load_all():
        metrics = getattr(record, "metrics", {}) or {}
        if "success_rate" not in metrics:
            continue
        try:
            rates.append(float(metrics["success_rate"]))
        except (TypeError, ValueError):
            continue

    if len(rates) < 3:
        return WARN_DROP, CRITICAL_DROP

    mean = sum(rates) / len(rates)
    sigma = math.sqrt(sum((rate - mean) ** 2 for rate in rates) / len(rates))
    warn = round(max(WARN_DROP, sigma), 4)
    critical = round(max(CRITICAL_DROP, 2 * sigma), 4)
    if critical <= warn:
        critical = round(warn + 0.01, 4)
    return warn, critical


def compute_drift(
    historical_decisions: list[dict[str, Any]],
    *,
    baseline_success_rate: float | None = None,
    warn_drop: float = WARN_DROP,
    critical_drop: float = CRITICAL_DROP,
) -> DriftReport:
    records = list(historical_decisions or [])
    outcome_summary = evaluate_decision_outcomes(records)
    sample_size = int(outcome_summary.get("sample_size", 0) or 0)

    if sample_size == 0:
        return DriftReport(
            sample_size=0,
            success_rate=0.0,
            avg_delay_error=0.0,
            avg_cost_error_ratio=0.0,
            baseline_success_rate=baseline_success_rate,
            success_rate_drop=0.0,
            drift_detected=False,
            severity="ok",
            findings=[
                "暂无可用于漂移体检的真实结果样本，已走空数据安全路径。",
                "当前成功率按 0.0% 记录，不使用模拟占位成功率。",
                "预测误差暂无有效样本，延迟与成本误差均记为 0。",
            ],
            recommended_action="none",
        )

    success_rate = float(outcome_summary.get("success_rate", 0.0) or 0.0)
    avg_delay_error = _mean_delay_error(records)
    avg_cost_error_ratio = _mean_cost_error_ratio(records)

    if baseline_success_rate is None:
        drop = 0.0
        severity = "ok"
        drift_detected = False
        recommended_action = "none"
        baseline_finding = "无基线，仅记录当前表现。"
    else:
        baseline = float(baseline_success_rate)
        drop = max(0.0, baseline - success_rate)
        if drop >= critical_drop:
            severity = "critical"
            drift_detected = True
            recommended_action = "review_rollback"
        elif drop >= warn_drop:
            severity = "warn"
            drift_detected = True
            recommended_action = "recalibrate"
        else:
            severity = "ok"
            drift_detected = False
            recommended_action = "none"
        baseline_finding = f"相对基线变化：下降 {drop:.1%}。"

    findings = [
        f"样本量 {sample_size} 条，当前成功率 {success_rate:.1%}。",
        baseline_finding,
        f"预测延迟平均误差 {avg_delay_error:.2f} 小时。",
        f"预测成本平均误差率 {avg_cost_error_ratio:.1%}。",
    ]

    return DriftReport(
        sample_size=sample_size,
        success_rate=round(success_rate, 4),
        avg_delay_error=round(avg_delay_error, 4),
        avg_cost_error_ratio=round(avg_cost_error_ratio, 4),
        baseline_success_rate=baseline_success_rate,
        success_rate_drop=round(drop, 4),
        drift_detected=drift_detected,
        severity=severity,
        findings=findings,
        recommended_action=recommended_action,
    )


def load_historical_decisions(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []

    conn = sqlite3.connect(path)
    try:
        cursor = conn.execute("SELECT * FROM historical_decisions")
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def run_recalibration_cycle(
    historical_decisions: list[dict[str, Any]],
    *,
    registry: Any | None = None,
    notifier: Any | None = None,
    baseline_success_rate: float | None = None,
    snapshot_version: str | None = None,
) -> dict[str, Any]:
    if registry is None:
        from src.model_registry import ModelRegistry

        registry = ModelRegistry()
    if notifier is None:
        from src.notifier import MockNotifier

        notifier = MockNotifier()

    warn_drop, critical_drop = calibrate_drift_thresholds(registry)
    threshold_source = (
        "calibrated"
        if (warn_drop, critical_drop) != (WARN_DROP, CRITICAL_DROP)
        else "default"
    )
    report = compute_drift(
        historical_decisions,
        baseline_success_rate=baseline_success_rate,
        warn_drop=warn_drop,
        critical_drop=critical_drop,
    )
    suggestions = evaluate_decision_outcomes(historical_decisions)

    utc_now = datetime.now(timezone.utc).isoformat()
    snapshot = snapshot_version or f"recalib-{utc_now}"
    metrics = {
        "success_rate": report.success_rate,
        "avg_delay_error": report.avg_delay_error,
    }
    record = registry.register(
        snapshot,
        metrics,
        notes="; ".join(report.findings)[:200],
    )
    should_promote = registry.should_replace_stable(metrics, metric="success_rate")

    alert_sent = False
    if report.drift_detected:
        from src.notifier import NotificationPayload
        from src.observability import log_event

        log_event(
            "drift_detected",
            severity=report.severity,
            success_rate=report.success_rate,
            drop=report.success_rate_drop,
        )
        payload = NotificationPayload(
            decision_id=snapshot,
            timestamp=utc_now,
            event_type="drift",
            inventory_risk_index=report.success_rate_drop * 100,
            human_approval_required=True,
            decision_status=report.severity,
        )
        notifier.send(payload)
        alert_sent = True

    return {
        "drift": asdict(report),
        "suggestions": suggestions,
        "registered_version": record.version_id,
        "should_promote": bool(should_promote),
        "alert_sent": alert_sent,
        "drift_thresholds": {
            "warn_drop": warn_drop,
            "critical_drop": critical_drop,
            "source": threshold_source,
        },
    }


def _mean_delay_error(records: list[dict[str, Any]]) -> float:
    errors: list[float] = []
    for record in records:
        actual = _to_float(record.get("actual_delay_hours"))
        predicted = _to_float(record.get("predicted_delay_hours"))
        if actual is None or predicted is None:
            continue
        errors.append(abs(actual - predicted))
    return sum(errors) / len(errors) if errors else 0.0


def _mean_cost_error_ratio(records: list[dict[str, Any]]) -> float:
    ratios: list[float] = []
    for record in records:
        actual = _to_float(record.get("actual_cost"))
        predicted = _to_float(record.get("predicted_cost"))
        if actual is None or predicted is None:
            continue
        ratios.append(abs(actual - predicted) / max(predicted, 1.0))
    return sum(ratios) / len(ratios) if ratios else 0.0


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
