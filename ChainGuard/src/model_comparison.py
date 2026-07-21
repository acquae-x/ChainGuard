from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from src.model_registry import ModelRegistry
from src.training_dataset import (
    DatasetSplit,
    train_prior_classifier,
)


# ⚠ 这五个特征全部是**事后结果指标**，而标签 outcome_status 正是由它们经
# derive_outcome_quality 算出来的。因此用它们预测 outcome_status 属于目标泄漏：
# 模型学到的是生成器的确定性映射，不是"提前预判成败"的能力。
# 保留该口径只为回答"能否从结果指标复原结果标签"，其指标**不得**作为预测能力对外引用。
# 真正的预测能力评估用下面的 PRE_EVENT_FEATURE_NAMES（事前可得）。
POST_HOC_FEATURE_NAMES: list[str] = [
    "covered_demand_rate",
    "delay_ratio",
    "cost_ratio",
    "downtime_norm",
    "human_rating_norm",
]

# 向后兼容别名；新代码请显式使用 POST_HOC_FEATURE_NAMES 或 PRE_EVENT_FEATURE_NAMES
FEATURE_NAMES: list[str] = POST_HOC_FEATURE_NAMES

# 事前特征：决策时点即可获得，与 src/feature_reconstruction.py 的口径一致
PRE_EVENT_FEATURE_NAMES: list[str] = [
    "shortage_urgency",
    "order_importance",
    "transit_delay",
    "external_event",
]


def extract_pre_event_features(record: dict[str, Any]) -> list[float]:
    """从已重建的事前特征记录中取值（0–100 分量分数）。"""
    return [float(record.get(name, 0.0)) for name in PRE_EVENT_FEATURE_NAMES]


@dataclass
class ModelResult:
    model_name: str
    accuracy: float
    f1_macro: float
    f1_weighted: float
    training_time_ms: float
    feature_importance: dict[str, float] | None
    model_notes: str
    decision_tree_text: str | None


@dataclass
class ModelComparisonReport:
    model_results: list[ModelResult]
    best_model_name: str
    best_f1_macro: float
    feature_names: list[str]
    evaluated_on: str


def extract_features(record: dict[str, Any]) -> list[float]:
    """Extract five numeric model features; missing or invalid values become 0.5."""
    covered_demand_rate = _float_or_neutral(record.get("covered_demand_rate"))
    delay_ratio = _ratio_or_neutral(
        record.get("actual_delay_hours"),
        record.get("predicted_delay_hours"),
    )
    cost_ratio = _ratio_or_neutral(record.get("actual_cost"), record.get("predicted_cost"))
    downtime_norm = _normalized_or_neutral(
        record.get("production_downtime_hours"),
        168.0,
    )
    human_rating_norm = _normalized_or_neutral(record.get("human_rating"), 5.0)
    return [
        covered_demand_rate,
        delay_ratio,
        cost_ratio,
        downtime_norm,
        human_rating_norm,
    ]


def compare_models(
    split: DatasetSplit,
    *,
    label_field: str = "outcome_status",
    random_state: int = 42,
    feature_extractor: Any = None,
    feature_names: list[str] | None = None,
) -> ModelComparisonReport:
    """
    Train six fixed model candidates and register the validation F1 winner.

    The validation split is used when present; otherwise training data is reused as
    a fallback evaluation set so small local demos still produce a comparable report.
    """
    if len(split.train) < 10:
        raise ValueError("训练数据不足，至少需要 10 条已标注记录")

    extractor = feature_extractor or extract_features
    names = list(feature_names or FEATURE_NAMES)

    eval_records = split.validation if split.validation else split.train
    evaluated_on = "validation" if split.validation else "train_fallback"
    classes = sorted(
        {
            str(record.get(label_field) or "")
            for record in [*split.train, *eval_records]
            if record.get(label_field)
        }
    )

    model_results: list[ModelResult] = [
        _evaluate_prior(split.train, eval_records, classes, label_field)
    ]

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.naive_bayes import GaussianNB
        from sklearn.svm import SVC
        from sklearn.tree import DecisionTreeClassifier, export_text
    except Exception:
        model_results.extend(_sklearn_unavailable_results())
    else:
        x_train = [extractor(record) for record in split.train]
        y_train = [str(record.get(label_field) or "") for record in split.train]
        x_eval = [extractor(record) for record in eval_records]
        y_eval = [str(record.get(label_field) or "") for record in eval_records]

        candidates = [
            (
                "LogisticRegression",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=500,
                    random_state=random_state,
                ),
                "Linear, interpretable baseline for feature-direction analysis.",
            ),
            (
                "DecisionTreeClassifier",
                DecisionTreeClassifier(
                    max_depth=4,
                    class_weight="balanced",
                    random_state=random_state,
                ),
                "Readable max_depth=4 rules for audit and business review.",
            ),
            (
                "RandomForestClassifier",
                RandomForestClassifier(
                    n_estimators=50,
                    max_depth=6,
                    class_weight="balanced",
                    random_state=random_state,
                ),
                "Ensemble model for stronger small-sample predictive performance.",
            ),
            (
                "GaussianNB",
                GaussianNB(),
                "Fast probabilistic baseline with simple feature assumptions.",
            ),
            (
                "SVM",
                SVC(
                    probability=True,
                    class_weight="balanced",
                    random_state=random_state,
                ),
                "Kernel max-margin classifier; probability via Platt scaling.",
            ),
        ]

        for name, model, notes in candidates:
            start = time.perf_counter()
            try:
                model.fit(x_train, y_train)
                predictions = model.predict(x_eval)
                elapsed_ms = (time.perf_counter() - start) * 1000
                feature_importance = _feature_importance_for(model, name, names)
                tree_text = (
                    export_text(model, feature_names=names)
                    if name == "DecisionTreeClassifier"
                    else None
                )
                model_results.append(
                    ModelResult(
                        model_name=name,
                        accuracy=round(float(accuracy_score(y_eval, predictions)), 6),
                        f1_macro=round(
                            float(
                                f1_score(
                                    y_eval,
                                    predictions,
                                    labels=classes,
                                    average="macro",
                                    zero_division=0,
                                )
                            ),
                            6,
                        ),
                        f1_weighted=round(
                            float(
                                f1_score(
                                    y_eval,
                                    predictions,
                                    labels=classes,
                                    average="weighted",
                                    zero_division=0,
                                )
                            ),
                            6,
                        ),
                        training_time_ms=round(elapsed_ms, 3),
                        feature_importance=feature_importance,
                        model_notes=notes,
                        decision_tree_text=tree_text,
                    )
                )
            except Exception as error:
                model_results.append(
                    ModelResult(
                        model_name=name,
                        accuracy=0.0,
                        f1_macro=0.0,
                        f1_weighted=0.0,
                        training_time_ms=round((time.perf_counter() - start) * 1000, 3),
                        feature_importance=None,
                        model_notes=f"训练失败：{error}",
                        decision_tree_text=None,
                    )
                )

    best = max(model_results, key=lambda result: result.f1_macro)
    report = ModelComparisonReport(
        model_results=model_results,
        best_model_name=best.model_name,
        best_f1_macro=best.f1_macro,
        feature_names=list(names),
        evaluated_on=evaluated_on,
    )
    _register_best_model(report)
    return report


