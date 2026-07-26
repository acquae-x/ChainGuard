"""ERP 字段映射编辑 UI 的后端契约。

覆盖查看、编辑、校验失败、保存后被真实同步使用、权限与跨租户隔离；
不改动已验收的 C2 映射边界、ERP 最小集成或 OCR 行为。
"""

from __future__ import annotations

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.webapi.auth import AuthContext
from src.webapi.auth.security import require_permission
from src.webapi.database import Base
from src.webapi.entity_mapping import activate_tenant_config
from src.webapi.erp_mapping_config import (
    MAPPING_CONFIG_TYPE,
    baseline_mapping,
    mapping_view,
    resolve_mapping,
    review,
)
from src.webapi.errors import ApiError
from src.webapi.models import Material, TenantConfig, Tenant
from src.webapi.routers import imports_settings
from src.webapi.schemas import PatchRequest


class _MockErp(BaseHTTPRequestHandler):
    expected_token = "erp-mapping-token"

    def _send(self, code: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.headers.get("Authorization") != f"Bearer {self.expected_token}":
            self._send(401, {"error": "unauthorized"}); return
        if self.path == "/health":
            self._send(200, {"status": "ok"}); return
        if self.path == "/api/v1/catalog":
            self._send(200, {"resources": [{"resource": "materials", "record_count": 1}]}); return
        if self.path.startswith("/api/v1/materials"):
            # `erp_desc` is the alternative name column the tenant remaps onto material_name.
            self._send(200, {"items": [{
                "material_id": "ERP-MAT",
                "material_name": "默认名称",
                "erp_desc": "租户映射名称",
                "standard_cost": 12.5,
            }], "total": 1}); return
        self._send(404, {"error": "not_found"})

    def log_message(self, *_args):
        return


@pytest.fixture
def erp_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockErp)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown(); thread.join(timeout=2); server.server_close()


@pytest.fixture
def mapping_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([Tenant(id="tenant-a", name="A"), Tenant(id="tenant-b", name="B")])
        db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def admin_a():
    return AuthContext("admin-a", "tenant-a", "实施管理员 A", "admin", ("settings:manage", "data:import", "data:view"))


@pytest.fixture
def admin_b():
    return AuthContext("admin-b", "tenant-b", "实施管理员 B", "admin", ("settings:manage", "data:import", "data:view"))


def _remapped_material_name(source: str = "erp_desc") -> dict:
    """Baseline with material_name taken from a different ERP source column."""
    spec = copy.deepcopy(baseline_mapping())
    fields = spec["resources"]["material"]["fields"]
    fields.pop("material_name", None)
    fields[source] = "material_name"
    return spec


def _save_erp_connection(db: Session, ctx: AuthContext, base_url: str) -> None:
    imports_settings.save_erp_integration_settings(
        PatchRequest(values={"baseUrl": base_url, "apiKey": _MockErp.expected_token,
                             "connectionParams": {"timeoutSeconds": 2, "pageSize": 50}}), ctx, db,
    )


def test_view_defaults_to_shipped_file_and_groups_by_entity(mapping_db, admin_a):
    view = imports_settings.get_erp_mapping(admin_a, mapping_db)
    assert view["source"] == "file" and view["version"] is None
    assert view["usable"] is True and view["degraded"] is False and view["errors"] == []
    material = next(item for item in view["resources"] if item["resourceType"] == "material")
    assert material["targetTable"] == "materials" and material["unknownColumns"] == "extra"
    assert material["businessKeys"] == ["material_id"]
    key_row = next(row for row in material["rows"] if row["targetField"] == "material_id")
    assert key_row["sourceField"] == "material_id" and key_row["required"] is True and key_row["businessKey"] is True
    cost_row = next(row for row in material["rows"] if row["targetField"] == "unit_cost")
    assert cost_row["kind"] == "convert" and cost_row["sourceField"] == "standard_cost" and cost_row["convertType"] == "float"
    assert "material_name" in {column["name"] for column in material["targetColumns"]}
    assert "tenant_id" not in {column["name"] for column in material["targetColumns"]}


