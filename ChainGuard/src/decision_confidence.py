"""Outcome-calibrated confidence for decision recommendations.

The raw score deliberately uses only information available before execution.
Observed outcomes are used only to calibrate that score after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


BIN_COUNT = 5
SUCCESS_STATUS = "success"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _strategy_text(record: dict[str, Any]) -> str:
    return " ".join(
        str(record.get(key) or "")
        for key in ("selected_strategy", "final_strategy", "proposal", "proposal_title")
    ).lower()


def raw_confidence(record: dict[str, Any]) -> float:
    """Calculate a pre-outcome confidence from decision-time inputs only.

    Fixed operating scales make this score usable before a local history exists;
    calibration below is responsible for translating it to an observed rate.
    """
    score = 0.50
    strategy = _strategy_text(record)
    if any(token in strategy for token in ("双供应商", "备用", "替代", "安全库存", "分单")):
        score += 0.10
    if any(token in strategy for token in ("紧急", "全量空运", "延期")):
        score -= 0.10

    predicted_delay = record.get("predicted_delay_hours")
    try:
        delay = float(predicted_delay)
        score += 0.10 if delay <= 24 else (-0.10 if delay >= 72 else 0.0)
    except (TypeError, ValueError):
        pass

    predicted_cost = record.get("predicted_cost")
    try:
        cost = float(predicted_cost)
        score += 0.05 if cost <= 250_000 else (-0.10 if cost >= 750_000 else 0.0)
    except (TypeError, ValueError):
        pass
    return round(_clamp(score), 4)


def _bin_index(confidence: float) -> int:
    return min(BIN_COUNT - 1, max(0, int(_clamp(confidence) * BIN_COUNT)))


@dataclass(frozen=True)
class ReliabilityBin:
    confidence: float
    sample_size: int
    success_rate: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "confidence": round(self.confidence, 4),
            "sample_size": self.sample_size,
            "success_rate": round(self.success_rate, 4),
        }


class ConfidenceCalibrator:
    """Five-bucket isotonic calibrator with no third-party dependency."""

    def __init__(self) -> None:
        self._values: list[float] | None = None
        self.sample_size = 0

    def fit(self, records: Iterable[dict[str, Any]]) -> "ConfidenceCalibrator":
        counts = [0] * BIN_COUNT
        successes = [0] * BIN_COUNT
        for record in records:
            status = str(record.get("outcome_status") or "")
            if status not in {"success", "partial_success", "failed"}:
                continue
            index = _bin_index(raw_confidence(record))
            counts[index] += 1
            successes[index] += int(status == SUCCESS_STATUS)

        # Laplace smoothing makes a sparse bin conservative, then PAV forces
        # the learned mapping to be non-decreasing without changing bin edges.
        blocks: list[dict[str, Any]] = []
        for index, (count, success) in enumerate(zip(counts, successes)):
            value = (success + 1) / (count + 2)
            blocks.append({"start": index, "end": index, "weight": count + 2, "value": value})
            while len(blocks) > 1 and blocks[-2]["value"] > blocks[-1]["value"]:
                right = blocks.pop()
                left = blocks.pop()
                weight = left["weight"] + right["weight"]
                blocks.append({
                    "start": left["start"], "end": right["end"], "weight": weight,
                    "value": (left["value"] * left["weight"] + right["value"] * right["weight"]) / weight,
                })

        values = [0.5] * BIN_COUNT
        for block in blocks:
            for index in range(block["start"], block["end"] + 1):
                values[index] = round(float(block["value"]), 4)
        self._values = values
        self.sample_size = sum(counts)
        return self

    @property
    def fitted(self) -> bool:
        return self._values is not None and self.sample_size > 0

    def calibrate(self, raw: float) -> float:
        if not self.fitted:
            return round(_clamp(raw), 4)
        assert self._values is not None
        return self._values[_bin_index(raw)]

    def assess(self, decision: dict[str, Any]) -> dict[str, Any]:
        raw = raw_confidence(decision)
        calibrated = self.calibrate(raw)
        return {
            "raw_confidence": raw,
            "confidence": calibrated,
            "calibration_status": "calibrated" if self.fitted else "uncalibrated_no_history",
            "calibration_sample_size": self.sample_size,
            "recommended_disposition": "manual_review" if not self.fitted else "threshold_pending_governance",
        }


def reliability_bins(predictions: Iterable[tuple[float, int]]) -> list[ReliabilityBin]:
    grouped: dict[float, list[int]] = {}
    for confidence, success in predictions:
        grouped.setdefault(round(float(confidence), 4), []).append(int(success))
    return [
        ReliabilityBin(confidence=value, sample_size=len(outcomes), success_rate=sum(outcomes) / len(outcomes))
        for value, outcomes in sorted(grouped.items())
    ]


def brier_score(predictions: Iterable[tuple[float, int]]) -> float:
    pairs = list(predictions)
    if not pairs:
        return 0.0
    return round(sum((confidence - success) ** 2 for confidence, success in pairs) / len(pairs), 6)
