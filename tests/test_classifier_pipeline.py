from pathlib import Path
import uuid

import pytest

from src.model_registry import ModelRegistry
from src.training_dataset import split_by_time, train_prior_classifier


RUNTIME_TMP = Path(__file__).resolve().parent / "_runtime_tmp"


@pytest.fixture
def tmp_path():
    path = RUNTIME_TMP / f"classifier_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_record(case_id, outcome_status, created_at):
    return {
        "case_id": case_id,
        "outcome_status": outcome_status,
        "created_at": created_at,
    }


def make_records(labels):
    return [
        make_record(
            f"CASE-{index:06d}",
            label,
            f"2026-01-{index:02d}",
        )
        for index, label in enumerate(labels, start=1)
    ]


def run_prior_pipeline(records, *, train_end="2026-01-15", validation_end="2026-01-17"):
    split = split_by_time(
        records,
        time_field="created_at",
        train_end=train_end,
        validation_end=validation_end,
    )
    clf = train_prior_classifier(split.train, label_field="outcome_status")
    return split, clf, split.evaluate_prior(clf)


def balanced_records():
    return make_records(["success"] * 15 + ["failed"] * 5)


def test_prior_pipeline_produces_valid_accuracy():
    _, _, metrics = run_prior_pipeline(balanced_records())

    assert 0.0 <= metrics["accuracy"] <= 1.0


def test_registry_stable_after_pipeline(tmp_path):
    _, _, metrics = run_prior_pipeline(balanced_records())
    registry = ModelRegistry(tmp_path / "model_registry.json")

    record = registry.register(snapshot_version="prior-v1", metrics=metrics)
    registry.promote_stable(record.version_id)
    stable = registry.get_stable()

    assert stable is not None
    assert stable.metrics["accuracy"] == pytest.approx(metrics["accuracy"])


def test_accuracy_matches_majority_class_rate():
    records = make_records(["success"] * 10 + ["validation"] * 2 + ["success"] * 3)

    _, _, metrics = run_prior_pipeline(
        records,
        train_end="2026-01-11",
        validation_end="2026-01-13",
    )

    assert metrics["accuracy"] == pytest.approx(1.0)


def test_input_change_changes_accuracy():
    first_records = make_records(["success"] * 10 + ["validation"] * 2 + ["success"] * 3)
    second_records = make_records(["success"] * 10 + ["validation"] * 2 + ["failed"] * 3)

    _, _, first_metrics = run_prior_pipeline(
        first_records,
        train_end="2026-01-11",
        validation_end="2026-01-13",
    )
    _, _, second_metrics = run_prior_pipeline(
        second_records,
        train_end="2026-01-11",
        validation_end="2026-01-13",
    )

    assert first_metrics["accuracy"] != second_metrics["accuracy"]


def test_empty_train_returns_zero_accuracy():
    records = make_records(["success", "failed", "success"])
    split = split_by_time(
        records,
        time_field="created_at",
        train_end="2025-12-31",
        validation_end="2026-01-02",
    )

    clf = train_prior_classifier(split.train, label_field="outcome_status")
    metrics = split.evaluate_prior(clf)

    assert split.train == []
    assert clf.total == 0
    assert metrics == {"accuracy": 0.0}


def test_registry_accuracy_key_present(tmp_path):
    _, _, metrics = run_prior_pipeline(balanced_records())
    registry = ModelRegistry(tmp_path / "model_registry.json")

    record = registry.register(snapshot_version="prior-v1", metrics=metrics)
    registry.promote_stable(record.version_id)

    assert "accuracy" in registry.get_stable().metrics
    assert registry.should_replace_stable({"accuracy": 0.99}, metric="accuracy") is True


def test_empty_test_returns_zero_accuracy():
    records = make_records(["success"] * 5)

    _, clf, metrics = run_prior_pipeline(
        records,
        train_end="2026-01-06",
        validation_end="2026-01-07",
    )

    assert clf.total == 5
    assert metrics == {"accuracy": 0.0}