def test_save_creates_versioned_tenant_mapping_and_reset_returns_to_file(mapping_db, admin_a):
    first = imports_settings.put_erp_mapping(PatchRequest(values={"spec": _remapped_material_name()}), admin_a, mapping_db)
    assert first["source"] == "tenant" and first["version"] == 1 and first["updatedBy"] == "实施管理员 A"
    assert first["usable"] is True

    second = imports_settings.put_erp_mapping(PatchRequest(values={"spec": _remapped_material_name("erp_desc")}), admin_a, mapping_db)
    assert second["version"] == 2
    active = mapping_db.scalars(select(TenantConfig).where(
        TenantConfig.tenant_id == "tenant-a", TenantConfig.config_type == MAPPING_CONFIG_TYPE, TenantConfig.is_active.is_(True))).all()
    assert len(active) == 1 and active[0].version == 2

    back_to_file = imports_settings.reset_erp_mapping_endpoint(admin_a, mapping_db)
    assert back_to_file["source"] == "file" and back_to_file["version"] is None
    spec, meta = resolve_mapping(mapping_db, "tenant-a")
    assert meta["source"] == "file" and spec["resources"]["material"]["fields"]["material_name"] == "material_name"


def test_structural_duplicate_and_required_violations_block_the_save(mapping_db, admin_a):
    unknown_target = copy.deepcopy(baseline_mapping())
    unknown_target["resources"]["material"]["fields"]["material_name"] = "not_a_column"
    with pytest.raises(ApiError) as unknown_error:
        imports_settings.put_erp_mapping(PatchRequest(values={"spec": unknown_target}), admin_a, mapping_db)
    assert unknown_error.value.status_code == 422 and unknown_error.value.code == "CG-2811"
    assert "not_a_column" in unknown_error.value.message

    duplicated = copy.deepcopy(baseline_mapping())
    duplicated["resources"]["material"]["fields"]["another_source"] = "material_name"
    problems = review(duplicated)["errors"]
    assert any("mapped more than once" in problem for problem in problems)
    with pytest.raises(ApiError):
        imports_settings.put_erp_mapping(PatchRequest(values={"spec": duplicated}), admin_a, mapping_db)

    missing_required = copy.deepcopy(baseline_mapping())
    missing_required["resources"]["material"]["required"] = []
    with pytest.raises(ApiError) as required_error:
        imports_settings.put_erp_mapping(PatchRequest(values={"spec": missing_required}), admin_a, mapping_db)
    assert "must be required" in required_error.value.message

    # None of the three rejected drafts may persist.
    assert mapping_db.scalar(select(TenantConfig).where(TenantConfig.tenant_id == "tenant-a")) is None
    assert imports_settings.get_erp_mapping(admin_a, mapping_db)["source"] == "file"


def test_validate_endpoint_separates_blocking_errors_from_dangerous_warnings(mapping_db, admin_a):
    dangerous = copy.deepcopy(baseline_mapping())
    dangerous["sensitive_columns"] = [name for name in dangerous["sensitive_columns"] if name != "bank_account"]
    dangerous["resources"]["order_line"]["forbidden_columns"] = []
    dangerous["resources"]["material"]["unknown_columns"] = "reject"
    dangerous["resources"]["material"]["fields"].pop("material_id")
    dangerous["resources"]["material"]["fields"]["legacy_code"] = "material_id"
    dangerous["resources"]["material"]["required"] = ["legacy_code"]
    dangerous["resources"]["material"]["source_key"] = "legacy_code"

    verdict = imports_settings.validate_erp_mapping(PatchRequest(values={"spec": dangerous}), admin_a)
    assert verdict["valid"] is True and verdict["errors"] == []
    joined = " | ".join(verdict["warnings"])
    assert "bank_account" in joined
    assert "order_amount" in joined
    assert "reject" in joined
    assert "material_id" in joined and "legacy_code" in joined

    # Warnings never block: the operator may still save a dangerous-but-valid mapping.
    saved = imports_settings.put_erp_mapping(PatchRequest(values={"spec": dangerous}), admin_a, mapping_db)
    assert saved["source"] == "tenant" and saved["warnings"]


