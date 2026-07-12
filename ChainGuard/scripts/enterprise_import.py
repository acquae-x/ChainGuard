from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


DEFAULT_DB_PATH = "demo_assets/enterprise/database/chainguard_enterprise_demo.db"

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "materials": ["material_id", "material_name", "daily_consumption"],
    "inventory": ["material_id", "on_hand_qty", "safety_stock_qty", "in_transit_qty"],
    "suppliers": ["supplier_id", "supplier_name", "reliability_score"],
    "supplier_materials": [
        "supplier_id",
        "material_id",
        "available_emergency_qty",
        "lead_time_hours",
        "emergency_cost_multiplier",
    ],
    "disruption_events": [
        "event_id",
        "event_type",
        "severity",
        "risk_score",
        "affected_supplier_id",
        "affected_material_id",
        "estimated_delay_hours",
    ],
    "sales_orders": ["sales_order_id", "customer_level", "order_status"],
    "sales_order_lines": ["sales_order_id", "material_id", "ordered_qty"],
    "historical_decisions": [
        "case_id",
        "outcome_status",
        "covered_demand_rate",
        "actual_delay_hours",
        "actual_cost",
        "human_rating",
        "created_at",
    ],
}


@dataclass
class TableImportResult:
    table_name: str
    file_path: str
    source_type: Literal["csv", "pdf"]
    status: Literal["ok", "skipped", "unknown_table"]
    rows_imported: int
    missing_columns: list[str]
    warning: str


def validate_csv(csv_path: str, table_name: str) -> TableImportResult:
    if table_name not in REQUIRED_COLUMNS:
        return TableImportResult(
            table_name=table_name,
            file_path=str(csv_path),
            source_type="csv",
            status="unknown_table",
            rows_imported=0,
            missing_columns=[],
            warning="未知表名，跳过",
        )

    rows, columns, warning = _read_csv_rows(csv_path)
    if warning:
        return TableImportResult(
            table_name=table_name,
            file_path=str(csv_path),
            source_type="csv",
            status="skipped",
            rows_imported=0,
            missing_columns=[],
            warning=warning,
        )

    missing = _missing_columns(columns, table_name)
    if missing:
        return TableImportResult(
            table_name=table_name,
            file_path=str(csv_path),
            source_type="csv",
            status="skipped",
            rows_imported=0,
            missing_columns=missing,
            warning=f"缺少必要列 {missing}",
        )

    if not rows:
        return TableImportResult(
            table_name=table_name,
            file_path=str(csv_path),
            source_type="csv",
            status="skipped",
            rows_imported=0,
            missing_columns=[],
            warning="CSV 文件为空或无数据行",
        )

    return TableImportResult(
        table_name=table_name,
        file_path=str(csv_path),
        source_type="csv",
        status="ok",
        rows_imported=len(rows),
        missing_columns=[],
        warning="",
    )


def validate_pdf(pdf_path: str, table_name: str) -> TableImportResult:
    if table_name not in REQUIRED_COLUMNS:
        return TableImportResult(
            table_name=table_name,
            file_path=str(pdf_path),
            source_type="pdf",
            status="unknown_table",
            rows_imported=0,
            missing_columns=[],
            warning="未知表名，跳过",
        )

    rows, columns, warning = _extract_pdf_rows(pdf_path)
    if warning:
        return TableImportResult(
            table_name=table_name,
            file_path=str(pdf_path),
            source_type="pdf",
            status="skipped",
            rows_imported=0,
            missing_columns=[],
            warning=warning,
        )

    missing = _missing_columns(columns, table_name)
    if missing:
        return TableImportResult(
            table_name=table_name,
            file_path=str(pdf_path),
            source_type="pdf",
            status="skipped",
            rows_imported=0,
            missing_columns=missing,
            warning=f"缺少必要列 {missing}",
        )

    return TableImportResult(
        table_name=table_name,
        file_path=str(pdf_path),
        source_type="pdf",
        status="ok",
        rows_imported=len(rows),
        missing_columns=[],
        warning="",
    )


def import_csv(
    csv_path: str,
    table_name: str,
    db_path: str,
    overwrite: bool = True,
) -> TableImportResult:
    result = validate_csv(csv_path, table_name)
    if result.status != "ok":
        return result

    rows, columns, warning = _read_csv_rows(csv_path)
    if warning:
        result.status = "skipped"
        result.rows_imported = 0
        result.warning = warning
        return result

    _write_rows_to_sqlite(rows, columns, table_name, db_path, overwrite)
    result.rows_imported = len(rows)
    return result


def import_pdf(
    pdf_path: str,
    table_name: str,
    db_path: str,
    overwrite: bool = True,
) -> TableImportResult:
    result = validate_pdf(pdf_path, table_name)
    if result.status != "ok":
        return result

    rows, columns, warning = _extract_pdf_rows(pdf_path)
    if warning:
        result.status = "skipped"
        result.rows_imported = 0
        result.warning = warning
        return result

    _write_rows_to_sqlite(rows, columns, table_name, db_path, overwrite)
    result.rows_imported = len(rows)
    return result


