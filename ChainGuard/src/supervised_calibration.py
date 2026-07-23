"""基于事前特征的监督式参数校准（替代归一化相关系数法）。

## 与旧方法的区别

旧：`weight_i = |pearson(x_i, y)| / Σ|pearson|`
- 用事后结果当特征，与标签构成目标泄漏
- 取绝对值丢掉方向，保护性因子会被当成风险放大项
- 边际相关不处理共线性：库存紧张与在途延误天然相关，共享方差被重复计入
- 无样本外验证，无从判断"校准后是不是真的更准"

新：对**事前**特征做带 L2 正则的逻辑回归，用系数定权重
- 特征由 `feature_reconstruction` 按决策时点还原，与线上打分同一套公式
- 系数是偏效应（控制其他因子后的净贡献），天然处理共线性
- 保留符号：系数 ≤ 0 的因子不获得正权重
- 分层切分训练/测试，报样本外 AUC 与 Brier，并与专家权重在**同一测试集**上对比

## 校准结果何时可用

满足以下全部条件才给出建议，否则明确拒绝（不回落到旧方法）：
- 有效样本 ≥ `MIN_SAMPLES`，且正负类各 ≥ `MIN_PER_CLASS`
- 至少一个因子的系数为正
- 样本外 AUC ≥ `MIN_AUC`（低于此值说明模型没学到东西，权重不可信）

"拒绝校准"是一个合法且重要的输出——拿不可信的权重去替换专家先验，比不换更糟。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from src.feature_reconstruction import FACTORS, ReconstructedCase

# 每个自变量至少 10 个正类事件（EPV 经验法则），4 个因子 → 正类 ≥ 40
MIN_SAMPLES = 80
MIN_PER_CLASS = 40
# 低于 0.55 基本等同随机排序，这样的模型定出的权重没有意义
MIN_AUC = 0.55
TEST_SIZE = 0.3
RANDOM_STATE = 20260720


@dataclass
class CalibrationOutcome:
    ok: bool
    reason: str = ""
    weights: dict[str, float] = field(default_factory=dict)
    coefficients: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "weights": self.weights,
            "coefficients": self.coefficients,
            "diagnostics": self.diagnostics,
            "method": "logistic_regression_pre_event",
        }


def _matrix(cases: Sequence[ReconstructedCase]) -> tuple[list[list[float]], list[int]]:
    xs = [[case.features[name] for name in FACTORS] for case in cases]
    ys = [case.is_failure for case in cases]
    return xs, ys


def _pairwise_correlations(xs: list[list[float]]) -> dict[str, float]:
    """报告因子间相关，供人工判断共线性严重程度（回归本身用 L2 处理）。"""
    import numpy as np

    array = np.asarray(xs, dtype=float)
    result: dict[str, float] = {}
    for i in range(len(FACTORS)):
        for j in range(i + 1, len(FACTORS)):
            left, right = array[:, i], array[:, j]
            if left.std() == 0 or right.std() == 0:
                value = 0.0
            else:
                value = float(np.corrcoef(left, right)[0, 1])
            result[f"{FACTORS[i]}~{FACTORS[j]}"] = round(value, 4)
    return result


def _score_with_weights(xs: list[list[float]], weights: dict[str, float]) -> list[float]:
    """按给定权重算风险指数，用于在同一测试集上对比排序能力。"""
    vector = [float(weights.get(name, 0.0)) for name in FACTORS]
    return [sum(value * coefficient for value, coefficient in zip(row, vector)) for row in xs]


def calibrate_weights_supervised(
    cases: Sequence[ReconstructedCase],
    expert_weights: dict[str, float],
) -> CalibrationOutcome:
    """用事前特征做逻辑回归，把系数转成风险权重。"""

    if len(cases) < MIN_SAMPLES:
        return CalibrationOutcome(False, f"有效样本 {len(cases)} 条，少于最低要求 {MIN_SAMPLES} 条")

    failures = sum(case.is_failure for case in cases)
    successes = len(cases) - failures
    if failures < MIN_PER_CLASS or successes < MIN_PER_CLASS:
        return CalibrationOutcome(
            False,
            f"正负类样本不均衡（失败 {failures} / 成功 {successes}），各需至少 {MIN_PER_CLASS} 条",
        )

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    xs, ys = _matrix(cases)
    x_train, x_test, y_train, y_test = train_test_split(
        xs, ys, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=ys,
    )

    # 标准化只用于稳定求解；系数会换算回原始 0–100 量纲再定权重
    scaler = StandardScaler().fit(x_train)
    model = LogisticRegression(max_iter=2000, C=1.0)  # C=1.0 即默认 L2 强度
    model.fit(scaler.transform(x_train), y_train)

    probabilities = model.predict_proba(scaler.transform(x_test))[:, 1]
    if len(set(y_test)) < 2:
        return CalibrationOutcome(False, "测试集只剩单一类别，无法评估")

    auc = float(roc_auc_score(y_test, probabilities))
    brier = float(brier_score_loss(y_test, probabilities))

    # 专家权重在同一测试集上的排序能力，作为对照基准
    expert_scores = _score_with_weights(x_test, expert_weights)
    expert_auc = float(roc_auc_score(y_test, expert_scores)) if len(set(expert_scores)) > 1 else 0.5

    # 标准化系数 → 原始量纲系数：beta_raw = beta_scaled / sigma
    scales = np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    raw_coefficients = model.coef_[0] / scales
    coefficients = {name: float(value) for name, value in zip(FACTORS, raw_coefficients)}

    diagnostics = {
        "sampleSize": len(cases),
        "failureCount": failures,
        "successCount": successes,
        "trainSize": len(x_train),
        "testSize": len(x_test),
        "aucOutOfSample": round(auc, 4),
        "brierOutOfSample": round(brier, 4),
        "expertAucSameTestSet": round(expert_auc, 4),
        "aucImprovement": round(auc - expert_auc, 4),
        "pairwiseFeatureCorrelation": _pairwise_correlations(xs),
        "regularization": "L2 (C=1.0)",
        "testSize_ratio": TEST_SIZE,
        "randomState": RANDOM_STATE,
    }

    if auc < MIN_AUC:
        return CalibrationOutcome(
            False,
            f"样本外 AUC {auc:.3f} 低于最低要求 {MIN_AUC}，模型未学到有效信号，不产出权重",
            coefficients=coefficients,
            diagnostics=diagnostics,
        )

    # 只有正系数才转成风险权重：系数 ≤ 0 表示该因子在控制其他因子后
    # 并不指向更高失败率，给它正权重等于凭空制造风险信号。
    positive = {name: value for name, value in coefficients.items() if value > 0}
    if not positive:
        return CalibrationOutcome(
            False, "所有因子系数均非正，数据不支持任何因子提高失败概率",
            coefficients=coefficients, diagnostics=diagnostics,
        )

    total = sum(positive.values())
    weights = {name: round(positive.get(name, 0.0) / total, 6) for name in FACTORS}
    # 修正舍入误差，保证严格和为 1
    drift = round(1.0 - sum(weights.values()), 6)
    dominant = max(weights, key=lambda name: weights[name])
    weights[dominant] = round(weights[dominant] + drift, 6)

    dropped = [name for name, value in coefficients.items() if value <= 0]
    if dropped:
        diagnostics["zeroWeightedFactors"] = dropped
        diagnostics["zeroWeightedNote"] = (
            "这些因子的系数非正（控制其他因子后不指向更高失败率），权重置 0 而非取绝对值"
        )

    return CalibrationOutcome(True, "", weights=weights, coefficients=coefficients, diagnostics=diagnostics)


# --------------------------------------------------------------- 触发阈值

# 漏报与误报的代价比。默认 10:1 的依据：漏掉一次真实中断的损失是整单履约损失
# （演示场景 ¥860,000 量级），而一次误报的代价是应急响应的组织成本
# （人力 + 可能的加急运费，量级在数万）。这个比值**必须按租户实际成本重设**，
# 不同企业差异极大——因此它是显式参数，不是藏在公式里的常数。
DEFAULT_FN_COST = 10.0
DEFAULT_FP_COST = 1.0


def calibrate_trigger_threshold_cost_sensitive(
    cases: Sequence[ReconstructedCase],
    weights: dict[str, float],
    *,
    false_negative_cost: float = DEFAULT_FN_COST,
    false_positive_cost: float = DEFAULT_FP_COST,
) -> dict[str, Any]:
    """按期望代价最小选触发阈值，而不是取失败样本分位数。

    旧做法取失败样本风险指数的 P25，等于只优化召回、完全不看误报量——
    而告警疲劳恰恰是风险系统最常见的死法：阈值一降，告警淹没用户，
    最后所有告警都被忽略，召回率再高也没有意义。
    """
    if not cases:
        return {"ok": False, "reason": "无样本", "value": None}
    if false_negative_cost <= 0 or false_positive_cost <= 0:
        return {"ok": False, "reason": "代价参数必须为正", "value": None}

    scored = [
        (sum(float(weights.get(name, 0.0)) * case.features[name] for name in FACTORS), case.is_failure)
        for case in cases
    ]
    scored.sort(key=lambda item: item[0])
    total_failures = sum(label for _, label in scored)
    total_normal = len(scored) - total_failures
    if total_failures == 0 or total_normal == 0:
        return {"ok": False, "reason": "样本只有单一类别，无法权衡误报与漏报", "value": None}

    # 候选阈值取相邻分数中点，避免恰好落在样本点上
    candidates = sorted({round(value, 4) for value, _ in scored})
    best: dict[str, Any] | None = None
    for threshold in candidates:
        alerted = [(value, label) for value, label in scored if value >= threshold]
        true_positive = sum(label for _, label in alerted)
        false_positive = len(alerted) - true_positive
        false_negative = total_failures - true_positive
        expected_cost = false_negative_cost * false_negative + false_positive_cost * false_positive
        if best is None or expected_cost < best["expectedCost"]:
            best = {
                "value": float(threshold),
                "expectedCost": float(expected_cost),
                "truePositive": true_positive,
                "falsePositive": false_positive,
                "falseNegative": false_negative,
                "recall": round(true_positive / total_failures, 4),
                "precision": round(true_positive / len(alerted), 4) if alerted else 0.0,
                "alertRate": round(len(alerted) / len(scored), 4),
            }

    assert best is not None
    return {
        "ok": True,
        "reason": "",
        "method": "expected_cost_minimization",
        "costs": {"falseNegative": false_negative_cost, "falsePositive": false_positive_cost},
        "sampleSize": len(scored),
        **best,
    }
