import json
import sqlite3
import tempfile
import uuid
from pathlib import Path

from src.history_pipeline import HistoryPipeline
from src.model_registry import ModelRegistry


RUNTIME_TMP = Path(tempfile.gettempdir()) / "chainguard_t13_tests"


def _runtime_path(name: str) -> Path:
    RUNTIME_TMP.mkdir(parents=True, exist_ok=True)
    path = Path(name)
    return RUNTIME_TMP / f"{path.stem}_{uuid.uuid4().hex}{path.suffix}"


def test_ingest_batch_matches_oneshot():
    records = [_record(index) for index in range(5)]
    db_one = _create_db(records)
    db_two = _create_db(records)

    small_batch = HistoryPipeline(
        db_path=db_one,
        state_path=_runtime_path("state.json"),
    ).ingest_incremental(batch_size=1)
    large_batch = HistoryPipeline(
        db_path=db_two,
        state_path=_runtime_path("state.json"),
    ).ingest_incremental(batch_size=9999)

    assert small_batch.ingested_count == large_batch.ingested_count == 5
    assert small_batch.rejected_count == large_batch.rejected_count == 0


def test_ingest_idempotent():
    db_path = _create_db([_record(index) for index in range(3)])
    state_path = _runtime_path("state.json")
    pipeline = HistoryPipeline(db_path=db_path, state_path=state_path)

    first = pipeline.ingest_incremental(batch_size=2)
    second = pipeline.ingest_incremental(batch_size=2)

    assert first.ingested_count == 3
    assert second.ingested_count == 0
    assert second.new_watermark == first.new_watermark


def test_watermark_resume_no_gap():
    db_path = _create_db([_record(0), _record(1)])
    state_path = _runtime_path("state.json")
    pipeline = HistoryPipeline(db_path=db_path, state_path=state_path)
    first = pipeline.ingest_incremental(batch_size=1)

    _append_records(db_path, [_record(2), _record(3)])
    second = pipeline.ingest_incremental(batch_size=1)

    assert first.ingested_count + second.ingested_count == 4
    assert pipeline.load_watermark() == second.new_watermark


def test_bad_record_quarantined():
    records = [
        _record(0),
        {**_record(1), "covered_demand_rate": 1.5},
        {**_record(2), "actual_cost": -1.0},
        {**_record(3), "case_id": ""},
    ]
    db_path = _create_db(records)

    report = HistoryPipeline(
        db_path=db_path,
        state_path=_runtime_path("state.json"),
    ).ingest_incremental(batch_size=2)

    assert report.ingested_count == 1
    assert report.rejected_count == 3
    assert report.ingested_count + report.rejected_count == 4
    assert report.rejected_reasons


def test_snapshot_cutoff_respected():
    db_path = _create_db([_record(index) for index in range(5)])
    pipeline = HistoryPipeline(
        db_path=db_path,
        state_path=_runtime_path("state.json"),
    )

    snapshot = pipeline.build_training_snapshot(
        cutoff_time="2026-01-03T00:00:00+00:00",
        snapshot_version="v1",
        train_end="2026-01-02T00:00:00+00:00",
        validation_end="2026-01-03T00:00:00+00:00",
    )

    assert snapshot.record_count == 3


def test_snapshot_has_required_fields():
    db_path = _create_db([_record(index) for index in range(4)])
    pipeline = HistoryPipeline(
        db_path=db_path,
        state_path=_runtime_path("state.json"),
    )

    snapshot = pipeline.build_training_snapshot(
        cutoff_time="2026-01-04T00:00:00+00:00",
        snapshot_version="snapshot:v1",
        train_end="2026-01-02T00:00:00+00:00",
        validation_end="2026-01-03T00:00:00+00:00",
    )
    payload = snapshot.to_dict()

    assert {
        "snapshot_version",
        "cutoff_time",
        "record_count",
        "train_count",
        "validation_count",
        "test_count",
        "outcome_class_distribution",
        "saved_to",
    } <= set(payload)
    assert Path(snapshot.saved_to).exists()


