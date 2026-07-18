from __future__ import annotations

from pathlib import Path

from src.ingestion_agent import detect_kind, extract_with_cascade, ingest_files


class StubBackend:
    def __init__(
        self,
        name: str,
        *,
        is_available: bool = True,
        text: str | None = None,
        raises: bool = False,
    ) -> None:
        self.name = name
        self.is_available = is_available
        self.text = text
        self.raises = raises

    def available(self) -> bool:
        return self.is_available

    def extract(self, file_path: str | Path) -> str | None:
        if self.raises:
            raise RuntimeError("backend failed")
        return self.text


def test_detect_kind() -> None:
    assert detect_kind("materials.csv") == "csv"
    assert detect_kind("materials.xlsx") == "excel"
    assert detect_kind("report.pdf") == "pdf"
    assert detect_kind("contract.docx") == "word"
    assert detect_kind("legacy.doc") == "word"
    assert detect_kind("scan.png") == "image"
    assert detect_kind("scan.unknown") == "unknown"


def test_cascade_prefers_first_available(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"fake image")
    backends = [
        StubBackend("first", text="a,b\n1,2"),
        StubBackend("second", text="x,y\n3,4"),
    ]

    text, method = extract_with_cascade(source, backends)

    assert text == "a,b\n1,2"
    assert method == "first"


def test_cascade_skips_unavailable(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"fake image")
    backends = [
        StubBackend("first", is_available=False, text="unused"),
        StubBackend("second", text="used"),
    ]

    text, method = extract_with_cascade(source, backends)

    assert text == "used"
    assert method == "second"


def test_cascade_all_fail_manual(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"fake image")
    backends = [
        StubBackend("missing", is_available=False, text="unused"),
        StubBackend("empty", text=None),
    ]

    assert extract_with_cascade(source, backends) == (None, "manual_required")


def test_ingest_csv_direct(tmp_path: Path) -> None:
    source = tmp_path / "inventory.csv"
    source.write_text("material_id,qty\nM1,10\nM2,5\n", encoding="utf-8")

    result = ingest_files([source])

    assert result.normalized["inventory"] == [
        {"material_id": "M1", "qty": "10"},
        {"material_id": "M2", "qty": "5"},
    ]
    assert result.extractions[0].rows == 2
    assert result.extractions[0].method_used == "direct"
    assert result.extractions[0].needs_manual is False


def test_ingest_image_no_backend_marks_manual(tmp_path: Path) -> None:
    source = tmp_path / "inventory.png"
    source.write_bytes(b"fake image")

    result = ingest_files([source], backends=[StubBackend("missing", is_available=False)])

    assert result.extractions[0].needs_manual is True
    assert result.extractions[0].rows == 0
    assert result.normalized == {}


def test_ingest_image_with_stub_backend(tmp_path: Path) -> None:
    source = tmp_path / "inventory.png"
    source.write_bytes(b"fake image")
    backend = StubBackend("stub_ocr", text="material_id,qty\nM1,10")

    result = ingest_files([source], backends=[backend])

    assert result.extractions[0].needs_manual is False
    assert result.extractions[0].method_used == "stub_ocr"
    assert result.extractions[0].rows > 0
    assert result.normalized["inventory_intake"] == [
        {"col_1": "material_id", "col_2": "qty"},
        {"col_1": "M1", "col_2": "10"},
    ]


def test_ingest_counts(tmp_path: Path) -> None:
    csv_source = tmp_path / "inventory.csv"
    csv_source.write_text("material_id,qty\nM1,10\n", encoding="utf-8")
    image_source = tmp_path / "photo.png"
    image_source.write_bytes(b"fake image")

    result = ingest_files(
        [csv_source, image_source],
        backends=[StubBackend("missing", is_available=False)],
    )

    assert result.ok_count == 1
    assert result.needs_manual_count == 1


def test_backend_extract_never_raises(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"fake image")
    backends = [
        StubBackend("bad", text="unused", raises=True),
        StubBackend("fallback", text="safe text"),
    ]

    text, method = extract_with_cascade(source, backends)

    assert text == "safe text"
    assert method == "fallback"


def test_empty_files() -> None:
    result = ingest_files([])

    assert result.extractions == []
    assert result.normalized == {}
    assert result.ok_count == 0
    assert result.needs_manual_count == 0


def test_input_changes_output(tmp_path: Path) -> None:
    source = tmp_path / "inventory.png"
    source.write_bytes(b"fake image")

    manual_result = ingest_files(
        [source],
        backends=[StubBackend("missing", is_available=False)],
    )
    extracted_result = ingest_files(
        [source],
        backends=[StubBackend("stub_ocr", text="material_id,qty\nM1,10")],
    )

    assert manual_result.extractions[0].needs_manual is True
    assert extracted_result.extractions[0].needs_manual is False
    assert manual_result.normalized != extracted_result.normalized


def test_csv_lands_in_canonical_table(tmp_path: Path) -> None:
    source = tmp_path / "inventory.csv"
    source.write_text("material_id,qty\nM1,10\n", encoding="utf-8")

    result = ingest_files([source])

    assert "inventory" in result.normalized


def test_non_csv_lands_in_staging_table(tmp_path: Path) -> None:
    source = tmp_path / "inventory.png"
    source.write_bytes(b"fake image")

    result = ingest_files(
        [source],
        backends=[StubBackend("stub_ocr", text="material_id,qty\nM1,10")],
    )

    assert "inventory_intake" in result.normalized
    assert "inventory" not in result.normalized
