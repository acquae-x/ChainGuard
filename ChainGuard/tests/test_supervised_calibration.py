"""监督式参数校准的验收测试。

覆盖三类断言：
1. **估计器是对的**：植入已知权重能还原出来（否则"拒绝校准"这个结论不可信）
2. **拒绝是对的**：没有信号、样本不足、类别失衡、系数非正时必须拒绝而不是硬给一组数
3. **不再走泄漏口径**：治理层的建议只来自监督式校准，拒绝时维持专家先验
"""

from __future__ import annotations

import math
import random

import pytest

from src.config_loader import load_risk_weights
from src.feature_reconstruction import FACTORS, ReconstructedCase
from src.supervised_calibration import (
    MIN_AUC,
    calibrate_trigger_threshold_cost_sensitive,
    calibrate_weights_supervised,
)


def _case(features: dict[str, float], is_failure: int, index: int = 0) -> ReconstructedCase:
    return ReconstructedCase(
        case_id=f"c-{index}", event_id="e", material_id="m", decided_at="",
        features=features, is_failure=is_failure, outcome_status="",
    )


def _planted(truth: dict[str, float], n: int = 800, seed: int = 42) -> list[ReconstructedCase]:
    """按已知权重生成有信号的样本。"""
    rng = random.Random(seed)
    cases = []
    for index in range(n):
        features = {name: rng.uniform(0, 100) for name in FACTORS}
        risk_index = sum(truth[name] * features[name] for name in FACTORS)
        probability = 1 / (1 + math.exp(-(risk_index - 50) / 12))
        cases.append(_case(features, 1 if rng.random() < probability else 0, index))
    return cases


def _noise(n: int = 800, seed: int = 7) -> list[ReconstructedCase]:
    """特征与标签完全无关的样本。"""
    rng = random.Random(seed)
    return [
        _case({name: rng.uniform(0, 100) for name in FACTORS}, rng.randint(0, 1), index)
        for index in range(n)
    ]


# ------------------------------------------------------- 估计器本身是对的


def test_recovers_planted_weights():
    truth = {"shortage_urgency": 0.50, "order_importance": 0.20, "transit_delay": 0.20, "external_event": 0.10}
    outcome = calibrate_weights_supervised(_planted(truth), truth)

    assert outcome.ok, outcome.reason
    for name in FACTORS:
        assert outcome.weights[name] == pytest.approx(truth[name], abs=0.08), f"{name} 偏差过大"
    assert sum(outcome.weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert outcome.diagnostics["aucOutOfSample"] > 0.7


def test_recovers_a_different_weight_ordering():
    """换一组权重排序也要还原对，防止"碰巧接近专家值"。"""
    truth = {"shortage_urgency": 0.10, "order_importance": 0.15, "transit_delay": 0.55, "external_event": 0.20}
    outcome = calibrate_weights_supervised(_planted(truth, seed=99), truth)

    assert outcome.ok, outcome.reason
    ranked = sorted(outcome.weights, key=lambda name: outcome.weights[name], reverse=True)
    assert ranked[0] == "transit_delay", f"最大权重应还原为 transit_delay，实得 {ranked}"


# ------------------------------------------------------------ 拒绝是对的


def test_refuses_when_no_signal():
    expert = dict(load_risk_weights()["inventory_risk_weights"])
    outcome = calibrate_weights_supervised(_noise(), expert)

    assert not outcome.ok
    assert "AUC" in outcome.reason
    assert outcome.weights == {}, "无信号时不得产出任何权重"
    # 诊断信息仍要给全，便于管理员判断
    assert outcome.diagnostics["aucOutOfSample"] < MIN_AUC


def test_refuses_when_sample_too_small():
    truth = {"shortage_urgency": 0.50, "order_importance": 0.20, "transit_delay": 0.20, "external_event": 0.10}
    outcome = calibrate_weights_supervised(_planted(truth, n=40), truth)

    assert not outcome.ok
    assert "样本" in outcome.reason
    assert outcome.weights == {}


def test_refuses_when_classes_are_imbalanced():
    rng = random.Random(3)
    cases = [_case({name: rng.uniform(0, 100) for name in FACTORS}, 0, i) for i in range(200)]
    cases += [_case({name: rng.uniform(0, 100) for name in FACTORS}, 1, 200 + i) for i in range(5)]
    outcome = calibrate_weights_supervised(cases, dict(load_risk_weights()["inventory_risk_weights"]))

    assert not outcome.ok
    assert "不均衡" in outcome.reason


def test_negative_coefficient_factor_gets_zero_weight_not_absolute_value():
    """保护性因子必须权重置 0，而不是像旧法那样取绝对值当成风险放大项。"""
    rng = random.Random(11)
    cases = []
    for index in range(900):
        features = {name: rng.uniform(0, 100) for name in FACTORS}
        # external_event 越高越**不容易**失败（保护性）
        logit = (0.05 * features["shortage_urgency"] - 0.05 * features["external_event"] - 1.0)
        probability = 1 / (1 + math.exp(-logit))
        cases.append(_case(features, 1 if rng.random() < probability else 0, index))

    outcome = calibrate_weights_supervised(cases, dict(load_risk_weights()["inventory_risk_weights"]))

    assert outcome.ok, outcome.reason
    assert outcome.coefficients["external_event"] < 0, "该因子本应为负系数"
    assert outcome.weights["external_event"] == 0.0, "负系数因子不得获得正权重"
    assert "external_event" in outcome.diagnostics["zeroWeightedFactors"]


def test_reports_collinearity():
    truth = {"shortage_urgency": 0.50, "order_importance": 0.20, "transit_delay": 0.20, "external_event": 0.10}
    outcome = calibrate_weights_supervised(_planted(truth), truth)

    correlations = outcome.diagnostics["pairwiseFeatureCorrelation"]
    assert len(correlations) == 6, "四个因子应有 6 组两两相关"


# ------------------------------------------------------ 成本敏感触发阈值


def test_cost_sensitive_threshold_beats_recall_only_on_alert_volume():
    truth = {"shortage_urgency": 0.50, "order_importance": 0.20, "transit_delay": 0.20, "external_event": 0.10}
    cases = _planted(truth)
    result = calibrate_trigger_threshold_cost_sensitive(cases, truth)

    assert result["ok"], result.get("reason")
    assert result["method"] == "expected_cost_minimization"
    # 必须报出误报/漏报的实际权衡，而不是只给一个阈值数字
    for key in ("recall", "precision", "alertRate", "truePositive", "falsePositive", "falseNegative"):
        assert key in result
    assert 0.0 <= result["alertRate"] <= 1.0


def test_higher_false_negative_cost_lowers_threshold():
    """漏报代价越高，阈值应越低（更愿意多报）——方向性必须正确。"""
    truth = {"shortage_urgency": 0.50, "order_importance": 0.20, "transit_delay": 0.20, "external_event": 0.10}
    cases = _planted(truth)

    cautious = calibrate_trigger_threshold_cost_sensitive(cases, truth, false_negative_cost=50.0, false_positive_cost=1.0)
    relaxed = calibrate_trigger_threshold_cost_sensitive(cases, truth, false_negative_cost=2.0, false_positive_cost=1.0)

    assert cautious["value"] <= relaxed["value"]
    assert cautious["recall"] >= relaxed["recall"]


def test_threshold_rejects_single_class_sample():
    cases = [_case({name: 50.0 for name in FACTORS}, 0, i) for i in range(100)]
    result = calibrate_trigger_threshold_cost_sensitive(cases, dict(load_risk_weights()["inventory_risk_weights"]))

    assert not result["ok"]
    assert result["value"] is None


# ------------------------------- §13 模型对比：泄漏口径 vs 事前口径


def _demo_pack_available() -> bool:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "demo_assets" / "enterprise" / "csv" / "historical_decisions.csv").exists()