def test_model_registry_no_replace_on_degradation():
    registry = ModelRegistry(_runtime_path("registry.json"))
    first = registry.register("snapshot-v1", {"accuracy": 0.9})
    registry.promote_stable(first.version_id)

    assert registry.should_replace_stable({"accuracy": 0.8}) is False
    assert registry.should_replace_stable({"accuracy": 0.95}) is True


def test_model_registry_rollback():
    registry = ModelRegistry(_runtime_path("registry.json"))
    first = registry.register("snapshot-v1", {"accuracy": 0.8})
    second = registry.register("snapshot-v2", {"accuracy": 0.9})
    registry.promote_stable(first.version_id)
    registry.promote_stable(second.version_id)

    rolled_back = registry.rollback()

    assert rolled_back is not None
    assert rolled_back.version_id == first.version_id
    assert registry.get_stable().version_id == first.version_id


def test_model_registry_skips_corrupted_lines():
    path = _runtime_path("registry.json")
    valid = {
        "version_id": "v1",
        "snapshot_version": "snapshot-v1",
        "metrics": {"accuracy": 0.8},
        "is_stable": True,
        "registered_at": "2026-01-01T00:00:00+00:00",
        "notes": "",
    }
    path.write_text(
        json.dumps(valid, ensure_ascii=False) + "\nnot-json\n",
        encoding="utf-8",
    )

    records = ModelRegistry(path).load_all()

    assert len(records) == 1
    assert records[0].version_id == "v1"


def _create_db(records: list[dict]) -> Path:
    path = _runtime_path("history.db")
    with sqlite3.connect(path) as connection:
        _create_table(connection)
        _insert_records(connection, records)
    return path


def _append_records(path: Path, records: list[dict]) -> None:
    with sqlite3.connect(path) as connection:
        _insert_records(connection, records)


def _create_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE historical_decisions (
            case_id TEXT,
            event_id TEXT,
            scenario TEXT,
            selected_strategy TEXT,
            predicted_delay_hours INTEGER,
            actual_delay_hours INTEGER,
            predicted_cost REAL,
            actual_cost REAL,
            covered_demand_rate REAL,
            production_downtime_hours INTEGER,
            lost_orders INTEGER,
            customer_complaints INTEGER,
            outcome_status TEXT,
            human_rating INTEGER,
            lessons_learned TEXT,
            model_version TEXT,
            parameter_version TEXT,
            created_at TEXT
        )
        """
    )


def _insert_records(connection: sqlite3.Connection, records: list[dict]) -> None:
    connection.executemany(
        """
        INSERT INTO historical_decisions VALUES (
            :case_id,
            :event_id,
            :scenario,
            :selected_strategy,
            :predicted_delay_hours,
            :actual_delay_hours,
            :predicted_cost,
            :actual_cost,
            :covered_demand_rate,
            :production_downtime_hours,
            :lost_orders,
            :customer_complaints,
            :outcome_status,
            :human_rating,
            :lessons_learned,
            :model_version,
            :parameter_version,
            :created_at
        )
        """,
        records,
    )
    connection.commit()


def _record(index: int) -> dict:
    return {
        "case_id": f"CASE-{index:03d}",
        "event_id": f"EVT-{index:03d}",
        "scenario": "typhoon delay",
        "selected_strategy": "backup_supplier",
        "predicted_delay_hours": 24,
        "actual_delay_hours": 20,
        "predicted_cost": 1000.0,
        "actual_cost": 980.0,
        "covered_demand_rate": 0.9,
        "production_downtime_hours": 0,
        "lost_orders": 0,
        "customer_complaints": 0,
        "outcome_status": "failed" if index == 0 else "success",
        "human_rating": 4,
        "lessons_learned": "use backup supplier",
        "model_version": "v1",
        "parameter_version": "p1",
        "created_at": f"2026-01-{index + 1:02d}T00:00:00+00:00",
    }
