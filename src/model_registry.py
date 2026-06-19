from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = "data/model_registry.json"


@dataclass
class VersionRecord:
    version_id: str
    snapshot_version: str
    metrics: dict[str, float]
    is_stable: bool
    registered_at: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelRegistry:
    def __init__(self, path: str | Path = DEFAULT_REGISTRY_PATH) -> None:
        target = Path(path)
        self.path = target if target.is_absolute() else PROJECT_ROOT / target

    def register(
        self,
        snapshot_version: str,
        metrics: dict[str, float],
        *,
        notes: str = "",
    ) -> VersionRecord:
        record = VersionRecord(
            version_id=uuid.uuid4().hex,
            snapshot_version=snapshot_version,
            metrics={key: float(value) for key, value in metrics.items()},
            is_stable=False,
            registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            notes=notes,
        )
        records = self.load_all()
        records.append(record)
        self._write_all(records)
        return record

    def promote_stable(self, version_id: str) -> None:
        records = self.load_all()
        if not any(record.version_id == version_id for record in records):
            raise KeyError(version_id)

        for record in records:
            record.is_stable = record.version_id == version_id
        self._write_all(records)

    def get_stable(self) -> VersionRecord | None:
        stable_records = [
            record
            for record in self.load_all()
            if record.is_stable
        ]
        return stable_records[-1] if stable_records else None

    def should_replace_stable(
        self,
        new_metrics: dict[str, float],
        metric: str = "accuracy",
    ) -> bool:
        stable = self.get_stable()
        if stable is None:
            return metric in new_metrics
        if metric not in new_metrics or metric not in stable.metrics:
            return False
        return float(new_metrics[metric]) > float(stable.metrics[metric])

    def rollback(self) -> VersionRecord | None:
        records = self.load_all()
        current_index = next(
            (
                index
                for index in range(len(records) - 1, -1, -1)
                if records[index].is_stable
            ),
            None,
        )
        if current_index is None:
            return None

        previous_records = records[:current_index]
        if not previous_records:
            return None

        previous = previous_records[-1]
        for record in records:
            record.is_stable = record.version_id == previous.version_id
        self._write_all(records)
        return previous

    def load_all(self) -> list[VersionRecord]:
        if not self.path.exists():
            return []

        records: list[VersionRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
                records.append(
                    VersionRecord(
                        version_id=str(payload["version_id"]),
                        snapshot_version=str(payload["snapshot_version"]),
                        metrics={
                            key: float(value)
                            for key, value in dict(payload["metrics"]).items()
                        },
                        is_stable=bool(payload["is_stable"]),
                        registered_at=str(payload["registered_at"]),
                        notes=str(payload.get("notes", "")),
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return records

    def _write_all(self, records: list[VersionRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(
            json.dumps(record.to_dict(), ensure_ascii=False)
            for record in records
        )
        if text:
            text += "\n"
        self.path.write_text(text, encoding="utf-8")
