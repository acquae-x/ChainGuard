"""租户级报表聚合。

口径原则沿用 P0-2：**指标无数据时返回 null，不伪装成 0**。
"本月净收益 0" 与 "本月还没有事件" 在经营语义上完全不同，前端据此显示"数据缺失"。

所有查询强制按 tenant_id 收敛；本模块只读，不写库。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Approval, ExperienceCard, Incident, Proposal, Risk, Task

# 报表默认回看窗口（月）。经营看板按月出数，6 个月够看趋势又不至于稀释当期。
DEFAULT_MONTHS = 6


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _window_start(months: int) -> datetime:
    # 用 30 天近似一个月：报表是趋势观察，不做财务期间对齐。
    return _utcnow() - timedelta(days=30 * max(1, months))


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite 取回的 datetime 可能没有 tzinfo，统一按 UTC 处理后再比较。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _month_key(moment: datetime) -> str:
    return f"{moment.year:04d}-{moment.month:02d}"


def _tenant_rows(db: Session, model: Any, tenant_id: str, since: datetime | None = None) -> list[Any]:
    rows = list(db.scalars(select(model).where(model.tenant_id == tenant_id)).all())
    if since is None:
        return rows
    return [row for row in rows if (_as_aware(row.created_at) or _utcnow()) >= since]


def _parse_due(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_aware(parsed)


# ---------------------------------------------------------------- 经营看板 L1


def executive_report(db: Session, tenant_id: str, months: int = DEFAULT_MONTHS) -> dict[str, Any]:
    """老板视角：系统价值主数字 = 避免损失 - 应急成本。"""
    since = _window_start(months)
    incidents = _tenant_rows(db, Incident, tenant_id, since)
    approvals = _tenant_rows(db, Approval, tenant_id, since)
    risks = _tenant_rows(db, Risk, tenant_id, since)

    avoided_loss = sum(float(item.loss or 0) for item in incidents)
    emergency_cost = sum(float(item.cost or 0) for item in incidents)

    # 无事件 => 净收益不可测量（null），而不是 0。
    net_benefit = round(avoided_loss - emergency_cost, 2) if incidents else None

    decided = [item for item in approvals if item.status in {"approved", "rejected"}]
    avg_response_hours = _mean([float(item.waiting_hours or 0) for item in decided])

    # 月度序列：避免损失 vs 应急成本，供 ECharts 折线/柱状叠加。
    buckets: dict[str, dict[str, float]] = {}
    for item in incidents:
        key = _month_key(_as_aware(item.created_at) or _utcnow())
        bucket = buckets.setdefault(key, {"avoidedLoss": 0.0, "emergencyCost": 0.0})
        bucket["avoidedLoss"] += float(item.loss or 0)
        bucket["emergencyCost"] += float(item.cost or 0)
    series = [
        {"month": key, "avoidedLoss": round(value["avoidedLoss"], 2), "emergencyCost": round(value["emergencyCost"], 2)}
        for key, value in sorted(buckets.items())
    ]

    # Top 风险供应商：按该供应商累计风险分排序，取前 5。
    supplier_scores: Counter[str] = Counter()
    for item in risks:
        if item.object_type == "supplier" and item.object_name:
            supplier_scores[item.object_name] += float(item.score or 0)
    top_suppliers = [
        {"name": name, "score": round(score, 2)}
        for name, score in supplier_scores.most_common(5)
    ]

    return {
        "window": {"months": months, "since": since.isoformat()},
        "netBenefit": net_benefit,
        "avoidedLoss": round(avoided_loss, 2) if incidents else None,
        "emergencyCost": round(emergency_cost, 2) if incidents else None,
        "riskCount": len(incidents),
        "avgResponseHours": avg_response_hours,
        "series": series,
        "topRiskSuppliers": top_suppliers,
    }


# ---------------------------------------------------------------- 运营看板 L2


def operation_report(db: Session, tenant_id: str, months: int = DEFAULT_MONTHS) -> dict[str, Any]:
    """供应链负责人视角：处理漏斗 + 任务超时。"""
    since = _window_start(months)
    risks = _tenant_rows(db, Risk, tenant_id, since)
    incidents = _tenant_rows(db, Incident, tenant_id, since)
    proposals = [item for item in _tenant_rows(db, Proposal, tenant_id, since) if not item.archived]
    approvals = _tenant_rows(db, Approval, tenant_id, since)
    tasks = _tenant_rows(db, Task, tenant_id, since)

    approved = [item for item in approvals if item.status == "approved"]
    completed_tasks = [item for item in tasks if item.status in {"done", "completed"}]

    # 漏斗：发现风险 → 建事件 → 出方案 → 批准 → 任务完成
    funnel = [
        {"stage": "发现风险", "count": len(risks)},
        {"stage": "建事件", "count": len(incidents)},
        {"stage": "出方案", "count": len(proposals)},
        {"stage": "批准", "count": len(approved)},
        {"stage": "执行完成", "count": len(completed_tasks)},
    ]

    now = _utcnow()
    open_tasks = [item for item in tasks if item.status not in {"done", "completed", "cancelled"}]
    overdue = [item for item in open_tasks if (due := _parse_due(item.due_at)) and due < now]
    overdue_rate = round(len(overdue) / len(open_tasks), 4) if open_tasks else None

    # 按承接角色统计超时，前端展示"按部门超时率"。
    by_role: dict[str, dict[str, int]] = {}
    for item in open_tasks:
        entry = by_role.setdefault(item.role_code or "unassigned", {"total": 0, "overdue": 0})
        entry["total"] += 1
        due = _parse_due(item.due_at)
        if due and due < now:
            entry["overdue"] += 1
    overdue_by_role = [
        {
            "roleCode": role,
            "total": value["total"],
            "overdue": value["overdue"],
            "rate": round(value["overdue"] / value["total"], 4) if value["total"] else None,
        }
        for role, value in sorted(by_role.items())
    ]

    type_distribution = [
        {"type": name, "count": count}
        for name, count in Counter(item.type for item in risks if item.type).most_common()
    ]
    level_distribution = [
        {"level": name, "count": count}
        for name, count in Counter(item.level for item in risks if item.level).most_common()
    ]

    return {
        "window": {"months": months, "since": since.isoformat()},
        "funnel": funnel,
        "overdueRate": overdue_rate,
        "overdueByRole": overdue_by_role,
        "riskTypeDistribution": type_distribution,
        "riskLevelDistribution": level_distribution,
    }


# ---------------------------------------------------------------- 应急复盘 L3


def response_report(db: Session, tenant_id: str, months: int = DEFAULT_MONTHS) -> dict[str, Any]:
    """应急效果：每事件一张复盘卡，方案预估 vs 实际。"""
    since = _window_start(months)
    incidents = _tenant_rows(db, Incident, tenant_id, since)
    proposals = _tenant_rows(db, Proposal, tenant_id, since)
    approvals = _tenant_rows(db, Approval, tenant_id, since)
    cards = _tenant_rows(db, ExperienceCard, tenant_id, since)

    proposals_by_incident: dict[str, list[Any]] = {}
    for item in proposals:
        proposals_by_incident.setdefault(item.incident_id, []).append(item)
    approvals_by_incident: dict[str, list[Any]] = {}
    for item in approvals:
        approvals_by_incident.setdefault(item.incident_id, []).append(item)
    cards_by_incident: Counter[str] = Counter(
        item.source_incident_id for item in cards if item.source_incident_id
    )

    events: list[dict[str, Any]] = []
    for incident in sorted(incidents, key=lambda row: _as_aware(row.created_at) or _utcnow(), reverse=True):
        related = proposals_by_incident.get(incident.id, [])
        adopted = next((item for item in related if not item.archived and not item.draft), None)

        # 预估成本来自被采纳方案；无方案或方案未给出成本时保持 null。
        estimated_cost = float(adopted.total_cost) if adopted and adopted.total_cost is not None else None
        actual_cost = float(incident.cost) if incident.cost is not None else None
        cost_diff = (
            round(actual_cost - estimated_cost, 2)
            if estimated_cost is not None and actual_cost is not None
            else None
        )

        decided = [item for item in approvals_by_incident.get(incident.id, []) if item.status in {"approved", "rejected"}]
        response_hours = _mean([float(item.waiting_hours or 0) for item in decided])

        events.append({
            "id": incident.id,
            "code": incident.code,
            "title": incident.title,
            "level": incident.level,
            "status": incident.status,
            "createdAt": (_as_aware(incident.created_at) or _utcnow()).isoformat(),
            "responseHours": response_hours,
            "estimatedCost": estimated_cost,
            "actualCost": actual_cost,
            "costDiff": cost_diff,
            "proposalCount": len(related),
            "experienceCards": cards_by_incident.get(incident.id, 0),
        })

    measured = [item["responseHours"] for item in events if item["responseHours"] is not None]

    return {
        "window": {"months": months, "since": since.isoformat()},
        "events": events,
        "avgResponseHours": _mean(measured),
        "experienceCardTotal": len(cards),
    }