def run_import(
    data_dir: str,
    db_path: str,
    dry_run: bool = False,
    overwrite: bool = True,
) -> list[TableImportResult]:
    root = Path(data_dir)
    csv_files = {path.stem.lower(): path for path in sorted(root.glob("*.csv"))}
    pdf_files = {path.stem.lower(): path for path in sorted(root.glob("*.pdf"))}

    results: list[TableImportResult] = []
    for table_name in sorted(set(csv_files) | set(pdf_files)):
        if table_name in csv_files:
            csv_path = csv_files[table_name]
            result = (
                validate_csv(str(csv_path), table_name)
                if dry_run
                else import_csv(str(csv_path), table_name, db_path, overwrite)
            )
            results.append(result)
            if table_name in pdf_files:
                results.append(
                    TableImportResult(
                        table_name=table_name,
                        file_path=str(pdf_files[table_name]),
                        source_type="pdf",
                        status="skipped",
                        rows_imported=0,
                        missing_columns=[],
                        warning="CSV优先，PDF跳过",
                    )
                )
            continue

        pdf_path = pdf_files[table_name]
        result = (
            validate_pdf(str(pdf_path), table_name)
            if dry_run
            else import_pdf(str(pdf_path), table_name, db_path, overwrite)
        )
        results.append(result)

    return results


def _read_csv_rows(csv_path: str) -> tuple[list[dict[str, str]], list[str], str]:
    last_error = ""
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(csv_path, newline="", encoding=encoding) as handle:
                reader = csv.DictReader(handle)
                columns = [str(column).strip() for column in (reader.fieldnames or [])]
                if not columns:
                    return [], [], "CSV 文件为空或缺少表头"
                rows = [
                    {
                        str(key).strip(): "" if value is None else str(value)
                        for key, value in row.items()
                        if key is not None
                    }
                    for row in reader
                ]
                return rows, columns, ""
        except UnicodeDecodeError as error:
            last_error = str(error)
    return [], [], f"CSV 编码解析失败: {last_error}"


def _extract_pdf_rows(pdf_path: str) -> tuple[list[dict[str, str]], list[str], str]:
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table or len(table) < 2:
                        continue
                    columns = [str(value or "").strip() for value in table[0]]
                    if not any(columns):
                        continue
                    rows = []
                    for raw_row in table[1:]:
                        row_values = list(raw_row or [])
                        row = {
                            column: (
                                ""
                                if index >= len(row_values) or row_values[index] is None
                                else str(row_values[index]).strip()
                            )
                            for index, column in enumerate(columns)
                        }
                        rows.append(row)
                    return rows, columns, ""
    except Exception as error:
        return [], [], f"PDF解析失败: {error}"
    return [], [], "PDF中未找到可用表格"


def _missing_columns(columns: list[str], table_name: str) -> list[str]:
    actual = {column.strip() for column in columns}
    return [
        column
        for column in REQUIRED_COLUMNS.get(table_name, [])
        if column not in actual
    ]


def _write_rows_to_sqlite(
    rows: list[dict[str, str]],
    columns: list[str],
    table_name: str,
    db_path: str,
    overwrite: bool,
) -> None:
    path = _resolve_db_path(db_path)
    if path.parent and str(path.parent) not in {"", "."}:
        path.parent.mkdir(parents=True, exist_ok=True)

    quoted_table = _quote_identifier(table_name)
    quoted_columns = [_quote_identifier(column) for column in columns]
    placeholders = ", ".join("?" for _ in columns)
    connection = sqlite3.connect(path)
    try:
        if overwrite:
            connection.execute(f"DROP TABLE IF EXISTS {quoted_table}")
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {quoted_table} "
            f"({', '.join(f'{column} TEXT' for column in quoted_columns)})"
        )
        connection.executemany(
            f"INSERT INTO {quoted_table} ({', '.join(quoted_columns)}) "
            f"VALUES ({placeholders})",
            [[row.get(column, "") for column in columns] for row in rows],
        )
        connection.commit()
    finally:
        connection.close()


def _resolve_db_path(db_path: str) -> Path:
    normalized = db_path.replace("\\", "/")
    if os.name == "nt" and normalized.startswith("/tmp/"):
        return Path(tempfile.gettempdir()) / normalized.removeprefix("/tmp/")
    return Path(db_path)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _format_result(result: TableImportResult) -> str:
    name = Path(result.file_path).name
    if result.status == "ok":
        suffix = " [PDF]" if result.source_type == "pdf" else ""
        return (
            f"[OK] {name:<32} -> {result.table_name:<25} "
            f"{result.rows_imported} rows{suffix}"
        )
    if result.status == "unknown_table":
        return f"[UNKNOWN] {name:<32} -> unknown table, skipped"
    return f"[SKIP] {name:<32} -> skipped: {result.warning}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import enterprise CSV/PDF tables into a ChainGuard SQLite database.",
    )
    parser.add_argument("--data-dir", required=True, help="Directory containing CSV/PDF files")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Target SQLite database path")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write DB")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=True,
        help="Replace existing table data; enabled by default",
    )
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    if not data_dir.exists() or not data_dir.is_dir():
        print(f"错误：--data-dir 不存在或不是目录：{data_dir}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("[DRY RUN] preview mode; database will not be written")

    results = run_import(
        str(data_dir),
        args.db,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    for result in results:
        print(_format_result(result))
    ok_count = sum(1 for result in results if result.status == "ok")
    print(f"Import complete: {ok_count}/{len(results)} tables ok. DB={args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
