from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from src.file_store import atomic_write_text, file_lock
from src.intake_review import DEFAULT_KEY_FIELDS, build_history_counts, signature_of
from src.observability import log_event


def tabular_file_signature(path: str | Path, resource_type: str) -> tuple[str, int]:
    """Return a stable D04 signature and data-row count for normalized input.

    CSV/XLSX/OCR inputs all reach execute as normalized CSV.  Values reuse the
    existing ``signature_of`` normalization contract (trim, lowercase, empty
    becomes ``unknown``), while sorted column names make equivalent CSV/XLSX
    payloads produce the same SHA-256 signature.  Non-tabular files use a
    streamed byte hash as a defensive fallback.
    """

    source = Path(path)
    digest = hashlib.sha256()
    digest.update(f"chainguard-import-v1\0{resource_type.strip().lower()}\0".encode())
    if source.suffix.lower() == ".csv":
        last_error: UnicodeDecodeError | None = None
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with source.open("r", encoding=encoding, newline="") as handle:
                    reader = csv.DictReader(handle)
                    columns = sorted(str(name or "").strip() for name in (reader.fieldnames or []))
                    digest.update(json.dumps(columns, ensure_ascii=False).encode("utf-8"))
                    count = 0
                    for row in reader:
                        digest.update(signature_of(dict(row), columns).encode("utf-8"))
                        digest.update(b"\n")
                        count += 1
                return digest.hexdigest(), count
            except UnicodeDecodeError as error:
                last_error = error
                digest = hashlib.sha256()
                digest.update(f"chainguard-import-v1\0{resource_type.strip().lower()}\0".encode())
        assert last_error is not None
        raise last_error

    count = 0
    with source.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest(), count


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
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as error:
        # 文件存在但读不出来 ≠ 还没有历史。此前两者都返回 {}，效果是整个租户的
        # 去重计数被静默清零、重复导入检测失效且无任何痕迹。至少要留下证据。
        log_event(
            "signature_history_unreadable",
            path=str(path),
            exception=type(error).__name__,
            message=str(error),
        )
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
    if not delta:
        return load_history(data_source)
    path = history_path_for(data_source)
    # 累加计数是读-改-写：并发导入（导入作业跑在后台线程）不加锁会互相覆盖，
    # 表现为去重计数偏低——而计数偏低只会让重复数据被放行，不会报错。
    with file_lock(path):
        merged = merge_counts(load_history(data_source), delta)
        atomic_write_text(
            path,
            json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True),
        )
    return merged


def merge_counts(base: dict[str, int], delta: dict[str, int]) -> dict[str, int]:
    """Return summed signature counts without mutating the inputs."""
    merged = dict(base)
    for key, value in delta.items():
        merged[key] = int(merged.get(key, 0) or 0) + int(value or 0)
    return merged