def test_saved_mapping_actually_drives_the_next_sync_and_is_traceable(mapping_db, admin_a, erp_server, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", "phase5b-erp-mapping-key")
    _save_erp_connection(mapping_db, admin_a, erp_server)

    baseline_job = imports_settings.sync_saved_erp_integration(PatchRequest(values={"types": ["material"]}), admin_a, mapping_db)
    assert baseline_job["status"] == "succeeded"
    assert baseline_job["options"]["mappingSource"] == "file" and baseline_job["options"]["mappingVersion"] is None
    material = mapping_db.scalar(select(Material).where(Material.tenant_id == "tenant-a", Material.material_id == "ERP-MAT"))
    assert material.material_name == "默认名称"

    imports_settings.put_erp_mapping(PatchRequest(values={"spec": _remapped_material_name()}), admin_a, mapping_db)
    remapped_job = imports_settings.sync_saved_erp_integration(PatchRequest(values={"types": ["material"]}), admin_a, mapping_db)
    assert remapped_job["status"] == "succeeded"
    assert remapped_job["options"]["mappingSource"] == "tenant"
    assert remapped_job["options"]["mappingVersion"] == 1
    assert remapped_job["options"]["mappingUpdatedBy"] == "实施管理员 A"
    assert remapped_job["options"]["mappingUpdatedAt"]

    mapping_db.expire_all()
    material = mapping_db.scalar(select(Material).where(Material.tenant_id == "tenant-a", Material.material_id == "ERP-MAT"))
    assert material.material_name == "租户映射名称"
    # The now-unmapped source column must land in extra rather than disappear.
    assert material.extra.get("material_name") == "默认名称"

    history = imports_settings.import_history(admin_a, mapping_db)
    versions = [item["options"].get("mappingVersion") for item in history["data"]]
    assert 1 in versions and None in versions


def test_invalid_stored_mapping_fails_the_sync_instead_of_falling_back(mapping_db, admin_a, erp_server, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", "phase5b-erp-mapping-key")
    _save_erp_connection(mapping_db, admin_a, erp_server)

    corrupted = copy.deepcopy(baseline_mapping())
    corrupted["resources"]["material"]["fields"]["material_name"] = "not_a_column"
    activate_tenant_config(mapping_db, "tenant-a", MAPPING_CONFIG_TYPE, corrupted, source="expert", approved_by="实施管理员 A")
    mapping_db.commit()

    view = imports_settings.get_erp_mapping(admin_a, mapping_db)
    assert view["usable"] is False and view["degraded"] is True
    assert "not_a_column" in view["degradeReason"] and view["source"] == "tenant"

    with pytest.raises(ApiError) as blocked:
        imports_settings.sync_saved_erp_integration(PatchRequest(values={"types": ["material"]}), admin_a, mapping_db)
    assert blocked.value.status_code == 409 and blocked.value.code == "CG-2810"
    assert "not_a_column" in blocked.value.message and "v1" in blocked.value.message
    # No silent baseline fallback: nothing was written.
    assert mapping_db.scalar(select(Material).where(Material.tenant_id == "tenant-a")) is None


def test_mapping_requires_settings_manage_and_is_tenant_isolated(mapping_db, admin_a, admin_b):
    imports_settings.put_erp_mapping(PatchRequest(values={"spec": _remapped_material_name()}), admin_a, mapping_db)

    # Tenant B keeps the shipped baseline and cannot observe tenant A's override.
    view_b = imports_settings.get_erp_mapping(admin_b, mapping_db)
    assert view_b["source"] == "file" and view_b["updatedBy"] is None
    material_b = next(item for item in view_b["resources"] if item["resourceType"] == "material")
    assert {row["sourceField"] for row in material_b["rows"] if row["targetField"] == "material_name"} == {"material_name"}
    spec_b, meta_b = resolve_mapping(mapping_db, "tenant-b")
    assert meta_b["source"] == "file" and "erp_desc" not in spec_b["resources"]["material"]["fields"]

    # Tenant A's own view still shows its override.
    assert mapping_view(mapping_db, "tenant-a")["source"] == "tenant"

    importer = AuthContext("importer-a", "tenant-a", "只导入", "operator", ("data:import", "data:view"))
    gate = require_permission("settings:manage")
    with pytest.raises(ApiError) as denied:
        gate(importer)
    assert denied.value.status_code == 403
    for permission in ("data:import", "data:view", "risk:view"):
        with pytest.raises(ApiError):
            require_permission("settings:manage")(AuthContext("u", "tenant-a", "n", "operator", (permission,)))


def test_source_field_catalog_degrades_with_an_explicit_reason(mapping_db, admin_a, erp_server, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", "phase5b-erp-mapping-key")

    with pytest.raises(ApiError) as unsaved:
        imports_settings.erp_mapping_source_fields(admin_a, mapping_db, "material")
    assert unsaved.value.code == "CG-2803"

    _save_erp_connection(mapping_db, admin_a, erp_server)
    with pytest.raises(ApiError) as untested:
        imports_settings.erp_mapping_source_fields(admin_a, mapping_db, "material")
    assert untested.value.code == "CG-2813" and "尚未通过测试" in untested.value.message

    imports_settings.test_saved_erp_integration(admin_a, mapping_db)
    catalog = imports_settings.erp_mapping_source_fields(admin_a, mapping_db, "material")
    names = {field["name"]: field for field in catalog["fields"]}
    assert catalog["sampledRows"] == 1
    assert names["material_id"]["mapped"] is True
    assert names["erp_desc"]["mapped"] is False and names["erp_desc"]["sample"] == "租户映射名称"
