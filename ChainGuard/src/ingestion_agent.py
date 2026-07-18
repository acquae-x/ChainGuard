from __future__ import annotations

import csv
import importlib.util
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


class ExtractBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def extract(self, file_path: str | Path) -> str | None:
        """Return extracted text; unavailable or failed backends return None."""


@dataclass(frozen=True)
class FileExtraction:
    file_name: str
    file_kind: str
    method_used: str
    rows: int
    needs_manual: bool
    note: str = ""


@dataclass(frozen=True)
class IngestionResult:
    extractions: list[FileExtraction]
    normalized: dict[str, list[dict[str, Any]]]
    needs_manual_count: int
    ok_count: int


class LLMVisionBackend:
    name = "llm_vision"

    def __init__(
        self,
        *,
        api_key_env: str = "CHAINGUARD_VISION_API_KEY",
        api_url_env: str = "CHAINGUARD_VISION_API_URL",
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_key_env = api_key_env
        self.api_url_env = api_url_env
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        try:
            return bool(os.environ.get(self.api_key_env, "").strip())
        except Exception:
            return False

    def extract(self, file_path: str | Path) -> str | None:
        try:
            api_key = os.environ.get(self.api_key_env, "").strip()
            api_url = os.environ.get(self.api_url_env, "").strip()
            if not api_key or not api_url:
                return None

            payload = json.dumps(
                {"file_name": Path(file_path).name},
                ensure_ascii=False,
            ).encode("utf-8")
            request = urllib.request.Request(
                api_url,
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
            parsed = json.loads(body)
            text = parsed.get("text") or parsed.get("content") or parsed.get("result")
            return str(text).strip() if text else None
        except (
            OSError,
            TimeoutError,
            ValueError,
            urllib.error.URLError,
            urllib.error.HTTPError,
        ):
            return None
        except Exception:
            return None


class OcrEngineBackend:
    name = "ocr_engine"

    def available(self) -> bool:
        try:
            return (
                importlib.util.find_spec("paddleocr") is not None
                or importlib.util.find_spec("pytesseract") is not None
            )
        except Exception:
            return False

    def extract(self, file_path: str | Path) -> str | None:
        try:
            if importlib.util.find_spec("paddleocr") is not None:
                from paddleocr import PaddleOCR  # type: ignore

                engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
                result = engine.ocr(str(file_path), cls=True)
                text_parts: list[str] = []
                for page in result or []:
                    for item in page or []:
                        if len(item) >= 2 and item[1]:
                            text_parts.append(str(item[1][0]))
                return "\n".join(part for part in text_parts if part).strip() or None

            if importlib.util.find_spec("pytesseract") is not None:
                import pytesseract  # type: ignore

                text = pytesseract.image_to_string(str(file_path))
                return text.strip() or None
        except Exception:
            return None
        return None


class TextLayerBackend:
    name = "text_layer"

    def available(self) -> bool:
        try:
            return (
                importlib.util.find_spec("pypdf") is not None
                or importlib.util.find_spec("pdfplumber") is not None
            )
        except Exception:
            return False

    def extract(self, file_path: str | Path) -> str | None:
        path = Path(file_path)
        if detect_kind(path) != "pdf":
            return None
        try:
            if importlib.util.find_spec("pypdf") is not None:
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(str(path))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                return text.strip() or None

            if importlib.util.find_spec("pdfplumber") is not None:
                import pdfplumber  # type: ignore

                with pdfplumber.open(str(path)) as pdf:
                    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                return text.strip() or None
        except Exception:
            return None
        return None


class WordTextBackend:
    """Extract paragraphs and tables from modern Word documents."""

    name = "word_text"

    def available(self) -> bool:
        try:
            return importlib.util.find_spec("docx") is not None
        except Exception:
            return False

    def extract(self, file_path: str | Path) -> str | None:
        path = Path(file_path)
        if path.suffix.lower() != ".docx":
            return None
        try:
            from docx import Document  # type: ignore

            document = Document(str(path))
            lines = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
            for table in document.tables:
                for row in table.rows:
                    values = [cell.text.strip() for cell in row.cells]
                    if any(values):
                        lines.append("\t".join(values))
            return "\n".join(lines).strip() or None
        except Exception:
            return None


def detect_kind(file_path: str | Path) -> str:
    """Classify file kind by extension."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in {".xlsx", ".xls"}:
        return "excel"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".doc", ".docx"}:
        return "word"
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        return "image"
    return "unknown"


def default_backends() -> list[ExtractBackend]:
    """Build cascaded extraction backends with their own availability probes."""
    return [LLMVisionBackend(), OcrEngineBackend(), TextLayerBackend(), WordTextBackend()]


def extract_with_cascade(
    file_path: str | Path,
    backends: list[ExtractBackend] | None = None,
) -> tuple[str | None, str]:
    """Try available backends in order and return extracted text plus method."""
    for backend in backends or default_backends():
        try:
            if not backend.available():
                continue
        except Exception:
            continue
        try:
            text = backend.extract(file_path)
        except Exception:
            text = None
        if text:
            return text, backend.name
    return None, "manual_required"


def ingest_files(
    file_paths: list[str | Path],
    *,
    backends: list[ExtractBackend] | None = None,
    csv_reader: Callable[[str | Path], list[dict[str, Any]]] | None = None,
) -> IngestionResult:
    """Detect, extract, normalize, and summarize a batch of source files."""
    normalized: dict[str, list[dict[str, Any]]] = {}
    extractions: list[FileExtraction] = []
    reader = csv_reader or _read_csv_rows

    for file_path in file_paths:
        path = Path(file_path)
        kind = detect_kind(path)
        stem = path.stem.lower()

        if kind == "csv":
            rows, note = _safe_read_csv(reader, path)
            table_name = stem
            if rows:
                normalized[table_name] = rows
                extractions.append(
                    FileExtraction(path.name, kind, "direct", len(rows), False)
                )
            else:
                extractions.append(
                    FileExtraction(
                        path.name,
                        kind,
                        "direct",
                        0,
                        True,
                        note or "No rows extracted; manual review required",
                    )
                )
            continue

        if kind in {"excel", "pdf", "image", "word"}:
            text, method_used = extract_with_cascade(path, backends)
            rows = _text_to_rows(text or "")
            if rows:
                normalized[f"{stem}_intake"] = rows
                extractions.append(
                    FileExtraction(path.name, kind, method_used, len(rows), False)
                )
            else:
                extractions.append(
                    FileExtraction(
                        path.name,
                        kind,
                        "manual_required",
                        0,
                        True,
                        "Unrecognized; manual entry required",
                    )
                )
            continue

        extractions.append(
            FileExtraction(
                path.name,
                kind,
                "manual_required",
                0,
                True,
                "Unsupported file type; manual entry required",
            )
        )

    needs_manual_count = sum(1 for extraction in extractions if extraction.needs_manual)
    return IngestionResult(
        extractions=extractions,
        normalized=normalized,
        needs_manual_count=needs_manual_count,
        ok_count=len(extractions) - needs_manual_count,
    )


def _read_csv_rows(file_path: str | Path) -> list[dict[str, Any]]:
    with Path(file_path).open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _safe_read_csv(
    reader: Callable[[str | Path], list[dict[str, Any]]],
    path: Path,
) -> tuple[list[dict[str, Any]], str]:
    try:
        return reader(path), ""
    except Exception as exc:
        return [], f"CSV parse failed: {exc}"


def _text_to_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        values = _split_text_line(line)
        if not values:
            continue
        rows.append({f"col_{index + 1}": value for index, value in enumerate(values)})
    return rows


def _split_text_line(line: str) -> list[str]:
    if "\t" in line:
        return [part.strip() for part in line.split("\t")]
    try:
        parsed = next(csv.reader([line]))
        return [part.strip() for part in parsed]
    except Exception:
        return [line]
