"""A03 库存风险重算：把已有引擎函数接到租户实体上，不新写任何评分公式。

设计约束：
- 分数一律由 ``src.inventory_monitor.calculate_inventory_risk`` 算出，本模块不做任何算术加权；
- 阈值/权重经 ``TenantContextBuilder`` 解析，与 C1 决策链路同源，保证"解释里的阈值"
  与"生成方案时用的阈值"是同一个值；
- 重算只管自己产生的风险（``details.origin == "recompute"``），
  人工判断过的状态（ignored / incident_created）不被机器覆盖；
- 幂等：实体数据不变时重复重算对 ``risks`` 表零写入（连 updated_at 都不动）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.inventory_monitor import calculate_inventory_risk

from .context_builder import ContextBuildError, MaterialSnapshot, TenantContextBuilder
from .models import Material, Risk

RECOMPUTE_ORIGIN = "recompute"
EXTERNAL_ORIGIN = "external_event"
RISK_TYPE = "库存"
OBJECT_TYPE = "物料"

# 引擎自身的三档预警分类 → 产品风险等级。此处不引入新阈值，
# warning_level 完全由 config/thresholds.yaml 的 red/yellow_support_hours 决定。
_LEVEL_BY_WARNING = {"红色预警": "high", "黄色预警": "medium", "正常": "low"}

# 主因标签：仅用于 rule 文案，不参与任何计算。
_DRIVER_LABELS = {
    "shortage_urgency": "缺货紧迫度",
    "order_importance": "关键订单覆盖",
    "transit_delay": "在途延误",
    "external_event": "外部事件",
}


def risk_id_for_material(tenant_id: str, material_id: str) -> str:
    """Deterministic primary key: no extra column, no JSON query, cross-DB identical."""
    digest = hashlib.sha1(f"{tenant_id}|inventory|{material_id}".encode("utf-8")).hexdigest()
    return f"risk-auto-{digest[:16]}"


@dataclass
class RecomputeResult:
    created: int = 0
    updated: int = 0
    resolved: int = 0
    recurred: int = 0
    unchanged: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "resolved": self.resolved,
            "recurred": self.recurred,
            "unchanged": self.unchanged,
            "skipped": list(self.skipped),
            "skippedCount": len(self.skipped),
        }


def _measurement(result: dict[str, Any], snapshot: MaterialSnapshot) -> dict[str, Any]:
    """Stable, decision-relevant numbers only.

    刻意排除一切"距现在多少小时"的相对时间字段（planned/estimated_arrival_hours、
    订单 due_hours）——它们每秒都在变，纳入后幂等断言必然失败，而它们对
    A03 解释也无需从风险行读取：解释接口是按实体实时算的。
    """
    inventory = snapshot.inventory
    return {
        "riskIndex": result["inventory_risk_index"],
        "warningLevel": result["warning_level"],
        "shouldTriggerResponse": result["should_trigger_response"],
        "supportHours": result["support_hours"],
        "safetyStockGap": result["safety_stock_gap"],
        "safetyStockGapRate": result["safety_stock_gap_rate"],
        "transitDelayHours": result["transit_delay_hours"],
        "criticalOrderCoverageRate": result["critical_order_coverage_rate"],
        "drivers": {
            "shortage_urgency": result["shortage_urgency_score"],
            "order_importance": result["order_importance_score"],
            "transit_delay": result["transit_delay_score"],
            "external_event": result["external_risk_score"],
        },
        "weights": dict(snapshot.risk_weights["inventory_risk_weights"]),
        "triggerThreshold": snapshot.thresholds["inventory_warning"]["inventory_risk_trigger"],
        "thresholds": {
            "yellowSupportHours": snapshot.thresholds["inventory_warning"]["yellow_support_hours"],
            "redSupportHours": snapshot.thresholds["inventory_warning"]["red_support_hours"],
        },
        "inputs": {
            "currentStock": inventory["current_stock"],
            "hourlyConsumption": inventory["hourly_consumption"],
            "safetyStock": inventory["safety_stock"],
            "inTransitQty": inventory["in_transit_qty"],
            "criticalOrderDemand": inventory["critical_order_demand"],
        },
        "configurationSource": snapshot.configuration["source"],
        "dataQuality": snapshot.data_quality.to_dict(),
        "narrative": list(result["explanation"]),
    }


def measure_material(result: dict[str, Any], snapshot: MaterialSnapshot) -> dict[str, Any]:
    """Public entry so the A03 explanation path measures exactly like recompute does."""
    return _measurement(result, snapshot)


def _dominant_driver(measurement: dict[str, Any]) -> str:
    weights = measurement["weights"]
    contributions = {
        key: float(weights.get(key, 0)) * float(score)
        for key, score in measurement["drivers"].items()
    }
    if not contributions:
        return ""
    # 并列时按固定键序取第一个，保证重复重算得到同一条 rule 文案。
    best = max(sorted(contributions), key=lambda key: contributions[key])
    return _DRIVER_LABELS.get(best, best)


def _rule_text(measurement: dict[str, Any]) -> str:
    return (
        f"库存风险指数 {measurement['riskIndex']} 超过触发阈值 "
        f"{measurement['triggerThreshold']}（主因：{_dominant_driver(measurement)}）"
    )[:255]


def _level_for(measurement: dict[str, Any]) -> str:
    return _LEVEL_BY_WARNING.get(str(measurement["warningLevel"]), "medium")


def _next_code(db: Session, tenant_id: str, now: datetime) -> str:
    prefix = f"RISK-{now:%Y%m%d}-A"
    existing = db.scalars(
        select(Risk.code).where(Risk.tenant_id == tenant_id, Risk.code.like(f"{prefix}%"))
    ).all()
    return f"{prefix}{len(existing) + 1:03d}"


def _push_history(details: dict[str, Any], measurement: dict[str, Any], stamp: str) -> None:
    history = list(details.get("snapshotHistory") or [])
    history.append({"at": stamp, "riskIndex": measurement["riskIndex"],
                    "warningLevel": measurement["warningLevel"]})
    details["snapshotHistory"] = history[-5:]


def _apply_measurement(risk: Risk, measurement: dict[str, Any], stamp: str) -> None:
    details = dict(risk.details or {})
    details["measurement"] = measurement
    details["computedAt"] = stamp
    _push_history(details, measurement, stamp)
    risk.details = details
    risk.score = float(measurement["riskIndex"])
    risk.level = _level_for(measurement)
    risk.rule = _rule_text(measurement)


def _changed(risk: Risk, measurement: dict[str, Any]) -> bool:
    return (risk.details or {}).get("measurement") != measurement


def recompute_inventory_risks(
    db: Session, tenant_id: str, *, now: datetime | None = None, commit: bool = True
) -> RecomputeResult:
    """Recompute every material's inventory risk for one tenant, then reconcile risk rows."""
    moment = now or datetime.now(timezone.utc)
    stamp = moment.isoformat()
    found_at = f"{moment:%Y-%m-%d %H:%M}"
    builder = TenantContextBuilder(db, tenant_id, now=moment)
    outcome = RecomputeResult()

    materials = list(
        db.scalars(
            select(Material).where(Material.tenant_id == tenant_id).order_by(Material.material_id)
        ).all()
    )
    for material in materials:
        try:
            snapshot = builder.build_material_snapshot(material)
        except ContextBuildError as error:
            # 数据不足不是失败，是"这个物料算不了"，如实记录不伪造分数。
            outcome.skipped.append(
                {"materialId": material.material_id, "code": error.code, "reason": error.message}
            )
            continue

        result = calculate_inventory_risk(
            snapshot.inventory, snapshot.risk_weights, snapshot.thresholds
        )
        measurement = _measurement(result, snapshot)
        triggered = bool(result["should_trigger_response"])
        risk_id = risk_id_for_material(tenant_id, material.material_id)
        existing = db.get(Risk, risk_id)

        if existing is None:
            if not triggered:
                continue  # 不产生"无风险"记录
            risk = Risk(
                id=risk_id,
                tenant_id=tenant_id,
                code=_next_code(db, tenant_id, moment),
                level=_level_for(measurement),
                type=RISK_TYPE,
                object_type=OBJECT_TYPE,
                object_name=material.material_name or material.material_id,
                score=float(measurement["riskIndex"]),
                rule=_rule_text(measurement),
                found_at=found_at,
                status="new",
                details={
                    "origin": RECOMPUTE_ORIGIN,
                    "riskType": "inventory",
                    # material_id / material 两个键都写：C1 _resolve_material 靠它们反查物料，
                    # 由重算产生的风险必须能直接用来建事件。
                    "material_id": material.material_id,
                    "material": material.material_id,
                    "materialName": material.material_name or material.material_id,
                    "recurrenceCount": 0,
                },
            )
            _apply_measurement(risk, measurement, stamp)
            db.add(risk)
            outcome.created += 1
            continue

        if (existing.details or {}).get("origin") != RECOMPUTE_ORIGIN:
            # 防御：id 命名空间已隔离，理论上不会命中；命中则说明有人手工占用了该 id。
            outcome.skipped.append(
                {"materialId": material.material_id, "code": "CG-A032",
                 "reason": "同 id 风险非重算来源，已跳过"}
            )
            continue

        status = existing.status
        if status == "ignored":
            # 人已经判过"不用管"，重扫不得复活，也不发通知；仅静默更新数值。
            if triggered and _changed(existing, measurement):
                _apply_measurement(existing, measurement, stamp)
                outcome.updated += 1
            else:
                outcome.unchanged += 1
            continue

        if status == "incident_created":
            # 事件生命周期由事件闭环决定，风险扫描无权把它置为已消除。
            details = dict(existing.details or {})
            no_longer = not triggered
            if _changed(existing, measurement) or bool(details.get("noLongerTriggering")) != no_longer:
                _apply_measurement(existing, measurement, stamp)
                details = dict(existing.details or {})
                if no_longer:
                    details["noLongerTriggering"] = True
                else:
                    details.pop("noLongerTriggering", None)
                existing.details = details
                outcome.updated += 1
            else:
                outcome.unchanged += 1
            continue

        if status == "resolved":
            if not triggered:
                outcome.unchanged += 1  # 已消除且仍不触发：不刷新，避免快照漂移
                continue
            details = dict(existing.details or {})
            details["recurrenceCount"] = int(details.get("recurrenceCount") or 0) + 1
            details["previousResolvedAt"] = details.get("resolvedAt")
            details.pop("resolvedAt", None)
            existing.details = details
            existing.status = "new"
            existing.found_at = found_at  # 复发按新发现计时，但 code 保持不变
            _apply_measurement(existing, measurement, stamp)
            outcome.recurred += 1
            continue

        # status in {"new", "watching"}：watching 是人做的标记，触发时不退回 new。
        if triggered:
            if _changed(existing, measurement):
                _apply_measurement(existing, measurement, stamp)
                outcome.updated += 1
            else:
                outcome.unchanged += 1
            continue

        _apply_measurement(existing, measurement, stamp)
        details = dict(existing.details or {})
        details["resolvedAt"] = stamp
        # 消除当时的真实数值快照——A03 在 CG-A031 场景下展示的就是它，
        # 而不是拿当前数据现编一个已经不成立的解释。
        details["lastExplanationSnapshot"] = measurement
        existing.details = details
        existing.status = "resolved"
        outcome.resolved += 1

    if commit:
        db.commit()
    return outcome