def _evaluate_prior(
    train_records: list[dict[str, Any]],
    eval_records: list[dict[str, Any]],
    classes: list[str],
    label_field: str,
) -> ModelResult:
    try:
        from sklearn.metrics import accuracy_score, f1_score
    except Exception:
        accuracy_score = None
        f1_score = None

    start = time.perf_counter()
    classifier = train_prior_classifier(train_records, label_field=label_field)
    if not classifier.class_priors:
        prediction = ""
    else:
        prediction = max(classifier.class_priors, key=classifier.class_priors.get)
    y_true = [str(record.get(label_field) or "") for record in eval_records]
    predictions = [prediction for _ in eval_records]
    elapsed_ms = (time.perf_counter() - start) * 1000

    if not eval_records or accuracy_score is None or f1_score is None:
        accuracy = 0.0
        f1_macro = 0.0
        f1_weighted = 0.0
    else:
        accuracy = float(accuracy_score(y_true, predictions))
        f1_macro = float(
            f1_score(
                y_true,
                predictions,
                labels=classes,
                average="macro",
                zero_division=0,
            )
        )
        f1_weighted = float(
            f1_score(
                y_true,
                predictions,
                labels=classes,
                average="weighted",
                zero_division=0,
            )
        )

    return ModelResult(
        model_name="PriorClassifier",
        accuracy=round(accuracy, 6),
        f1_macro=round(f1_macro, 6),
        f1_weighted=round(f1_weighted, 6),
        training_time_ms=round(elapsed_ms, 3),
        feature_importance=None,
        model_notes="Zero-feature frequency baseline for comparison.",
        decision_tree_text=None,
    )


def _feature_importance_for(model: Any, model_name: str, names: list[str] | None = None) -> dict[str, float] | None:
    names = list(names or FEATURE_NAMES)
    if model_name == "LogisticRegression" and hasattr(model, "coef_"):
        raw = [abs(float(value)) for value in model.coef_.sum(axis=0)]
    elif hasattr(model, "feature_importances_"):
        raw = [float(value) for value in model.feature_importances_]
    else:
        return None

    total = sum(raw)
    if total <= 0:
        neutral = 1.0 / len(names)
        return {name: neutral for name in names}
    return {
        name: round(value / total, 6)
        for name, value in zip(names, raw, strict=True)
    }


def _sklearn_unavailable_results() -> list[ModelResult]:
    return [
        ModelResult(
            model_name=model_name,
            accuracy=0.0,
            f1_macro=0.0,
            f1_weighted=0.0,
            training_time_ms=0.0,
            feature_importance=None,
            model_notes="sklearn 未安装",
            decision_tree_text=None,
        )
        for model_name in [
            "LogisticRegression",
            "DecisionTreeClassifier",
            "RandomForestClassifier",
            "GaussianNB",
            "SVM",
        ]
    ]


def _register_best_model(report: ModelComparisonReport) -> None:
    best = max(report.model_results, key=lambda result: result.f1_macro)
    registry = ModelRegistry()
    try:
        record = registry.register(
            snapshot_version=(
                f"sklearn-{best.model_name.lower().replace(' ', '-').replace('_', '-')}-v1"
            ),
            metrics={
                "f1_macro": best.f1_macro,
                "accuracy": best.accuracy,
                "f1_weighted": best.f1_weighted,
            },
            notes=f"I06 model comparison, evaluated_on={report.evaluated_on}",
        )
        if registry.should_replace_stable(new_metrics=record.metrics, metric="f1_macro"):
            registry.promote_stable(record.version_id)
    except OSError:
        pass


def _float_or_neutral(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.5


def _ratio_or_neutral(numerator: Any, denominator: Any) -> float:
    try:
        return float(numerator) / max(float(denominator), 1.0)
    except (TypeError, ValueError):
        return 0.5


def _normalized_or_neutral(value: Any, denominator: float) -> float:
    try:
        return float(value) / denominator
    except (TypeError, ValueError):
        return 0.5
