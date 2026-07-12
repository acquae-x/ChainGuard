from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.db import get_connection
from src.training_dataset import split_by_time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = "demo_assets/enterprise/database/chainguard_enterprise_demo.db"
DEFAULT_STATE_PATH = "data/pipeline_state.json"


@dataclass
class IngestionReport:
    source: str
    since_watermark: str | None
    new_watermark: str
    ingested_count: int
    rejected_count: int
    rejected_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrainingSnapshot:
    snapshot_version: str
    cutoff_time: str
    record_count: int
    train_count: int
    validation_count: int
    test_count: int
    outcome_class_distribution: dict[str, int]
    saved_to: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HistoryPipeline:
    def __init__(
        self,
        db_path: str | Path | None = None,
        state_path: str | Path | None = None,
        *,
        tenant_id: str = "default",
    ) -> None:
        self.db_path = _resolve_path(db_path or DEFAULT_DB_PATH)
        self.state_path = _resolve_path(state_path or DEFAULT_STATE_PATH)
        self.tenant_id = tenant_id

    def ingest_incremental(
        self,
        source: str = "historical_decisions",
        *,
        since_watermark: str | None = None,
        batch_size: int = 100,
    ) -> IngestionReport:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if not self.db_path.exists():
            raise FileNotFoundError(self.db_path)

        effective_watermark = (
            since_watermark
            if since_watermark is not None
            else self.load_watermark()
        )
        ingested_count = 0
        rejected_count = 0
        rejected_reasons: list[str] = []
        seen_case_ids: set[str] = set()
        latest_watermark = effective_watermark or ""
        cursor_created_at = effective_watermark or ""
        cursor_case_id: str | None = None

        with get_connection(f"sqlite:///{self.db_path}", tenant_id=self.tenant_id) as connection:
            while True:
                rows = self._fetch_batch(
                    connection,
                    source,
                    cursor_created_at,
                    cursor_case_id,
                    batch_size,
                )
                if not rows:
                    break

                for row in rows:
                    record = dict(row)
                    created_at = str(record.get("created_at") or "")
                    case_id = str(record.get("case_id") or "")
                    cursor_created_at = created_at
                    cursor_case_id = case_id
                    if created_at > latest_watermark:
                        latest_watermark = created_at

                    reason = _quality_issue(record)
                    if not reason and case_id in seen_case_ids:
                        reason = f"duplicate case_id: {case_id}"
                    if reason:
                        rejected_count += 1
                        if len(rejected_reasons) < 10:
                            rejected_reasons.append(reason)
                        continue

                    seen_case_ids.add(case_id)
                    ingested_count += 1

        if latest_watermark:
            self.save_watermark(latest_watermark)

        return IngestionReport(
            source=source,
            since_watermark=effective_watermark,
            new_watermark=latest_watermark,
            ingested_count=ingested_count,
            rejected_count=rejected_count,
            rejected_reasons=rejected_reasons,
        )

    def build_training_snapshot(
        self,
        *,
        cutoff_time: str,
        snapshot_version: str,
        train_end: str,
        validation_end: str,
    ) -> TrainingSnapshot:
        if cutoff_time < train_end:
            raise ValueError("cutoff_time must be greater than or equal to train_end")
        if validation_end <= train_end:
            raise ValueError("validation_end must be greater than train_end")
        if not self.db_path.exists():
            raise FileNotFoundError(self.db_path)

        records = self._load_valid_records_before_cutoff(cutoff_time)
        split = split_by_time(
            records,
            time_field="created_at",
            train_end=train_end,
            validation_end=validation_end,
        )
        distribution: dict[str, int] = {}
        for record in records:
            label = str(record.get("outcome_status") or "unknown")
            distribution[label] = distribution.get(label, 0) + 1

        snapshot_dir = self._snapshot_dir()
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{_safe_filename(snapshot_version)}.json"
        snapshot = TrainingSnapshot(
            snapshot_version=snapshot_version,
            cutoff_time=cutoff_time,
            record_count=len(records),
            train_count=len(split.train),
            validation_count=len(split.validation),
            test_count=len(split.test),
            outcome_class_distribution=distribution,
            saved_to=str(snapshot_path),
        )
        snapshot_path.write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return snapshot

    def load_outcomes(self) -> list[dict[str, Any]]:
        """Load all quality-validated historical decision records for calibration.

        Wraps _load_valid_records_before_cutoff with a far-future cutoff so all
        available records are returned. Quality filtering is applied by the
        underlying method.
        """
        return self._load_valid_records_before_cutoff("9999-12-31T23:59:59")

    def load_watermark(self) -> str | None:
        if not self.state_path.exists():
            return None
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        watermark = payload.get("watermark")
        return str(watermark) if watermark else None

    def save_watermark(self, watermark: str) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "watermark": watermark,
            "source": "historical_decisions",
        }
        tmp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.state_path)

    def _fetch_batch(
        self,
        connection: sqlite3.Connection,
        source: str,
        cursor_created_at: str,
        cursor_case_id: str | None,
        batch_size: int,
    ) -> list[sqlite3.Row]:
        if cursor_case_id is None:
            query = (
                f"SELECT * FROM {source} WHERE created_at > ? "
                "ORDER BY created_at, case_id LIMIT ?"
            )
            parameters: tuple[Any, ...] = (cursor_created_at, batch_size)
        else:
            query = (
                f"SELECT * FROM {source} "
                "WHERE created_at > ? OR (created_at = ? AND case_id > ?) "
                "ORDER BY created_at, case_id LIMIT ?"
            )
            parameters = (
                cursor_created_at,
                cursor_created_at,
                cursor_case_id,
                batch_size,
            )
        return list(connection.execute(query, parameters))

    def _load_valid_records_before_cutoff(self, cutoff_time: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_case_ids: set[str] = set()
        with get_connection(f"sqlite:///{self.db_path}", tenant_id=self.tenant_id) as connection:
            rows = connection.execute(
                "SELECT * FROM historical_decisions "
                "WHERE created_at <= ? ORDER BY created_at, case_id",
                (cutoff_time,),
            )
            for row in rows:
                record = dict(row)
                case_id = str(record.get("case_id") or "")
                if _quality_issue(record) or case_id in seen_case_ids:
                    continue
                seen_case_ids.add(case_id)
                records.append(record)
        return records

    def _snapshot_dir(self) -> Path:
        if self.state_path == PROJECT_ROOT / DEFAULT_STATE_PATH:
            return PROJECT_ROOT / "data" / "snapshots"
        return self.state_path.parent / "snapshots"


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    return target if target.is_absolute() else PROJECT_ROOT / target


def _quality_issue(record: dict[str, Any]) -> str:
    case_id = str(record.get("case_id") or "").strip()
    if not case_id:
        return "case_id is empty"
    try:
        covered_demand_rate = float(record.get("covered_demand_rate"))
    except (TypeError, ValueError):
        return f"invalid covered_demand_rate for {case_id}"
    if not 0.0 <= covered_demand_rate <= 1.0:
        return f"covered_demand_rate out of range for {case_id}"

    try:
        human_rating = int(record.get("human_rating"))
    except (TypeError, ValueError):
        return f"invalid human_rating for {case_id}"
    if not 1 <= human_rating <= 5:
        return f"human_rating out of range for {case_id}"

    try:
        actual_cost = float(record.get("actual_cost"))
    except (TypeError, ValueError):
        return f"invalid actual_cost for {case_id}"
    if actual_cost < 0:
        return f"actual_cost below zero for {case_id}"

    return ""


def _safe_filename(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in value
    )
