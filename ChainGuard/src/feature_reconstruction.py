"""把历史决策还原成**决策时点的事前特征**，供参数校准使用。

## 为什么需要这个模块

旧版校准（`calibrate_inventory_risk_weights`）直接拿历史决策里的
`covered_demand_rate` / `lost_orders` / `actual_delay_hours` / `production_downtime_hours`
当特征，和成败标签做相关。这些全是**事后结果**，而标签本身就由它们决定
（丢单数 > 0 基本等于失败），属于典型的目标泄漏——算出来的不是"哪个风险因子重要"，
而是"哪个事后损失指标最能区分失败案例"。

更根本的是，线上的风险指数用的是另一组量：可支撑时长、关键订单覆盖率、
**预计**到货延误、事件严重度——全部事前可算。拿事后量标定出的权重去加权事前量，
两组变量量纲不同、分布不同、含义不同，这一步本身不成立。

本模块按决策时点重建那四个**事前**因子，并且**直接调用生产的
`calculate_inventory_risk`** 来算分量分数，保证校准特征与线上打分同一套公式。

## 数据来源与还原方式

| 事前因子 | 来源 |
|---|---|
| 可支撑时长 → shortage_urgency | 事件发生日的库存（快照回滚）÷ 物料小时消耗 |
| 关键订单覆盖 → order_importance | 快照 `allocated_qty`（已分配给订单的量）作为承诺需求 |
| 预计延误 → transit_delay | `disruption_events.estimated_delay_hours`（**预计**，非实际） |
| 事件强度 → external_event | `disruption_events.risk_score` |

库存快照只覆盖最后 31 天，而决策横跨整年，因此用 `inventory_movements`
从最早快照**反向回滚**求任意时点库存：`stock(t) = stock(S) − Σ movements in (t, S]`
（movement 的 quantity 自带符号：入库为正、出库为负）。

任何一项还原不出来的记录一律**剔除并计数**，绝不填默认值——
用编造的特征标定参数，比不标定更危险。
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from src.config_loader import load_risk_weights, load_thresholds
from src.inventory_monitor import calculate_inventory_risk

FACTORS = ("shortage_urgency", "order_importance", "transit_delay", "external_event")

# 失败口径：与既有阈值校准保持一致——部分成功也算未达预期，纳入正类。
FAILURE_STATUSES = frozenset({"failed", "partial_success"})
KNOWN_STATUSES = frozenset({"success", "partial_success", "failed"})


@dataclass(frozen=True)
class ReconstructedCase:
    """一条决策还原出的事前特征 + 结果标签。"""

    case_id: str
    event_id: str
    material_id: str
    decided_at: str
    features: dict[str, float]
    is_failure: int
    outcome_status: str


@dataclass
class ReconstructionResult:
    cases: list[ReconstructedCase] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)

    @property
    def sample_size(self) -> int:
        return len(self.cases)

    @property
    def failure_count(self) -> int:
        return sum(case.is_failure for case in self.cases)

    def exclude(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1

    def summary(self) -> dict[str, Any]:
        return {
            "sampleSize": self.sample_size,
            "failureCount": self.failure_count,
            "successCount": self.sample_size - self.failure_count,
            "excluded": dict(sorted(self.excluded.items(), key=lambda kv: -kv[1])),
            "excludedTotal": sum(self.excluded.values()),
        }


def _parse_moment(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    # 统一去掉时区，只用于先后比较与差值，不做跨时区换算
    return parsed.replace(tzinfo=None)


def _number(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # 过滤 NaN


class InventoryReconstructor:
    """按物料聚合快照，并用流水反向回滚到任意时点。"""

    def __init__(self, snapshots: Iterable[Mapping[str, Any]], movements: Iterable[Mapping[str, Any]]):
        # 同一物料跨仓库求和：线上风险指数看的是该物料的总可用量
        per_date: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        for row in snapshots:
            material_id = str(row.get("material_id") or "")
            date = str(row.get("snapshot_date") or "")[:10]
            if not material_id or not date:
                continue
            bucket = per_date[material_id][date]
            for source, target in (("available_qty", "available"), ("safety_stock_qty", "safety"), ("allocated_qty", "allocated")):
                value = _number(row.get(source))
                if value is not None:
                    bucket[target] += value

        # 每个物料取**最早**的快照作为回滚锚点，尽量缩短回滚跨度
        self._anchor: dict[str, tuple[datetime, dict[str, float]]] = {}
        for material_id, dates in per_date.items():
            earliest = min(dates)
            moment = _parse_moment(earliest)
            if moment is not None:
                self._anchor[material_id] = (moment, dict(dates[earliest]))

        # 流水按物料排序，便于二分求区间和
        self._moments: dict[str, list[datetime]] = {}
        self._cumulative: dict[str, list[float]] = {}
        staged: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        for row in movements:
            material_id = str(row.get("material_id") or "")
            moment = _parse_moment(row.get("movement_at"))
            quantity = _number(row.get("quantity"))
            if not material_id or moment is None or quantity is None:
                continue
            staged[material_id].append((moment, quantity))
        for material_id, entries in staged.items():
            entries.sort(key=lambda item: item[0])
            moments, running, total = [], [], 0.0
            for moment, quantity in entries:
                total += quantity
                moments.append(moment)
                running.append(total)
            self._moments[material_id] = moments
            self._cumulative[material_id] = running

    def _net_between(self, material_id: str, start: datetime, end: datetime) -> float:
        """(start, end] 区间内的净变动量。"""
        moments = self._moments.get(material_id)
        if not moments:
            return 0.0
        cumulative = self._cumulative[material_id]
        left, right = bisect_right(moments, start), bisect_right(moments, end)
        if right <= left:
            return 0.0
        before = cumulative[left - 1] if left > 0 else 0.0
        return cumulative[right - 1] - before

    def at(self, material_id: str, moment: datetime) -> dict[str, float] | None:
        """还原某物料在指定时点的库存状态。"""
        anchor = self._anchor.get(material_id)
        if anchor is None:
            return None
        anchor_moment, values = anchor
        available = values.get("available", 0.0)
        if moment < anchor_moment:
            # 锚点之前：stock(t) = stock(S) − Σ movements in (t, S]
            available -= self._net_between(material_id, moment, anchor_moment)
        elif moment > anchor_moment:
            available += self._net_between(material_id, anchor_moment, moment)
        return {
            "available": max(available, 0.0),
            # 安全库存与已分配量随时间变化不大，且流水里没有对应科目，沿用快照值。
            # 这是本模块唯一的近似，已在返回值里标注，不隐瞒。
            "safety": values.get("safety", 0.0),
            "allocated": values.get("allocated", 0.0),
            "approximated_fields": ("safety_stock", "allocated_qty"),
        }


def reconstruct_cases(
    decisions: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    snapshots: Sequence[Mapping[str, Any]],
    materials: Sequence[Mapping[str, Any]],
    movements: Sequence[Mapping[str, Any]],
) -> ReconstructionResult:
    """把历史决策还原成事前特征样本。剔除原因逐条计数，便于审计。"""

    result = ReconstructionResult()
    events_by_id = {str(row.get("event_id") or ""): row for row in events}
    materials_by_id = {str(row.get("material_id") or ""): row for row in materials}
    inventory = InventoryReconstructor(snapshots, movements)

    # 分量分数与权重无关，这里传专家配置只为满足函数签名
    risk_weights = load_risk_weights()
    thresholds = load_thresholds()

    for decision in decisions:
        status = str(decision.get("outcome_status") or "").strip()
        if status not in KNOWN_STATUSES:
            result.exclude("结果状态未知")
            continue

        event = events_by_id.get(str(decision.get("event_id") or ""))
        if event is None:
            result.exclude("关联不到扰动事件")
            continue

        material_id = str(event.get("affected_material_id") or "")
        material = materials_by_id.get(material_id)
        if material is None:
            result.exclude("关联不到物料主数据")
            continue

        moment = _parse_moment(event.get("started_at")) or _parse_moment(decision.get("created_at"))
        if moment is None:
            result.exclude("缺少可解析的时间")
            continue

        state = inventory.at(material_id, moment)
        if state is None:
            result.exclude("该物料没有库存快照可回滚")
            continue

        daily_consumption = _number(material.get("daily_consumption"))
        if not daily_consumption or daily_consumption <= 0:
            result.exclude("物料无有效日消耗")
            continue

        safety_stock = state["safety"]
        if safety_stock <= 0:
            result.exclude("安全库存为零或缺失")
            continue

        # **预计**延误（事前预报），不是 actual_delay_hours
        estimated_delay = _number(event.get("estimated_delay_hours"))
        if estimated_delay is None:
            result.exclude("事件缺少预计延误")
            continue

        external_score = _number(event.get("risk_score"))
        if external_score is None:
            result.exclude("事件缺少严重度评分")
            continue

        try:
            # 直接复用线上打分函数，确保校准特征与生产同一套公式
            scored = calculate_inventory_risk(
                {
                    "current_stock": state["available"],
                    "hourly_consumption": daily_consumption / 24.0,
                    "safety_stock": safety_stock,
                    "planned_arrival_hours": 0.0,
                    "estimated_arrival_hours": max(estimated_delay, 0.0),
                    "critical_order_demand": state["allocated"],
                    "external_risk_score": max(0.0, min(external_score, 100.0)),
                },
                risk_weights,
                thresholds,
            )
        except ValueError:
            result.exclude("事前指标不满足打分函数约束")
            continue

        result.cases.append(ReconstructedCase(
            case_id=str(decision.get("case_id") or ""),
            event_id=str(event.get("event_id") or ""),
            material_id=material_id,
            decided_at=moment.isoformat(),
            features={
                "shortage_urgency": scored["shortage_urgency_score"],
                "order_importance": scored["order_importance_score"],
                "transit_delay": scored["transit_delay_score"],
                "external_event": scored["external_risk_score"],
            },
            is_failure=1 if status in FAILURE_STATUSES else 0,
            outcome_status=status,
        ))

    return result
