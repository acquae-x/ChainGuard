"""生成校准治理 e2e 的固定夹具 CSV（提交进仓库，不在测试里现编）。

## 为什么需要这套夹具

监督式校准（src/supervised_calibration.py）的准入门要求：
有效样本 ≥ 80、正负类各 ≥ 40、样本外 AUC ≥ 0.55、至少一个因子系数为正。
而特征由 src/feature_reconstruction.py 从**事前**数据重建，缺一项就整行剔除：

| 事前因子 | 来源字段 |
|---|---|
| shortage_urgency | 快照 available_qty ÷ (materials.daily_consumption / 24) |
| order_importance | 快照 allocated_qty 与库存之比 |
| transit_delay | disruption_events.estimated_delay_hours |
| external_event | disruption_events.risk_score |

所以"空租户 + 一张历史决策 CSV"永远过不了准入门——必须同时具备
物料主数据、库存快照、扰动事件，且历史决策的 event_id 能关联上事件。

## 设计原则

**期望值从第一性原理推导，不从跑出来的结果反写。**

- 特征值由本脚本按闭式公式直接指定（见 _profile），每个因子在高风险档
  一律高于低风险档，因此逻辑回归系数必为正、AUC 必显著高于 0.55。
- 刻意注入 20% 标签噪声（每 5 条第 5 条取反档位），避免线性可分——
  完全可分的夹具 AUC=1.0，既不真实，也测不出准入门的判别力。
- 全程无随机数，纯 index 推导，任何人可复算。

## 样本量推导

主路径：120 条决策 = 60 失败 + 60 成功。
- 120 ≥ MIN_SAMPLES(80) ✓
- 各 60 ≥ MIN_PER_CLASS(40) ✓
- 每条决策都配齐事件/物料/快照，因此剔除数应为 0，重建样本量应恰为 120。

漂移批次：额外 120 条全失败决策，复用已有 event_id（同一事件上的新决策）。
- 确认时基线成功率 = 60/120 = 0.5
- 导入后 = 60/240 = 0.25，跌幅 = 0.25 ≥ critical_drop(0.15) → severity=critical
"""

from __future__ import annotations

import csv
from pathlib import Path

# 与 e2e 规格共用的常量；改动这里必须同步 calibration-governance-api-acceptance.spec.ts
MAIN_CASES = 120           # 主路径决策条数
DRIFT_CASES = 120          # 漂移批次决策条数（全部失败）
DAILY_CONSUMPTION = 240.0  # 所有物料统一日消耗 → 小时消耗 10
SNAPSHOT_DATE = "2026-07-01"
NOISE_MODULUS = 5          # 每 5 条第 5 条取反档位 → 20% 标签噪声

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "chainguard-web" / "e2e" / "fixtures" / "calibration"


def _profile(index: int, high_risk: bool) -> dict[str, float]:
    """按闭式公式给出一条样本的事前量。高风险档四个因子一律高于低风险档。

    支撑小时数直接决定 shortage_urgency = _linear_score(sh, low=24, high=72)；
    覆盖率决定 order_importance = (1 - coverage) * 100；
    预计延误决定 transit_delay = delay / 72 * 100；
    risk_score 即 external_event。
    """
    if high_risk:
        support_hours = 26.0 + (index % 10) * 1.5      # 26.0–39.5 → urgency 95.8–67.7
        coverage = 0.35 + (index % 5) * 0.03           # 0.35–0.47  → importance 65–53
        delay_hours = 40.0 + (index % 6) * 4.0         # 40–60      → transit 55.6–83.3
        risk_score = 70.0 + (index % 7) * 3.0          # 70–88
    else:
        support_hours = 55.0 + (index % 10) * 1.5      # 55.0–68.5 → urgency 35.4–7.3
        coverage = 0.85 + (index % 5) * 0.03           # 0.85–0.97 → importance 15–3
        delay_hours = 6.0 + (index % 6) * 2.0          # 6–16      → transit 8.3–22.2
        risk_score = 20.0 + (index % 7) * 3.0          # 20–38

    hourly = DAILY_CONSUMPTION / 24.0
    available = round(support_hours * hourly, 2)
    return {
        "available": available,
        # 安全库存必须 > 0，否则该行被"安全库存为零或缺失"剔除
        "safety": round(available * 0.5 + 100.0, 2),
        # 覆盖率 = min(available / allocated, 1)，反解 allocated
        "allocated": round(available / coverage, 2),
        "delay_hours": delay_hours,
        "risk_score": risk_score,
    }


