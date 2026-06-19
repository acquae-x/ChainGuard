import shutil
import uuid
from pathlib import Path

import pytest

from src.learning import (
    build_experience_cards_from_history,
    card_from_historical_record,
)


@pytest.fixture
def tmp_path():
    base = Path(".tmp_test_experience_pipeline")
    target = base / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=False)
    try:
        yield target
    finally:
        shutil.rmtree(target, ignore_errors=True)
        try:
            base.rmdir()
        except OSError:
            pass


def make_record(case_id: str = "CASE-000001", **overrides):
    record = {
        "case_id": case_id,
        "event_id": "EVT-000001",
        "scenario": "台风天气-苏州-001",
        "selected_strategy": "铁路替代+延期交付",
        "outcome_status": "success",
        "human_rating": "4",
        "lessons_learned": "高优先级订单应提前锁定铁路仓位",
        "covered_demand_rate": "0.82",
        "actual_delay_hours": "18",
        "actual_cost": "125000",
    }
    record.update(overrides)
    return record


def test_card_from_historical_record_field_mapping():
    card = card_from_historical_record(make_record())

    assert card["case_id"] == "CASE-000001"
    assert card["scenario"] == "台风天气-苏州-001"
    assert card["recommended_pattern"] == "铁路替代+延期交付"
    assert card["improvement_strategy"] == "高优先级订单应提前锁定铁路仓位"
    assert card["confidence_score"] == 0.8


@pytest.mark.parametrize(
    ("human_rating", "expected"),
    [
        ("5", 1.0),
        ("1", pytest.approx(0.2)),
        ("3", pytest.approx(0.6)),
    ],
)
def test_card_confidence_score_normalization(human_rating, expected):
    card = card_from_historical_record(make_record(human_rating=human_rating))

    assert card["confidence_score"] == expected


def test_card_failed_reason_outcome_failed():
    failed_card = card_from_historical_record(
        make_record(
            outcome_status="failed",
            lessons_learned="备用供应商容量不足",
        )
    )
    success_card = card_from_historical_record(make_record(outcome_status="success"))

    assert "备用供应商容量不足" in failed_card["failed_reason"]
    assert success_card["failed_reason"] == ""


def test_build_cards_deduplication(tmp_path):
    path = tmp_path / "experience_cards.json"
    records = [make_record("CASE-000001"), make_record("CASE-000002")]

    first = build_experience_cards_from_history(records, path=path)
    second = build_experience_cards_from_history(records, path=path, overwrite=False)

    assert first["added"] == 2
    assert first["skipped"] == 0
    assert second["added"] == 0
    assert second["skipped"] == 2
    assert second["total_after"] == 2


def test_build_cards_added_count(tmp_path):
    path = tmp_path / "experience_cards.json"
    records = [make_record(f"CASE-{index:06d}") for index in range(1, 6)]

    result = build_experience_cards_from_history(records, path=path)

    assert result["added"] == 5
    assert result["skipped"] == 0
    assert result["total_after"] == 5


def test_card_from_historical_input_changes_output():
    first = card_from_historical_record(
        make_record("CASE-000001", scenario="台风天气-苏州-001")
    )
    second = card_from_historical_record(
        make_record("CASE-000002", scenario="海关延误-上海-002")
    )

    assert first["scenario"] != second["scenario"]
