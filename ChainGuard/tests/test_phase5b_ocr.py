from __future__ import annotations

import io
import shutil
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from src.api import app
from src.ingestion_agent import OcrEngineBackend, _reconstruct_ocr_lines, ingest_files
from src.webapi.auth.security import create_tokens
from src.webapi.database import SessionLocal
from src.webapi.models import Material, User
from src.webapi.seed import seed


@pytest.fixture(scope="module")
def ocr_runtime_dir():
    path = Path(__file__).resolve().parent / "_runtime_tmp" / "phase5b_ocr" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _font_path() -> Path:
    candidates = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.skip("没有可生成中英文真实 OCR 样本的 CJK 字体")


def _image_bytes(
    lines: list[str],
    image_format: str = "PNG",
    *,
    font_path: Path | None = None,
    font_size: int = 48,
) -> bytes:
    image = Image.new("RGB", (1800, 160 + (font_size * 2 + 19) * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path or _font_path()), font_size)
    for index, line in enumerate(lines):
        draw.text((35, 45 + index * (font_size * 2 + 19)), line, font=font, fill="black")
    output = io.BytesIO()
    image.save(output, format=image_format, quality=96)
    return output.getvalue()


def _write_image(path: Path, lines: list[str], image_format: str) -> Path:
    path.write_bytes(_image_bytes(lines, image_format))
    return path


def test_rapidocr_boxes_rebuild_split_cells_into_visual_rows():
    payload = {
        "texts": ["成本", "物料编码", "物料名称", "12.50", "MAT-BOX-001", "中文芯片"],
        "boxes": [
            [[410, 10], [500, 10], [500, 50], [410, 50]],
            [[10, 10], [120, 10], [120, 50], [10, 50]],
            [[180, 10], [330, 10], [330, 50], [180, 50]],
            [[410, 80], [500, 80], [500, 120], [410, 120]],
            [[10, 80], [150, 80], [150, 120], [10, 120]],
            [[180, 80], [330, 80], [330, 120], [180, 120]],
        ],
    }

    assert _reconstruct_ocr_lines(payload) == [
        "物料编码,物料名称,成本",
        "MAT-BOX-001,中文芯片,12.50",
    ]


@pytest.mark.parametrize(
    ("suffix", "image_format", "headers", "name"),
    [
        (".png", "PNG", "物料编码,物料名称,成本", "中文界面验收芯片"),
        (".jpg", "JPEG", "material_id,物料名称,standard_cost", "中英文混合芯片"),
    ],
)
def test_real_png_jpg_recognize_three_columns_and_mixed_text(
    ocr_runtime_dir: Path, suffix: str, image_format: str, headers: str, name: str
):
    path = _write_image(
        ocr_runtime_dir / f"bilingual-{uuid.uuid4().hex}{suffix}",
        [headers, f"MAT-OCR-001,{name},12.50"],
        image_format,
    )

    result = ingest_files([path], backends=[OcrEngineBackend(timeout_seconds=30, min_confidence=0.70)])

    extraction = result.extractions[0]
    assert extraction.method_used == "rapidocr_local"
    assert extraction.needs_manual is False
    assert extraction.confidence is not None and extraction.confidence >= 0.70
    rows = next(iter(result.normalized.values()))
    assert len(rows) == 2
    assert list(rows[0].values()) == headers.split(",")
    assert list(rows[1].values()) == ["MAT-OCR-001", name, "12.50"]


def test_real_microsoft_yahei_png_preserves_chinese_headers_and_full_width_separator(
    ocr_runtime_dir: Path,
):
    yahei = Path("C:/Windows/Fonts/msyh.ttc")
    if not yahei.is_file():
        pytest.skip("Windows Microsoft YaHei font is unavailable")
    path = ocr_runtime_dir / "microsoft-yahei-real.png"
    path.write_bytes(_image_bytes(
        ["物料编码，物料名称，成本", "MAT-UI-ZH-001，中文界面验收芯片，12.50"],
        font_path=yahei,
        font_size=24,
    ))

    result = ingest_files([path], backends=[OcrEngineBackend(timeout_seconds=30)])

    extraction = result.extractions[0]
    assert extraction.needs_manual is False
    assert extraction.confidence is not None and extraction.confidence >= 0.75
    rows = next(iter(result.normalized.values()))
    assert list(rows[0].values()) == ["物料编码", "物料名称", "成本"]
    assert list(rows[1].values()) == ["MAT-UI-ZH-001", "中文界面验收芯片", "12.50"]


