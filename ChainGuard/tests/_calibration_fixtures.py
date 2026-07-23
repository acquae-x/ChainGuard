"""构造带**已知信号**的校准数据集，供校准闭环测试使用。

为什么需要：企业演示数据包的 `outcome_status` 由一个纯随机隐变量生成
（见 scripts/generate_enterprise_demo_data.py 的 `latent_quality`），
与库存状态、事件强度完全无关。因此监督式校准在那份数据上**会正确地拒绝**，
无法用来演示"校准成功并生效"这条路径。

这里生成一份事前因子与结果之间确有因果关系的数据：
先随机取事前原始输入 → 用生产打分函数算出四个因子分 →
按植入的真实权重算风险指数 → 以此为概率抽取成败标签。

这样重建出来的特征与线上完全一致，且信号是我们放进去的，可验证。
"""

from __future__ import annotations

import math
import random
from typing import Any

from src.config_loader import load_risk_weights, load_thresholds
from src.inventory_monitor import calculate_inventory_risk

TRUE_WEIGHTS = {
    "shortage_urgency": 0.45,
    "order_importance": 0.15,
    "transit_delay": 0.30,
    "external_event": 0.10,
}

SNAPSHOT_DATE = "2026-03-01"
EVENT_MOMENT = "2026-03-05T00:00:00+08:00"


def build_signal_dataset(count: int = 260, seed: int = 20260720) -> dict[str, Any]:
    """生成 decisions / events / snapshots / materials 四张表（movements 留空）。

    每个案例独占一个物料与快照，从而能自由控制其事前因子取值。
    """
    rng = random.Random(seed)
    risk_weights = load_risk_weights()
    thresholds = load_thresholds()

    decisions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []

    for index in range(count):
        material_id = f"MAT-SIG-{index:04d}"
        daily_consumption = rng.choice([120.0, 240.0, 480.0])
        hourly = daily_consumption / 24.0

        # 事前原始输入：覆盖从充裕到紧张的整个区间
        available = rng.uniform(0.2, 4.0) * hourly * 48
        safety_stock = rng.uniform(0.5, 2.0) * hourly * 24
        allocated = rng.uniform(0.3, 3.0) * available if available > 0 else 1.0
        estimated_delay = rng.uniform(0.0, 96.0)
        external_score = rng.uniform(10.0, 95.0)

        scored = calculate_inventory_risk(
            {
                "current_stock": available,
                "hourly_consumption": hourly,
                "safety_stock": max(safety_stock, 1.0),
                "planned_arrival_hours": 0.0,
                "estimated_arrival_hours": estimated_delay,
                "critical_order_demand": max(allocated, 0.0),
                "external_risk_score": external_score,
            },
            risk_weights,
            thresholds,
        )
        factors = {
            "shortage_urgency": scored["shortage_urgency_score"],
            "order_importance": scored["order_importance_score"],
            "transit_delay": scored["transit_delay_score"],
            "external_event": scored["external_risk_score"],
        }

        # 植入信号：真实风险指数越高，失败概率越高
        true_index = sum(TRUE_WEIGHTS[name] * factors[name] for name in TRUE_WEIGHTS)
        probability = 1 / (1 + math.exp(-(true_index - 50.0) / 10.0))
        failed = rng.random() < probability

        event_id = f"EVT-SIG-{index:04d}"
        materials.append({"material_id": material_id, "daily_consumption": daily_consumption})
        snapshots.append({
            "material_id": material_id,
            "snapshot_date": SNAPSHOT_DATE,
            "available_qty": round(available, 2),
            "safety_stock_qty": round(max(safety_stock, 1.0), 2),
            "allocated_qty": round(max(allocated, 0.0), 2),
        })
        events.append({
            "event_id": event_id,
            "affected_material_id": material_id,
            "risk_score": round(external_score, 2),
            "estimated_delay_hours": round(estimated_delay, 2),
            "started_at": EVENT_MOMENT,
            "severity": "high" if external_score > 70 else "medium",
        })
        decisions.append({
            "case_id": f"CASE-SIG-{index:04d}",
            "event_id": event_id,
            "outcome_status": "failed" if failed else "success",
            "created_at": EVENT_MOMENT,
            # 事后字段照常填充，但还原逻辑必须不碰它们
            "actual_delay_hours": round(estimated_delay * rng.uniform(0.5, 2.0), 2),
            "predicted_delay_hours": round(estimated_delay, 2),
            "actual_cost": round(rng.uniform(10000, 500000), 2),
            "predicted_cost": round(rng.uniform(10000, 500000), 2),
            "covered_demand_rate": round(rng.uniform(0.5, 1.0), 4),
            "production_downtime_hours": rng.randint(0, 48),
            "lost_orders": rng.randint(0, 5),
            "human_rating": rng.randint(1, 5),
        })

    return {
        "decisions": decisions,
        "events": events,
        "snapshots": snapshots,
        "materials": materials,
        "movements": [],
        "truth": dict(TRUE_WEIGHTS),
    }
