from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import tracemalloc
import uuid
from pathlib import Path

from src.history_pipeline import HistoryPipeline


def test_history_pipeline_scale_batch_ingest():
    total_records = int(os.environ.get("SCALE_TEST_N", "100000"))
    root = Path(tempfile.gettempdir()) / "chainguard_t13_scale" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "history.db"
    state_path = root / "pipeline_state.json"
    _create_history_db(db_path, total_records)

    pipeline = HistoryPipeline(db_path=db_path, state_path=state_path)
    tracemalloc.start()
    start = time.perf_counter()
    report = pipeline.ingest_incremental(batch_size=1000)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    throughput = total_records / max(elapsed, 0.001)
    peak_mb = peak / 1024 / 1024
    print(
        f"records={total_records} elapsed={elapsed:.2f}s "
        f"throughput={throughput:.0f}/s peak_mb={peak_mb:.1f}"
    )

    assert report.ingested_count + report.rejected_count == total_records
    assert peak_mb < 200
    assert throughput > 5000


def _create_history_db(path: Path, total_records: int) -> None:
    with sqlite3.connect(path) as connection:
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
        batch: list[tuple[object, ...]] = []
        for index in range(total_records):
            batch.append(_record(index))
            if len(batch) >= 5000:
                connection.executemany(_INSERT_SQL, batch)
                batch.clear()
        if batch:
            connection.executemany(_INSERT_SQL, batch)
        connection.commit()


def _record(index: int) -> tuple[object, ...]:
    day = (index % 28) + 1
    hour = (index // 28) % 24
    status = "failed" if index % 20 == 0 else "success"
    return (
        f"CASE-{index:07d}",
        f"EVT-{index % 1000:06d}",
        "synthetic scale scenario",
        "backup_supplier",
        24,
        20,
        1000.0,
        980.0,
        0.9,
        0,
        0,
        0,
        status,
        4,
        "scale benchmark",
        "v1",
        "p1",
        f"2026-01-{day:02d}T{hour:02d}:00:00+00:00",
    )


_INSERT_SQL = """
    INSERT INTO historical_decisions VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    )
"""
