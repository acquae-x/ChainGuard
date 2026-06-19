import json

import pytest

from src.training_dataset import (
    DatasetSplit,
    compute_class_weights,
    split_by_time,
    train_prior_classifier,
)


def test_split_by_time_no_leakage():
    split = split_by_time(
        _records(),
        time_field="created_at",
        train_end="2026-02-01T00:00:00+00:00",
        validation_end="2026-03-01T00:00:00+00:00",
    )

    assert all(
        record["created_at"] < "2026-02-01T00:00:00+00:00"
        for record in split.train
    )
    assert all(
        "2026-02-01T00:00:00+00:00"
        <= record["created_at"]
        < "2026-03-01T00:00:00+00:00"
        for record in split.validation
    )


def test_split_by_time_all_records_assigned():
    records = _records()

    split = split_by_time(
        records,
        time_field="created_at",
        train_end="2026-02-01T00:00:00+00:00",
        validation_end="2026-03-01T00:00:00+00:00",
    )

    assert split.total == len(records)
    assert split.summary()["total"] == len(records)


def test_class_weights_rare_event_higher():
    records = [
        {"outcome_status": "success"},
        {"outcome_status": "success"},
        {"outcome_status": "success"},
        {"outcome_status": "failed"},
    ]

    weights = compute_class_weights(records, label_field="outcome_status")

    assert weights["failed"] > weights["success"]


def test_split_by_time_empty_records():
    split = split_by_time(
        [],
        time_field="created_at",
        train_end="2026-02-01T00:00:00+00:00",
        validation_end="2026-03-01T00:00:00+00:00",
    )

    assert split.total == 0


def test_class_weights_empty_records():
    assert compute_class_weights([], label_field="outcome_status") == {}


def test_train_prior_classifier_counts():
    records = (
        [{"outcome_status": "success"} for _ in range(7)]
        + [{"outcome_status": "failed"} for _ in range(3)]
    )

    classifier = train_prior_classifier(records, label_field="outcome_status")

    assert classifier.total == 10
    assert classifier.class_counts == {"success": 7, "failed": 3}
    assert classifier.class_priors["success"] == pytest.approx(0.7, abs=0.01)


def test_train_prior_classifier_empty():
    classifier = train_prior_classifier([], label_field="outcome_status")

    assert classifier.total == 0
    assert classifier.class_priors == {}
    assert classifier.class_counts == {}


def test_evaluate_prior_majority_class():
    train = (
        [{"outcome_status": "success"} for _ in range(7)]
        + [{"outcome_status": "failed"} for _ in range(3)]
    )
    test = [{"outcome_status": "success"} for _ in range(5)]
    split = DatasetSplit(train=train, validation=[], test=test)
    classifier = train_prior_classifier(train, label_field="outcome_status")

    assert split.evaluate_prior(classifier) == {"accuracy": 1.0}


def test_prior_to_dict_serializable():
    classifier = train_prior_classifier(
        [{"outcome_status": "success"}],
        label_field="outcome_status",
    )

    json.dumps(classifier.to_dict(), ensure_ascii=False)


def test_evaluate_prior_empty_classifier():
    classifier = train_prior_classifier([], label_field="outcome_status")
    split = DatasetSplit(
        train=[],
        validation=[],
        test=[{"outcome_status": "success"}],
    )

    assert split.evaluate_prior(classifier) == {"accuracy": 0.0}


def test_evaluate_prior_empty_test_set():
    train = [{"outcome_status": "success"}]
    classifier = train_prior_classifier(train, label_field="outcome_status")
    split = DatasetSplit(train=train, validation=[], test=[])

    assert split.evaluate_prior(classifier) == {"accuracy": 0.0}


def _records():
    return [
        {"case_id": "A", "created_at": "2026-01-01T00:00:00+00:00"},
        {"case_id": "B", "created_at": "2026-02-01T00:00:00+00:00"},
        {"case_id": "C", "created_at": "2026-03-01T00:00:00+00:00"},
    ]
