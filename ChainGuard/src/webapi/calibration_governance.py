"""Tenant-scoped adapter for the existing calibration and drift engines.

This module deliberately does not implement any scoring or fitting logic.  It
only turns C2's tenant-scoped historical-decision import rows into the stable
input contract consumed by ``run_recalibration_cycle`` and prepares its output
for the settings UI.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.config_loader import load_risk_weights, load_thresholds
from src.drift_monitor import run_recalibration_cycle
from src.feature_reconstruction import reconstruct_cases
from src.model_registry import ModelRegistry
from src.supervised_calibration import (
    calibrate_trigger_threshold_cost_sensitive,
    calibrate_weights_supervised,
)

from .entity_mapping import activate_tenant_config
from .models import ImportJob, ImportSourceRow, Material, TenantConfig
from .notifications import ensure_rules, notify_event


_HISTORY_TABLE = "historical_decisions"
# 监督式校准还需要的三张事前数据表；缺哪张就明确告诉企业要补导哪张
_EVENT_TABLE = "disruption_events"
_SNAPSHOT_TABLE = "inventory_snapshots"
_MOVEMENT_TABLE = "inventory_movements"
_SUPERVISED_TABLES = (_EVENT_TABLE, _SNAPSHOT_TABLE, _MOVEMENT_TABLE)
_WEIGHT_KEYS = ("shortage_urgency", "order_importance", "transit_delay", "external_event")


class _D3DriftNotifier:
    """Adapter: let the existing drift engine decide *when* to alert.

    D3 remains the delivery path.  ``run_recalibration_cycle`` only requires
    a notifier with ``send``; this adapter records that the engine requested
    one without duplicating drift criteria.
    """

    def __init__(self) -> None:
        self.requested = False

    def send(self, _payload: Any) -> bool:
        self.requested = True
        return True


def _registry_path(tenant_id: str) -> Path:
    digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
    return Path(".workspace") / "calibration_registry" / digest / "model_registry.json"


def _coerce_history(row: ImportSourceRow) -> dict[str, Any]:
    payload = dict(row.payload) if isinstance(row.payload, dict) else {}
    # Import source rows have an immutable created_at too; retain it only as a
    # fallback when an ERP record does not provide its own event time.
    payload.setdefault("created_at", row.created_at.isoformat() if row.created_at else None)
    return payload


def load_tenant_history(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    """Read only C2 source rows for this tenant; never fall back to demo DBs."""

    rows = db.scalars(
        select(ImportSourceRow)
        .outerjoin(ImportJob, and_(
            ImportJob.id == ImportSourceRow.import_job_id,
            ImportJob.tenant_id == ImportSourceRow.tenant_id,
        ))
        .where(
            ImportSourceRow.tenant_id == tenant_id,
            # Direct ERP imports retain the canonical source table.  File
            # imports preserve their filename stem in source_table, so use
            # their already-confirmed C2 import type instead of guessing.
            or_(
                ImportSourceRow.source_table == _HISTORY_TABLE,
                ImportJob.import_type == "historical_decision",
            ),
        )
        .order_by(ImportSourceRow.created_at, ImportSourceRow.row_number)
    ).all()
    return [_coerce_history(row) for row in rows]


def _source_rows(db: Session, tenant_id: str, source_table: str, import_type: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ImportSourceRow)
        .outerjoin(ImportJob, and_(
            ImportJob.id == ImportSourceRow.import_job_id,
            ImportJob.tenant_id == ImportSourceRow.tenant_id,
        ))
        .where(
            ImportSourceRow.tenant_id == tenant_id,
            or_(ImportSourceRow.source_table == source_table, ImportJob.import_type == import_type),
        )
        .order_by(ImportSourceRow.created_at, ImportSourceRow.row_number)
    ).all()
    return [dict(row.payload or {}) for row in rows]


def load_supervised_cases(db: Session, tenant_id: str) -> tuple[Any, list[str]]:
    """还原监督式校准所需的事前特征样本。

    返回 (ReconstructionResult, 缺失的数据表)。缺表时不猜、不补默认值，
    直接把缺哪张表告诉企业——这比给出一组不可信的权重有用得多。
    """
    events = _source_rows(db, tenant_id, _EVENT_TABLE, "disruption_event")
    snapshots = _source_rows(db, tenant_id, _SNAPSHOT_TABLE, "inventory_snapshot")
    movements = _source_rows(db, tenant_id, _MOVEMENT_TABLE, "inventory_movement")
    materials = [
        {"material_id": item.material_id, "daily_consumption": item.daily_consumption}
        for item in db.scalars(select(Material).where(Material.tenant_id == tenant_id)).all()
    ]

    missing = [
        label for label, rows in (
            ("disruption_events", events),
            ("inventory_snapshots", snapshots),
            ("materials", materials),
        ) if not rows
    ]
    if missing:
        return None, missing

    decisions = _source_rows(db, tenant_id, _HISTORY_TABLE, "historical_decision")
    return reconstruct_cases(decisions, events, snapshots, materials, movements), []


def _supervised_section(db: Session, tenant_id: str, expert_weights: dict[str, Any]) -> dict[str, Any]:
    """监督式校准结果。任何一步不成立都如实说明原因，绝不回落到旧的泄漏口径。"""
    reconstruction, missing = load_supervised_cases(db, tenant_id)
    if missing:
        return {
            "ok": False,
            "reason": f"缺少重建事前特征所需的数据：{'、'.join(missing)}。请先导入这些资料后再校准。",
            "missingTables": missing,
            "weights": {},
            "diagnostics": {},
        }

    outcome = calibrate_weights_supervised(reconstruction.cases, expert_weights)
    payload = outcome.as_payload()
    payload["reconstruction"] = reconstruction.summary()
    if outcome.ok:
        payload["trigger"] = calibrate_trigger_threshold_cost_sensitive(reconstruction.cases, outcome.weights)
    return payload


def _time_range(records: list[dict[str, Any]]) -> dict[str, str | None]:
    values: list[datetime] = []
    for record in records:
        raw = record.get("created_at") or record.get("occurred_at") or record.get("closed_at")
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            values.append(parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc))
        except ValueError:
            continue
    return {
        "from": min(values).isoformat() if values else None,
        "to": max(values).isoformat() if values else None,
    }


def _confidence(sample_size: int) -> dict[str, Any]:
    # Presentation metadata only.  Calibration algorithms and their minimum
    # sample thresholds remain in parameter_calibration.py unchanged.
    if sample_size >= 50:
        return {"level": "high", "score": 95, "note": "≥50 条有效结果，建议可进入人工审核。"}
    if sample_size >= 20:
        return {"level": "medium", "score": 75, "note": "20–49 条有效结果，建议结合业务专家复核。"}
    if sample_size >= 5:
        return {"level": "low", "score": 50, "note": "达到引擎最小校准样本，但统计稳定性有限。"}
    return {"level": "insufficient", "score": 20, "note": "少于 5 条有效结果，校准引擎将回退专家默认值。"}


def _active_config(db: Session, tenant_id: str, config_type: str) -> TenantConfig | None:
    return db.scalar(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_type == config_type,
        TenantConfig.is_active.is_(True),
    ))


def _baseline(registry: ModelRegistry) -> float | None:
    stable = registry.get_stable()
    if stable is None:
        return None
    value = stable.metrics.get("success_rate")
    return float(value) if value is not None else None


def _numeric_weights(suggestion: dict[str, Any]) -> dict[str, float]:
    return {key: float(suggestion[key]) for key in _WEIGHT_KEYS if key in suggestion}


def _recommendation_id(weights: dict[str, Any], thresholds: dict[str, Any], records: list[dict[str, Any]]) -> str:
    stable = json.dumps({"weights": weights, "thresholds": thresholds, "history": _time_range(records)}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def build_governance_snapshot(db: Session, tenant_id: str, *, notify: bool = True) -> dict[str, Any]:
    """Run existing engines for a tenant and expose an auditable UI payload."""

    history = load_tenant_history(db, tenant_id)
    registry = ModelRegistry(_registry_path(tenant_id))
    notifier = _D3DriftNotifier()
    result = run_recalibration_cycle(
        history,
        registry=registry,
        notifier=notifier,
        baseline_success_rate=_baseline(registry),
        snapshot_version=f"tenant-{hashlib.sha256(tenant_id.encode()).hexdigest()[:12]}-{datetime.now(timezone.utc).isoformat()}",
    )
    suggestions = dict(result["suggestions"])
    expert_thresholds = load_thresholds()
    expert_weights = load_risk_weights()
    expert_inventory_weights = dict(expert_weights["inventory_risk_weights"])

    # 权重建议只认监督式校准（事前特征 + 逻辑回归 + 样本外验证）。
    # 旧的归一化相关系数法存在目标泄漏，其结果不再作为建议对外提供——
    # 校准不成立时宁可维持专家先验，也不给一组看起来精确、实则不可信的数字。
    supervised = _supervised_section(db, tenant_id, expert_inventory_weights)
    if supervised.get("ok"):
        suggested_weights = dict(supervised["weights"])
        trigger = {
            "value": supervised["trigger"]["value"],
            "_source": "cost_sensitive",
            "_sample_size": supervised["trigger"]["sampleSize"],
            "_method": supervised["trigger"]["method"],
            "_note": (
                f"按期望代价最小选取（漏报:误报 = "
                f"{supervised['trigger']['costs']['falseNegative']:.0f}:{supervised['trigger']['costs']['falsePositive']:.0f}），"
                f"召回 {supervised['trigger']['recall']:.0%}，精确率 {supervised['trigger']['precision']:.0%}，"
                f"告警率 {supervised['trigger']['alertRate']:.0%}"
            ),
        }
        suggested_thresholds = copy.deepcopy(expert_thresholds)
        suggested_thresholds.setdefault("inventory_warning", {})["inventory_risk_trigger"] = trigger["value"]
    else:
        suggested_weights = {}
        trigger = {
            "value": expert_thresholds["inventory_warning"]["inventory_risk_trigger"],
            "_source": "expert",
            "_sample_size": 0,
            "_method": "none",
            "_note": f"未产出数据驱动建议：{supervised.get('reason', '')}",
        }
        suggested_thresholds = copy.deepcopy(expert_thresholds)
    recommendation_id = _recommendation_id(suggested_weights, suggested_thresholds, history)

    drift = dict(result["drift"])
    notification_count = 0
    if notify and notifier.requested:
        ensure_rules(db, tenant_id)
        notification_count = notify_event(db, tenant_id, "drift_detected", {
            "title": f"校准漂移{ '严重' if drift.get('severity') == 'critical' else '预警' }：成功率下降 {float(drift.get('success_rate_drop') or 0):.1%}",
            "target": "/settings/thresholds",
        })

    active_threshold = _active_config(db, tenant_id, "thresholds")
    active_weights = _active_config(db, tenant_id, "risk_weights")
    drift_payload = {
        "sampleSize": drift["sample_size"],
        "successRate": drift["success_rate"],
        "avgDelayError": drift["avg_delay_error"],
        "avgCostErrorRatio": drift["avg_cost_error_ratio"],
        "baselineSuccessRate": drift["baseline_success_rate"],
        "successRateDrop": drift["success_rate_drop"],
        "driftDetected": drift["drift_detected"],
        "severity": drift["severity"],
        "findings": drift["findings"],
        "recommendedAction": drift["recommended_action"],
        "thresholds": {
            "warnDrop": result["drift_thresholds"]["warn_drop"],
            "criticalDrop": result["drift_thresholds"]["critical_drop"],
            "source": result["drift_thresholds"]["source"],
        },
        "notificationCount": notification_count,
    }
    return {
        "recommendationId": recommendation_id,
        "sample": {
            "totalRows": len(history),
            "effectiveRows": int(suggestions.get("sample_size", 0) or 0),
            "timeRange": _time_range(history),
            "confidence": _confidence(int(suggestions.get("sample_size", 0) or 0)),
        },
        "comparison": {
            "expert": {"thresholds": expert_thresholds, "riskWeights": expert_weights["inventory_risk_weights"]},
            "suggested": {"thresholds": suggested_thresholds, "riskWeights": suggested_weights},
            "active": {
                "thresholdsVersion": active_threshold.version if active_threshold else None,
                "weightsVersion": active_weights.version if active_weights else None,
                "approved": bool(active_threshold and active_threshold.approved_by and active_weights and active_weights.approved_by),
            },
        },
        "calculation": {
            "weightMethod": "logistic_regression_pre_event" if supervised.get("ok") else None,
            "weightNote": (
                f"事前特征逻辑回归，样本外 AUC {supervised['diagnostics'].get('aucOutOfSample')}"
                if supervised.get("ok") else supervised.get("reason")
            ),
            "trigger": trigger,
            "summary": suggestions.get("key_findings", []),
            "approvalGate": "建议仅供审核；只有管理员确认后才写入已批准租户配置并影响后续真实决策。",
        },
        # 监督式校准的完整诊断：样本重建情况、样本外 AUC、与专家权重的对照、
        # 因子共线性。不可用时这里会说明具体原因，供管理员判断该补什么数据。
        "supervised": supervised,
        "drift": drift_payload,
        "registeredVersion": result["registered_version"],
    }


def confirm_governance_snapshot(db: Session, tenant_id: str, approver_id: str, recommendation_id: str) -> dict[str, Any]:
    """Atomically apply the current recommendation after explicit approval."""

    snapshot = build_governance_snapshot(db, tenant_id)
    if recommendation_id != snapshot["recommendationId"]:
        raise ValueError("校准建议已变化，请刷新页面后重新确认")
    if snapshot["sample"]["effectiveRows"] < 5:
        raise ValueError("有效历史结果不足 5 条，不能确认校准建议")
    # 监督式校准不成立时不允许应用：没有通过样本外验证的权重一旦写入，
    # 就会以"已校准"的名义影响真实决策，比维持专家先验危险得多。
    supervised = snapshot.get("supervised") or {}
    if not supervised.get("ok"):
        raise ValueError(f"数据驱动校准未通过验证，不能应用：{supervised.get('reason', '原因未知')}")

    suggested = snapshot["comparison"]["suggested"]
    # 追溯信息必须跟着配置一起落库：只存数值的话，事后没人能回答
    # "这组权重是几条样本、用什么方法、依据哪次建议算出来的"——
    # 而"任何数字可现场复算/追溯"是本项目对外的核心承诺。
    provenance = {
        "recommendationId": recommendation_id,
        "sampleSize": snapshot["sample"]["effectiveRows"],
        "totalRows": snapshot["sample"]["totalRows"],
        "confidence": (snapshot["sample"].get("confidence") or {}).get("score"),
        "method": (snapshot.get("calculation") or {}).get("weightMethod") or "logistic_regression_pre_event",
        # 样本外 AUC 是这组权重可信度的核心证据，必须跟着配置一起留档
        "aucOutOfSample": (supervised.get("diagnostics") or {}).get("aucOutOfSample"),
        "expertAucSameTestSet": (supervised.get("diagnostics") or {}).get("expertAucSameTestSet"),
        "reconstructedSampleSize": (supervised.get("reconstruction") or {}).get("sampleSize"),
        "approvedBy": approver_id,
        "approvedAt": datetime.now(timezone.utc).isoformat(),
    }
    thresholds = activate_tenant_config(
        db, tenant_id, "thresholds", {**suggested["thresholds"], "_provenance": provenance},
        source="calibrated", approved_by=approver_id,
    )
    weights = activate_tenant_config(
        db, tenant_id, "risk_weights",
        {"inventory_risk_weights": suggested["riskWeights"], "_provenance": provenance},
        source="calibrated", approved_by=approver_id,
    )
    # Promotion is deliberately after approval: an unconfirmed recommendation
    # is never considered the drift baseline or a decision configuration.
    registry = ModelRegistry(_registry_path(tenant_id))
    registry.promote_stable(str(snapshot["registeredVersion"]))
    return {"thresholdsVersion": thresholds.version, "weightsVersion": weights.version, "recommendationId": recommendation_id}