def _is_high_risk(index: int, is_failure: bool) -> bool:
    """失败样本默认高风险档，每 5 条第 5 条取反 → 双向各 20% 噪声。"""
    flipped = index % NOISE_MODULUS == NOISE_MODULUS - 1
    return is_failure != flipped


def _write(name: str, header: list[str], rows: list[list[object]]) -> None:
    path = OUTPUT_DIR / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  {name}: {len(rows)} 行")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    materials: list[list[object]] = []
    snapshots: list[list[object]] = []
    events: list[list[object]] = []
    decisions: list[list[object]] = []

    for index in range(MAIN_CASES):
        is_failure = index < MAIN_CASES // 2
        profile = _profile(index, _is_high_risk(index, is_failure))

        material_id = f"CAL-MAT-{index:03d}"
        event_id = f"CAL-EVT-{index:03d}"
        # 事件日固定在快照锚点之后；无流水时库存恒等于锚点值，与具体日期无关
        started_at = f"2026-07-{(index % 28) + 1:02d}T08:00:00+00:00"

        materials.append([
            material_id, f"校准夹具物料 {index:03d}", "电子元器件", "件",
            "critical" if is_failure else "normal", 12.5, DAILY_CONSUMPTION,
        ])
        snapshots.append([
            f"CAL-SNP-{index:03d}", SNAPSHOT_DATE, material_id, "WH-CAL",
            round(profile["available"] * 12.5, 2),
            profile["available"], profile["safety"], profile["allocated"],
        ])
        events.append([
            event_id, "supply_disruption", "high" if is_failure else "medium",
            profile["risk_score"], material_id, started_at, profile["delay_hours"],
        ])
        decisions.append(_decision_row(
            case_id=f"CAL-CASE-{index:03d}",
            event_id=event_id,
            started_at=started_at,
            failed=is_failure,
        ))

    # 漂移批次：同一批事件上的新决策，结果全部失败。
    # 复用既有 event_id 保证仍能重建特征，不会因"关联不到扰动事件"被剔除。
    drift: list[list[object]] = []
    for index in range(DRIFT_CASES):
        drift.append(_decision_row(
            case_id=f"CAL-DRIFT-{index:03d}",
            event_id=f"CAL-EVT-{index % MAIN_CASES:03d}",
            started_at=f"2026-08-{(index % 28) + 1:02d}T08:00:00+00:00",
            failed=True,
        ))

    print(f"输出目录：{OUTPUT_DIR}")
    _write("materials.csv",
           ["material_id", "material_name", "category", "unit", "criticality", "standard_cost", "daily_consumption"],
           materials)
    _write("inventory-snapshots.csv",
           ["snapshot_id", "snapshot_date", "material_id", "warehouse_id", "inventory_value",
            "available_qty", "safety_stock_qty", "allocated_qty"],
           snapshots)
    _write("disruption-events.csv",
           ["event_id", "event_type", "severity", "risk_score", "affected_material_id",
            "started_at", "estimated_delay_hours"],
           events)
    _write("historical-decisions.csv", _DECISION_HEADER, decisions)
    _write("historical-decisions-drift.csv", _DECISION_HEADER, drift)

    status_index = _DECISION_HEADER.index("outcome_status")
    failures = sum(1 for row in decisions if row[status_index] == "failed")
    print(f"\n主路径：{len(decisions)} 条 = 失败 {failures} / 成功 {len(decisions) - failures}")
    print(f"漂移后成功率：{len(decisions) - failures}/{len(decisions) + len(drift)} = "
          f"{(len(decisions) - failures) / (len(decisions) + len(drift)):.4f}")


_DECISION_HEADER = [
    "case_id", "event_id", "selected_strategy", "created_at", "outcome_status",
    "covered_demand_rate", "actual_delay_hours", "predicted_delay_hours",
    "actual_cost", "predicted_cost", "lost_orders", "production_downtime_hours", "human_rating",
]


def _decision_row(*, case_id: str, event_id: str, started_at: str, failed: bool) -> list[object]:
    """事后字段只服务于漂移体检（成功率/误差），不参与事前特征重建。"""
    if failed:
        return [case_id, event_id, "emergency_purchase", started_at, "failed",
                0.30, 30.0, 10.0, 1500.0, 1000.0, 2, 8.0, 2]
    return [case_id, event_id, "standard_replenishment", started_at, "success",
            0.95, 4.0, 10.0, 1000.0, 1000.0, 0, 0.0, 5]


if __name__ == "__main__":
    main()
