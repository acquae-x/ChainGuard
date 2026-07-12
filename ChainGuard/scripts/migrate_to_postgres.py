from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.db import DEFAULT_SQLITE_DB  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate the ChainGuard SQLite demo database to PostgreSQL."
    )
    parser.add_argument(
        "--sqlite",
        default=str(DEFAULT_SQLITE_DB),
        help="Source SQLite database path.",
    )
    parser.add_argument(
        "--postgres-url",
        default=os.getenv("DATABASE_URL"),
        help="Target PostgreSQL URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Rows per insert batch.",
    )
    parser.add_argument(
        "--schema",
        default="public",
        help="Target PostgreSQL schema.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate target tables before inserting data.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise FileNotFoundError(sqlite_path)
    if not args.postgres_url:
        raise ValueError("--postgres-url or DATABASE_URL is required")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    try:
        import psycopg
    except ImportError as exc:
        raise ImportError(
            "PostgreSQL migration requires psycopg. Install it with: "
            "pip install 'psycopg[binary]>=3'."
        ) from exc

    with sqlite3.connect(sqlite_path) as sqlite_conn:
        sqlite_conn.row_factory = sqlite3.Row
        tables = _sqlite_tables(sqlite_conn)
        with psycopg.connect(args.postgres_url) as pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{args.schema}"')
                cursor.execute(f'SET search_path TO "{args.schema}"')
                for table_name, create_sql in tables:
                    cursor.execute(_postgres_create_table(create_sql))
                    if args.truncate:
                        cursor.execute(f'TRUNCATE TABLE "{table_name}"')
                    count = _copy_table(
                        sqlite_conn,
                        cursor,
                        table_name,
                        batch_size=args.batch_size,
                    )
                    print(f"{table_name}: migrated {count} rows")
            pg_conn.commit()
    return 0


def _sqlite_tables(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = connection.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [(str(row["name"]), str(row["sql"])) for row in rows]


def _postgres_create_table(create_sql: str) -> str:
    statement = re.sub(
        r"^CREATE TABLE",
        "CREATE TABLE IF NOT EXISTS",
        create_sql.strip(),
        flags=re.IGNORECASE,
    )
    statement = re.sub(r"\bAUTOINCREMENT\b", "", statement, flags=re.IGNORECASE)
    statement = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\b",
        "BIGSERIAL PRIMARY KEY",
        statement,
        flags=re.IGNORECASE,
    )
    return statement


def _copy_table(
    sqlite_conn: sqlite3.Connection,
    pg_cursor,
    table_name: str,
    *,
    batch_size: int,
) -> int:
    source_cursor = sqlite_conn.execute(f'SELECT * FROM "{table_name}"')
    columns = [description[0] for description in source_cursor.description]
    total = 0
    while True:
        rows = source_cursor.fetchmany(batch_size)
        if not rows:
            break
        _insert_rows(pg_cursor, table_name, columns, rows)
        total += len(rows)
    return total


def _insert_rows(
    pg_cursor,
    table_name: str,
    columns: list[str],
    rows: Iterable[sqlite3.Row],
) -> None:
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = (
        f'INSERT INTO "{table_name}" ({quoted_columns}) '
        f"VALUES ({placeholders})"
    )
    values = [tuple(row[column] for column in columns) for row in rows]
    pg_cursor.executemany(sql, values)


if __name__ == "__main__":
    raise SystemExit(main())
