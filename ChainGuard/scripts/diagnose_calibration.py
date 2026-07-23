"""并排对比两代参数校准方法，输出可审计的诊断报告。

用法：
    python scripts/diagnose_calibration.py [--csv-dir demo_assets/enterprise/csv]

报告三件事：
1. 旧法（事后特征 + 归一化相关系数）算出什么
2. 新法（事前特征 + 逻辑回归 + 样本外验证）算出什么，或者为什么拒绝
3. 用一份**植入已知权重**的对照数据验证新法本身没坏

第 3 步很重要：如果新法在真实数据上拒绝校准，必须能证明"拒绝"是因为数据没信号，
而不是因为估计器本身有问题。
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import random
from pathlib import Path
from typing import Any

from src.config_loader import load_risk_weights, load_thresholds
from src.feature_reconstruction import FACTORS, ReconstructedCase, reconstruct_cases
from src.parameter_calibration import calibrate_inventory_risk_weights, calibrate_trigger_threshold
from src.supervised_calibration import (
    calibrate_trigger_threshold_cost_sensitive,
    calibrate_weights_supervised,
)

DEFAULT_CSV_DIR = Path("demo_assets/enterprise/csv")


def _load(directory: Path, name: str) -> list[dict[str, Any]]:
    path = directory / name
    if not path.exists():
        return []
    with io.open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _fmt_weights(weights: dict[str, float]) -> str:
    if not weights:
        return "（无）"
    return "  ".join(f"{name}={weights.get(name, 0.0):.4f}" for name in FACTORS)


def _rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def _planted_signal_control() -> None:
    """对照实验：数据里植入已知权重，看新法能否还原。"""
    rng = random.Random(42)
    truth = {"shortage_urgency": 0.50, "order_importance": 0.20, "transit_delay": 0.20, "external_event": 0.10}
    cases = []
    for index in range(800):
        features = {name: rng.uniform(0, 100) for name in FACTORS}
        risk_index = sum(truth[name] * features[name] for name in FACTORS)
        probability = 1 / (1 + math.exp(-(risk_index - 50) / 12))
        cases.append(ReconstructedCase(
            case_id=f"control-{index}", event_id="", material_id="", decided_at="",
            features=features, is_failure=1 if rng.random() < probability else 0, outcome_status="",
        ))

    outcome = calibrate_weights_supervised(cases, truth)
    print("植入真实权重 :", _fmt_weights(truth))
    if outcome.ok:
        print("新法还原权重 :", _fmt_weights(outcome.weights))
        print(f"样本外 AUC   : {outcome.diagnostics['aucOutOfSample']}")
        deviation = max(abs(outcome.weights[name] - truth[name]) for name in FACTORS)
        print(f"最大偏差     : {deviation:.4f}")
        print("结论         : 估计器本身工作正常——有信号时能把权重还原出来。")
    else:
        print("新法拒绝     :", outcome.reason)
        print("结论         : ⚠ 估计器在有信号的数据上也拒绝了，需要检查实现。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_CSV_DIR)
    args = parser.parse_args()
    directory = args.csv_dir

    decisions = _load(directory, "historical_decisions.csv")
    if not decisions:
        print(f"找不到历史决策数据：{directory / 'historical_decisions.csv'}")
        return 1

    expert = dict(load_risk_weights()["inventory_risk_weights"])
    expert_trigger = load_thresholds()["inventory_warning"]["inventory_risk_trigger"]

    _rule("专家先验（当前线上实际使用）")
    print("权重     :", _fmt_weights(expert))
    print("触发阈值 :", expert_trigger)

    # ---------------------------------------------------------------- 旧法
    _rule("旧法：事后特征 + 归一化相关系数（存在目标泄漏）")
    legacy = calibrate_inventory_risk_weights(decisions)
    legacy_weights = {name: legacy[name] for name in FACTORS if name in legacy}
    print("权重     :", _fmt_weights(legacy_weights))
    print("样本量   :", legacy.get("_sample_size"))
    legacy_trigger = calibrate_trigger_threshold(decisions, legacy_weights)
    print("触发阈值 :", legacy_trigger.get("value"), f"（{legacy_trigger.get('_method')}）")
    print()
    print("问题     : 特征 covered_demand_rate / lost_orders / actual_delay_hours /")
    print("           production_downtime_hours 全是事后结果，而标签 outcome_status")
    print("           正是由这些量算出来的——相关性接近同义反复，不是预测能力。")

    # ---------------------------------------------------------------- 新法
    _rule("新法：事前特征 + 逻辑回归 + 样本外验证")
    reconstruction = reconstruct_cases(
        decisions,
        _load(directory, "disruption_events.csv"),
        _load(directory, "inventory_snapshots.csv"),
        _load(directory, "materials.csv"),
        _load(directory, "inventory_movements.csv"),
    )
    summary = reconstruction.summary()
    print(f"重建样本 : {summary['sampleSize']} 条（失败 {summary['failureCount']} / 成功 {summary['successCount']}）")
    if summary["excluded"]:
        print("剔除原因 :", summary["excluded"])

    outcome = calibrate_weights_supervised(reconstruction.cases, expert)
    diagnostics = outcome.diagnostics
    if diagnostics:
        print(f"样本外AUC: {diagnostics.get('aucOutOfSample')}  (专家权重同测试集: {diagnostics.get('expertAucSameTestSet')})")
        print(f"Brier    : {diagnostics.get('brierOutOfSample')}")
        print("因子共线性:")
        for pair, value in (diagnostics.get("pairwiseFeatureCorrelation") or {}).items():
            flag = "  ← 高度共线" if abs(value) > 0.8 else ""
            print(f"           {pair:42} {value:+.4f}{flag}")

    if outcome.ok:
        print("权重     :", _fmt_weights(outcome.weights))
        trigger = calibrate_trigger_threshold_cost_sensitive(reconstruction.cases, outcome.weights)
        print(f"触发阈值 : {trigger['value']:.2f}（期望代价最小）")
        print(f"           召回 {trigger['recall']:.0%}  精确率 {trigger['precision']:.0%}  告警率 {trigger['alertRate']:.0%}")
    else:
        print("权重     : 拒绝产出")
        print("拒绝原因 :", outcome.reason)
        print("系数     :", {name: round(value, 5) for name, value in outcome.coefficients.items()})

    # ------------------------------------------------------------ 对照实验
    _rule("对照实验：植入已知权重，验证估计器本身")
    _planted_signal_control()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