@pytest.mark.skipif(not _demo_pack_available(), reason="缺少企业演示数据包")
def test_pre_event_model_comparison_is_far_weaker_than_leaky_one():
    """事前特征的分类效果必须显著低于泄漏口径——0.712 不是预测能力。

    这条测试锁住的是一个**结论**：在当前演示数据上，用事前特征几乎学不到东西
    （接近多数类基线），而用事后指标能到 0.7+，差距正是目标泄漏的体现。
    """
    import csv, io, random
    from pathlib import Path

    from src.feature_reconstruction import reconstruct_cases
    from src.model_comparison import (
        PRE_EVENT_FEATURE_NAMES,
        compare_models,
        extract_pre_event_features,
    )
    from src.training_dataset import DatasetSplit

    base = Path(__file__).resolve().parents[1] / "demo_assets" / "enterprise" / "csv"

    def load(name):
        with io.open(base / name, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    reconstruction = reconstruct_cases(
        load("historical_decisions.csv"), load("disruption_events.csv"),
        load("inventory_snapshots.csv"), load("materials.csv"), load("inventory_movements.csv"),
    )
    records = [{**case.features, "outcome_status": case.outcome_status} for case in reconstruction.cases]
    random.Random(42).shuffle(records)
    cut = int(len(records) * 0.7)
    split = DatasetSplit(train=records[:cut], validation=records[cut:], test=[])

    report = compare_models(
        split, feature_extractor=extract_pre_event_features, feature_names=PRE_EVENT_FEATURE_NAMES,
    )

    prior = next(item for item in report.model_results if item.model_name == "PriorClassifier")
    assert report.best_f1_macro < 0.45, (
        f"事前特征 f1_macro={report.best_f1_macro:.3f} 意外偏高——"
        "若真有预测能力，需重新核对特征是否仍混入事后信息"
    )
    assert report.best_f1_macro - prior.f1_macro < 0.15, "相对多数类基线没有实质提升"
    assert report.feature_names == PRE_EVENT_FEATURE_NAMES
