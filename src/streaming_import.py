from __future__ import annotations

import csv
import codecs
import sqlite3
from pathlib import Path
from typing import Callable


INDEX_SPEC: dict[str, list[str]] = {
    "inventory": ["material_id"],
    "supplier_materials": ["material_id", "supplier_id"],
    "sales_order_lines": ["material_id", "sales_order_id"],
    "sales_orders": ["customer_level", "order_status"],
    "disruption_events": ["affected_material_id"],
}


def stream_import_csv(
    csv_path: str | Path,
    table_name: str,
    db_path: str | Path,
    *,
    batch_size: int = 10000,
    overwrite: bool = True,
    progress: Callable[[int], None] | None = None,
) -> int:
    """Stream CSV rows into SQLite, committing once per batch."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    row_count = 0
    csv_file = Path(csv_path)
    encoding = _detect_encoding(csv_file)
    with csv_file.open(newline="", encoding=encoding) as handle:
        reader = csv.reader(handle)
        raw_columns = next(reader, None)

        connection = sqlite3.connect(path)
        try:
            quoted_table = _quote_identifier(table_name)
            if overwrite:
                connection.execute(f"DROP TABLE IF EXISTS {quoted_table}")
                connection.commit()

            if not raw_columns:
                return 0

            columns = _normalize_columns(raw_columns)
            quoted_columns = [_quote_identifier(column) for column in columns]
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {quoted_table} "
                f"({', '.join(f'{column} TEXT' for column in quoted_columns)})"
            )
            placeholders = ", ".join("?" for _ in columns)
            insert_sql = (
                f"INSERT INTO {quoted_table} ({', '.join(quoted_columns)}) "
                f"VALUES ({placeholders})"
            )

            batch: list[list[str]] = []
            for row in reader:
                batch.append(_normalize_row(row, len(columns)))
                if len(batch) >= batch_size:
                    connection.executemany(insert_sql, batch)
                    connection.commit()
                    row_count += len(batch)
                    if progress is not None:
                        progress(row_count)
                    batch.clear()

            if batch:
                connection.executemany(insert_sql, batch)
                connection.commit()
                row_count += len(batch)
                if progress is not None:
                    progress(row_count)
        finally:
            connection.close()

    return row_count


def create_indexes(db_path: str | Path, table_name: str) -> list[str]:
    """Create indexes from INDEX_SPEC for columns present in the table."""
    columns = INDEX_SPEC.get(table_name, [])
    if not columns:
        return []

    created: list[str] = []
    connection = sqlite3.connect(Path(db_path))
    try:
        existing_columns = {
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({_quote_identifier(table_name)})"
            ).fetchall()
        }
        for column in columns:
            if column not in existing_columns:
                continue
            index_name = f"idx_{table_name}_{column}"
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {_quote_identifier(index_name)} "
                f"ON {_quote_identifier(table_name)} ({_quote_identifier(column)})"
            )
            created.append(index_name)
        connection.commit()
    finally:
        connection.close()
    return created


def reconcile(csv_path: str | Path, table_name: str, db_path: str | Path) -> tuple[bool, int, int]:
    """Compare CSV data-row count with rows persisted in SQLite."""
    csv_rows = _count_csv_data_rows(csv_path)
    connection = sqlite3.connect(Path(db_path))
    try:
        db_rows = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}"
            ).fetchone()[0]
        )
    except sqlite3.OperationalError:
        db_rows = 0
    finally:
        connection.close()
    return csv_rows == db_rows, csv_rows, db_rows


def _count_csv_data_rows(csv_path: str | Path) -> int:
    csv_file = Path(csv_path)
    with csv_file.open(newline="", encoding=_detect_encoding(csv_file)) as handle:
        reader = csv.reader(handle)
        if next(reader, None) is None:
            return 0
        return sum(1 for _ in reader)


def _detect_encoding(csv_path: Path) -> str:
    with csv_path.open("rb") as handle:
        sample = handle.read(65536)
    last_error = ""
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            codecs.getincrementaldecoder(encoding)().decode(sample, final=False)
            return encoding
        except UnicodeDecodeError as exc:
            last_error = str(exc)
    raise UnicodeDecodeError("csv", b"", 0, 1, f"unsupported CSV encoding: {last_error}")


def _normalize_columns(raw_columns: list[str]) -> list[str]:
    columns: list[str] = []
    seen: dict[str, int] = {}
    for index, raw_column in enumerate(raw_columns):
        base = str(raw_column).strip() or f"column_{index + 1}"
        suffix = seen.get(base, 0)
        seen[base] = suffix + 1
        columns.append(base if suffix == 0 else f"{base}_{suffix + 1}")
    return columns


def _normalize_row(row: list[str], width: int) -> list[str]:
    normalized = ["" if value is None else str(value) for value in row[:width]]
    if len(normalized) < width:
        normalized.extend("" for _ in range(width - len(normalized)))
    return normalized


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