@pytest.mark.parametrize(
    ("file_name", "lines", "error_code"),
    [
        ("garbled.png", ["????,????,??", "MAT-BAD-001,??????,12.50"], "OCR_GARBLED_TEXT"),
        ("broken-structure.png", ["物料编码物料名称成本", "MAT-BAD-002中文芯片12.50"], "OCR_STRUCTURE_INCOMPLETE"),
    ],
)
def test_real_high_confidence_garbage_and_broken_structure_never_preflight_green(
    ocr_runtime_dir: Path, file_name: str, lines: list[str], error_code: str
):
    path = _write_image(ocr_runtime_dir / file_name, lines, "PNG")

    result = ingest_files([path], backends=[OcrEngineBackend(timeout_seconds=30)])

    extraction = result.extractions[0]
    assert extraction.needs_manual is True
    assert extraction.error_code == error_code
    assert not result.normalized
    assert "重新上传" in extraction.note and "人工录入" in extraction.note


def test_blank_damaged_low_confidence_and_missing_engine_degrade_safely(
    ocr_runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    blank = ocr_runtime_dir / "blank.png"
    Image.new("RGB", (800, 400), "white").save(blank)
    blank_result = ingest_files([blank], backends=[OcrEngineBackend(timeout_seconds=30)])
    assert blank_result.extractions[0].error_code == "OCR_EMPTY"
    assert blank_result.extractions[0].needs_manual is True and not blank_result.normalized

    damaged = ocr_runtime_dir / "damaged.jpg"
    damaged.write_bytes(b"not-a-real-jpeg")
    damaged_result = ingest_files([damaged], backends=[OcrEngineBackend(timeout_seconds=30)])
    assert damaged_result.extractions[0].error_code == "OCR_IMAGE_DAMAGED"
    assert damaged_result.extractions[0].needs_manual is True and not damaged_result.normalized

    readable = _write_image(
        ocr_runtime_dir / "low-confidence.png",
        ["material_id,material_name", "MAT-LOW,低置信度样本"],
        "PNG",
    )
    low_result = ingest_files(
        [readable], backends=[OcrEngineBackend(timeout_seconds=30, min_confidence=1.0)]
    )
    assert low_result.extractions[0].error_code == "OCR_LOW_CONFIDENCE"
    assert low_result.extractions[0].needs_manual is True and not low_result.normalized

    timeout_result = ingest_files(
        [readable], backends=[OcrEngineBackend(timeout_seconds=0.1, min_confidence=0.0)]
    )
    assert timeout_result.extractions[0].error_code == "OCR_TIMEOUT"
    assert timeout_result.extractions[0].needs_manual is True and not timeout_result.normalized

    from src import ingestion_agent

    original_find_spec = ingestion_agent.importlib.util.find_spec
    monkeypatch.setattr(
        ingestion_agent.importlib.util,
        "find_spec",
        lambda name: None if name in {"rapidocr", "onnxruntime"} else original_find_spec(name),
    )
    missing_result = ingest_files([readable], backends=[OcrEngineBackend()])
    assert missing_result.extractions[0].error_code == "OCR_ENGINE_UNAVAILABLE"
    assert missing_result.extractions[0].needs_manual is True and not missing_result.normalized


def test_csv_and_pdf_text_layer_do_not_load_ocr(ocr_runtime_dir: Path, monkeypatch: pytest.MonkeyPatch):
    csv_path = ocr_runtime_dir / "unaffected.csv"
    csv_path.write_text("material_id,material_name\nMAT-CSV,CSV物料\n", encoding="utf-8")

    from reportlab.pdfgen import canvas

    pdf_path = ocr_runtime_dir / "text-layer.pdf"
    document = canvas.Canvas(str(pdf_path))
    document.drawString(72, 760, "material_id,material_name")
    document.drawString(72, 730, "MAT-PDF,PDF material")
    document.save()

    def ocr_must_not_run(self, _path):
        raise AssertionError("CSV/PDF 文本层不应调用 OCR")

    monkeypatch.setattr(OcrEngineBackend, "extract", ocr_must_not_run)
    csv_result = ingest_files([csv_path])
    pdf_result = ingest_files([pdf_path])
    assert csv_result.extractions[0].method_used == "direct"
    assert pdf_result.extractions[0].method_used == "text_layer"
    assert csv_result.ok_count == pdf_result.ok_count == 1


def test_real_ocr_api_preflight_mapping_execute_poll_and_tenant_visibility(
    ocr_runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    seed()
    client = TestClient(app)
    with SessionLocal() as db:
        lead = db.get(User, "u-scm_lead")
        auth = {"Authorization": f"Bearer {create_tokens(lead)['token']}"}

    monkeypatch.chdir(ocr_runtime_dir)
    material_id = f"MAT-OCR-{uuid.uuid4().hex[:8].upper()}"
    image = _image_bytes(
        ["物料编码,物料名称,成本", f"{material_id},中英文OCR芯片,12.50"],
        "PNG",
    )
    uploaded = client.post(
        "/api/v1/imports/upload?type=material&mode=ocr",
        headers=auth,
        files={"file": ("materials_scan.png", image, "image/png")},
    )
    assert uploaded.status_code == 201
    job_id = uploaded.json()["id"]

    preflight = client.post(f"/api/v1/imports/{job_id}/preflight", headers=auth)
    assert preflight.status_code == 200
    preflight_body = preflight.json()
    assert preflight_body["status"] == "manual_review"
    assert preflight_body["result"]["canProceed"] is True
    assert preflight_body["result"]["extraction"]["method_used"] == "rapidocr_local"
    assert preflight_body["result"]["extraction"]["column_count"] == 3
    preview = preflight_body["result"]["normalized"]["previewRows"]
    assert preview and preview[0]["物料编码"] == material_id

    garbled_uploaded = client.post(
        "/api/v1/imports/upload?type=material&mode=ocr",
        headers=auth,
        files={"file": ("garbled_materials.png", _image_bytes(
            ["????,????,??", "MAT-GARBLED-001,??????,12.50"], "PNG"
        ), "image/png")},
    )
    assert garbled_uploaded.status_code == 201
    garbled_preflight = client.post(
        f"/api/v1/imports/{garbled_uploaded.json()['id']}/preflight", headers=auth
    )
    assert garbled_preflight.status_code == 200
    garbled_body = garbled_preflight.json()
    assert garbled_body["status"] == "manual_required"
    assert garbled_body["result"]["canProceed"] is False
    assert garbled_body["result"]["extraction"]["error_code"] == "OCR_GARBLED_TEXT"
    assert "疑似乱码" in garbled_body["result"]["message"]
    assert garbled_body["result"]["manualReview"]["suggestions"] == [
        "重新上传清晰、端正且保留表头和列分隔符的图片",
        "改用 CSV/Excel 上传，或人工录入",
    ]

    confirmed = client.post(
        f"/api/v1/imports/{job_id}/confirm",
        headers=auth,
        json={"values": {
            "confirmedType": "material",
            "manualConfirmed": True,
            "fieldMapping": {"物料编码": "material_id", "物料名称": "material_name", "成本": "standard_cost"},
        }},
    )
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    executed = client.post(f"/api/v1/imports/{job_id}/execute", headers=auth)
    assert executed.status_code == 202

    deadline = time.monotonic() + 15
    polled = None
    while time.monotonic() < deadline:
        polled = client.get(f"/api/v1/imports/{job_id}", headers=auth)
        assert polled.status_code == 200
        if polled.json()["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert polled is not None and polled.json()["status"] == "succeeded"
    assert polled.json()["result"]["successRows"] == 1

    materials = client.get("/api/v1/data/material", headers=auth)
    assert materials.status_code == 200
    assert any(row["id"] == material_id and row["name"] == "中英文OCR芯片" for row in materials.json()["data"])

    other_phone = f"138{uuid.uuid4().int % 10**8:08d}"
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "phone": other_phone,
            "password": "ocr-tenant-test-password",
            "companyName": "OCR 隔离租户",
            "industry": "制造",
            "scale": "small",
            "ownerRole": "供应链负责人",
        },
    )
    assert registered.status_code == 201
    other_auth = {"Authorization": f"Bearer {registered.json()['token']}"}
    other_materials = client.get("/api/v1/data/material", headers=other_auth)
    assert other_materials.status_code == 200
    assert material_id not in {row["id"] for row in other_materials.json()["data"]}

    with SessionLocal() as db:
        entity = db.scalar(select(Material).where(Material.material_id == material_id))
        assert entity is not None and entity.tenant_id == "tenant-demo"
        assert db.scalar(
            select(Material).where(Material.tenant_id != "tenant-demo", Material.material_id == material_id)
        ) is None
