from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from src.intake_review import DEFAULT_KEY_FIELDS, build_history_counts


def history_path_for(data_source: Any) -> Path:
    """Return the tenant-scoped persistent signature history path."""
    audit_path = Path(getattr(data_source, "audit_log_path", "data/audit_log.jsonl"))
    parent = audit_path.parent
    tenant_id = getattr(data_source, "tenant_id", "default")
    kind = getattr(data_source, "kind", "demo")
    if kind == "demo" or tenant_id == "default":
        return parent / "signature_history.json"
    return parent / f"signature_history.{tenant_id}.json"


def load_history(data_source: Any) -> dict[str, int]:
    """Load cumulative signature counts; missing or invalid files are empty."""
    path = history_path_for(data_source)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}

    counts: dict[str, int] = {}
    for key, value in raw.items():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            counts[str(key)] = count
    return counts


def update_history(
    data_source: Any,
    records: Iterable[dict[str, Any]],
    *,
    key_fields: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Accumulate record signatures into the persistent history and return all counts."""
    delta = build_history_counts(records, key_fields or DEFAULT_KEY_FIELDS)
    current = load_history(data_source)
    if not delta:
        return current
    merged = merge_counts(current, delta)
    path = history_path_for(data_source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return merged


def merge_counts(base: dict[str, int], delta: dict[str, int]) -> dict[str, int]:
    """Return summed signature counts without mutating the inputs."""
    merged = dict(base)
    for key, value in delta.items():
        merged[key] = int(merged.get(key, 0) or 0) + int(value or 0)
    return merged
