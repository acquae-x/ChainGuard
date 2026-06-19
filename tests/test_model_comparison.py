import dataclasses
import json
import random

import pytest

from src.model_comparison import compare_models, extract_features
from src.training_dataset import DatasetSplit


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


def test_compare_models_returns_five_results():
    report = compare_models(_make_split())

    assert len(report.model_results) == 5


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
