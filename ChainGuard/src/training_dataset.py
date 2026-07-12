from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class DatasetSplit:
    train: list[dict[str, Any]]
    validation: list[dict[str, Any]]
    test: list[dict[str, Any]]

    @property
    def total(self) -> int:
        return len(self.train) + len(self.validation) + len(self.test)

    def summary(self) -> dict[str, Any]:
        return {
            "train_count": len(self.train),
            "validation_count": len(self.validation),
            "test_count": len(self.test),
            "total": self.total,
            "train_time_range": _time_range(self.train),
            "validation_time_range": _time_range(self.validation),
            "test_time_range": _time_range(self.test),
        }

    def evaluate_prior(self, classifier: PriorClassifier) -> dict[str, float]:
        """Compute majority-class accuracy on the test split."""
        if classifier.total == 0 or not classifier.class_priors:
            return {"accuracy": 0.0}
        if not self.test:
            return {"accuracy": 0.0}

        majority_label = max(
            classifier.class_priors,
            key=classifier.class_priors.get,
        )
        correct = sum(
            1
            for record in self.test
            if str(record.get(classifier.label_field) or "") == majority_label
        )
        return {"accuracy": round(correct / len(self.test), 6)}


@dataclass
class PriorClassifier:
    label_field: str
    class_priors: dict[str, float]
    class_counts: dict[str, int]
    total: int
    trained_on: str

    def predict_proba(self, record: dict[str, Any]) -> dict[str, float]:
        """Return class prior probabilities for this label-independent baseline."""
        return dict(self.class_priors)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for model registration."""
        return asdict(self)


def train_prior_classifier(
    records: list[dict[str, Any]],
    *,
    label_field: str,
) -> PriorClassifier:
    """Train a label-frequency prior classifier on the given records."""
    counts: dict[str, int] = {}
    for record in records:
        if label_field not in record:
            continue
        label = str(record.get(label_field) or "")
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1

    total = sum(counts.values())
    priors = {
        label: round(count / total, 6)
        for label, count in counts.items()
    } if total else {}

    return PriorClassifier(
        label_field=label_field,
        class_priors=priors,
        class_counts=counts,
        total=total,
        trained_on=datetime.now(timezone.utc).isoformat(),
    )


def split_by_time(
    records: list[dict[str, Any]],
    *,
    time_field: str,
    train_end: str,
    validation_end: str,
) -> DatasetSplit:
    if validation_end <= train_end:
        raise ValueError("validation_end must be greater than train_end")

    train: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []

    for record in records:
        timestamp = str(record.get(time_field, ""))
        if timestamp < train_end:
            train.append(record)
        elif timestamp < validation_end:
            validation.append(record)
        else:
            test.append(record)

    return DatasetSplit(train=train, validation=validation, test=test)


def compute_class_weights(
    records: list[dict[str, Any]],
    *,
    label_field: str,
) -> dict[str, float]:
    counts: dict[str, int] = {}
    for record in records:
        if label_field not in record:
            continue
        label = str(record.get(label_field) or "")
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1

    if not counts:
        return {}

    total = sum(counts.values())
    n_classes = len(counts)
    return {
        label: round(total / (n_classes * count), 6)
        for label, count in counts.items()
    }


def _time_range(records: list[dict[str, Any]]) -> dict[str, str | None]:
    timestamps = [
        str(record.get("created_at"))
        for record in records
        if record.get("created_at")
    ]
    if not timestamps:
        return {"min": None, "max": None}
    return {"min": min(timestamps), "max": max(timestamps)}
