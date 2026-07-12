import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

from scripts.enterprise_import import (
    TableImportResult,
    import_csv,
    import_pdf,
    run_import,
    validate_csv,
    validate_pdf,
)


DEMO_CSV_DIR = "demo_assets/enterprise/csv"


def test_validate_valid_materials_csv_returns_ok():
    result = validate_csv(f"{DEMO_CSV_DIR}/materials.csv", "materials")

    assert isinstance(result, TableImportResult)
    assert result.status == "ok"
    assert result.missing_columns == []
    assert result.source_type == "csv"


def test_import_materials_writes_rows_to_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = handle.name

    try:
        result = import_csv(f"{DEMO_CSV_DIR}/materials.csv", "materials", db_path)
        assert result.status == "ok"
        assert result.rows_imported > 0
        connection = sqlite3.connect(db_path)
        try:
            count = connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        finally:
            connection.close()
        assert count == result.rows_imported
    finally:
        os.unlink(db_path)


def test_missing_required_column_returns_skipped():
    with tempfile.NamedTemporaryFile(
        suffix=".csv",
        delete=False,
        mode="w",
        encoding="utf-8",
        newline="",
    ) as handle:
        handle.write("material_id,material_name\nM001,chip\n")
        csv_path = handle.name

    try:
        result = validate_csv(csv_path, "materials")
        assert result.status == "skipped"
        assert "daily_consumption" in result.missing_columns
    finally:
        os.unlink(csv_path)


def test_dry_run_does_not_write_database():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = handle.name
    os.unlink(db_path)

    try:
        run_import(DEMO_CSV_DIR, db_path, dry_run=True)
        assert not os.path.exists(db_path), "dry_run should not create database file"
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_run_import_all_demo_csvs_mostly_succeed():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = handle.name

    try:
        results = run_import(DEMO_CSV_DIR, db_path)
        ok_results = [result for result in results if result.status == "ok"]
        assert len(ok_results) >= 6, f"expected at least 6 ok tables, got {len(ok_results)}"
    finally:
        os.unlink(db_path)


def test_validate_pdf_with_valid_table_returns_ok():
    mock_table = [
        ["material_id", "material_name", "daily_consumption"],
        ["M001", "steel", "100"],
        ["M002", "copper", "50"],
    ]
    mock_page = MagicMock()
    mock_page.extract_tables.return_value = [mock_table]
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda self: mock_pdf
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("pdfplumber.open", return_value=mock_pdf):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            pdf_path = handle.name
        try:
            result = validate_pdf(pdf_path, "materials")
            assert result.status == "ok"
            assert result.rows_imported == 2
            assert result.source_type == "pdf"
            assert result.missing_columns == []
        finally:
            os.unlink(pdf_path)


def test_validate_pdf_with_no_table_returns_skipped():
    mock_page = MagicMock()
    mock_page.extract_tables.return_value = []
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda self: mock_pdf
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("pdfplumber.open", return_value=mock_pdf):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            pdf_path = handle.name
        try:
            result = validate_pdf(pdf_path, "materials")
            assert result.status == "skipped"
            assert result.rows_imported == 0
            assert "未找到" in result.warning or "no" in result.warning.lower()
        finally:
            os.unlink(pdf_path)
