import dataclasses
import json
import random

import pytest

from src.model_comparison import compare_models, extract_features
from src.history_pipeline import HistoryPipeline
from src.training_dataset import DatasetSplit
from src.training_dataset import split_by_time


_LABELS = ["success", "partial_success", "failed"]


def _make_records(n: int = 30) -> list[dict]:
    """Generate n synthetic records with all required fields."""
    rng = random.Random(42)
    records = []
    for i in range(n):
        label = _LABELS[i % 3]
        records.append(
            {
                "covered_demand_rate": rng.uniform(0.3, 1.0),
                "predicted_delay_hours": rng.uniform(10, 100),
                "actual_delay_hours": rng.uniform(5, 120),
                "predicted_cost": rng.uniform(1000, 50000),
                "actual_cost": rng.uniform(800, 60000),
                "production_downtime_hours": rng.uniform(0, 48),
                "human_rating": rng.uniform(1, 5),
                "outcome_status": label,
            }
        )
    return records


def _make_split(n_train: int = 30, n_val: int = 10) -> DatasetSplit:
    records = _make_records(n_train + n_val)
    return DatasetSplit(
        train=records[:n_train],
        validation=records[n_train:],
        test=[],
    )


def test_compare_models_returns_six_results():
    report = compare_models(_make_split())

    assert len(report.model_results) == 6


def test_best_model_has_highest_f1_macro():
    report = compare_models(_make_split())

    assert report.best_f1_macro == max(r.f1_macro for r in report.model_results)


def test_report_json_serializable():
    report = compare_models(_make_split())

    json.dumps(dataclasses.asdict(report))


def test_prior_classifier_always_included():
    report = compare_models(_make_split())
    names = [r.model_name for r in report.model_results]

    assert "PriorClassifier" in names


def test_svm_included_and_gaussian_nb_retained():
    report = compare_models(_make_split())
    names = [r.model_name for r in report.model_results]

    assert "SVM" in names
    assert "GaussianNB" in names


def test_empty_train_raises_value_error():
    split = DatasetSplit(train=[], validation=[], test=[])

    with pytest.raises(ValueError):
        compare_models(split)


def test_random_forest_has_feature_importance():
    report = compare_models(_make_split())
    rf = next(r for r in report.model_results if "RandomForest" in r.model_name)

    assert rf.feature_importance is not None
    assert sum(rf.feature_importance.values()) == pytest.approx(1.0, abs=0.01)


def test_extract_features_missing_fields_fills_neutral():
    result = extract_features({})

    assert result == [0.5, 0.5, 0.5, 0.5, 0.5]


def test_best_model_beats_prior_on_real_data():
    report = compare_models(_real_history_split())
    prior = next(r for r in report.model_results if r.model_name == "PriorClassifier")
    best = next(r for r in report.model_results if r.model_name == report.best_model_name)

    assert report.best_model_name != "PriorClassifier"
    assert best.f1_macro >= prior.f1_macro + 0.10
    assert best.accuracy >= prior.accuracy


def test_best_model_not_overfit():
    report = compare_models(_real_history_split())

    assert report.best_f1_macro <= 0.92


def _real_history_split() -> DatasetSplit:
    records = HistoryPipeline()._load_valid_records_before_cutoff("2026-12-31")
    return split_by_time(
        records,
        time_field="created_at",
        train_end="2026-03-15",
        validation_end="2026-04-01",
    )
