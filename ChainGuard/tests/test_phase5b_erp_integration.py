from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.webapi.auth import AuthContext
from src.webapi.database import Base
from src.webapi.errors import ApiError
from src.webapi.models import ErpIntegrationConfig, Material, Tenant
from src.webapi.routers import imports_settings
from src.webapi.schemas import PatchRequest


class _MockErp(BaseHTTPRequestHandler):
    expected_token = "erp-test-token"

    def _send(self, code: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.headers.get("Authorization") != f"Bearer {self.expected_token}":
            self._send(401, {"error": "unauthorized"}); return
        if self.path == "/health": self._send(200, {"status": "ok"}); return
        if self.path == "/api/v1/catalog": self._send(200, {"resources": [{"resource": "materials", "record_count": 1}]}); return
        if self.path.startswith("/api/v1/materials"):
            self._send(200, {"items": [{"material_id": "ERP-MAT", "material_name": "ERP material", "standard_cost": 12.5}], "total": 1}); return
        self._send(404, {"error": "not_found"})

    def log_message(self, *_args):
        return


@pytest.fixture
def erp_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockErp)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown(); thread.join(timeout=2); server.server_close()


@pytest.fixture
def integration_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([Tenant(id="tenant-a", name="A"), Tenant(id="tenant-b", name="B")]); db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def admin_context():
    return AuthContext("admin-a", "tenant-a", "ERP admin", "admin", ("settings:manage", "data:import", "data:view"))


def _save(db: Session, ctx: AuthContext, base_url: str, token: str = "erp-test-token"):
    return imports_settings.save_erp_integration_settings(
        PatchRequest(values={"baseUrl": base_url, "apiKey": token, "connectionParams": {"timeoutSeconds": 2, "pageSize": 50}}), ctx, db,
    )


def test_saved_erp_config_health_catalog_sync_history_and_tenant_isolation(integration_db, admin_context, erp_server, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", "phase5b-erp-test-key")
    saved = _save(integration_db, admin_context, erp_server)
    assert saved["credentialConfigured"] is True and "erp-test-token" not in str(saved)
    ciphertext = integration_db.scalar(select(ErpIntegrationConfig.credential_ciphertext).where(ErpIntegrationConfig.tenant_id == "tenant-a"))
    assert ciphertext and "erp-test-token" not in ciphertext

    checked = imports_settings.test_saved_erp_integration(admin_context, integration_db)
    assert checked["lastTestStatus"] == "available"
    assert checked["availableResources"] == [{"resource": "materials", "recordCount": 1}]

    result = imports_settings.sync_saved_erp_integration(PatchRequest(values={"types": ["material"]}), admin_context, integration_db)
    assert result["status"] == "succeeded" and result["successRows"] == 1
    assert integration_db.scalar(select(Material).where(Material.tenant_id == "tenant-a", Material.material_id == "ERP-MAT")) is not None
    history = imports_settings.import_history(admin_context, integration_db)
    assert history["total"] == 1 and history["data"][0]["options"]["types"] == ["material"]

    tenant_b = AuthContext("admin-b", "tenant-b", "B", "admin", ("settings:manage", "data:import"))
    assert imports_settings.erp_integration_settings(tenant_b, integration_db)["configured"] is False
    assert imports_settings.import_history(tenant_b, integration_db)["total"] == 0


def test_erp_auth_and_network_failures_are_safe_and_recorded(integration_db, admin_context, erp_server, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", "phase5b-erp-test-key")
    _save(integration_db, admin_context, erp_server, "wrong-token")
    with pytest.raises(ApiError) as auth_failed:
        imports_settings.test_saved_erp_integration(admin_context, integration_db)
    assert auth_failed.value.code == "CG-2804" and "认证失败" in auth_failed.value.message and "wrong-token" not in auth_failed.value.message
    item = integration_db.scalar(select(ErpIntegrationConfig).where(ErpIntegrationConfig.tenant_id == "tenant-a"))
    assert item.last_test_status == "unavailable" and item.last_test_error == "认证失败，请检查凭证"

    _save(integration_db, admin_context, "http://127.0.0.1:1")
    with pytest.raises(ApiError) as network_failed:
        imports_settings.test_saved_erp_integration(admin_context, integration_db)
    assert network_failed.value.code == "CG-2804" and network_failed.value.message in {"ERP 服务不可用或连接配置不正确", "ERP 服务响应超时"}


def test_erp_credential_refused_when_encryption_unavailable(integration_db, admin_context, erp_server, monkeypatch):
    """fail-closed 的落点：密钥缺失时保存必须被拒，且库里不能留下任何凭证痕迹。

    改造前 encrypt_bytes 会原样返回明文，这条路径靠调用侧"密文 == 明文"的等值比较
    兜底；该分支此前无任何测试覆盖。现在由 EncryptionUnavailable 保证。
    """
    monkeypatch.delenv("CHAINGUARD_ENCRYPTION_KEY", raising=False)

    with pytest.raises(ApiError) as refused:
        _save(integration_db, admin_context, erp_server, "plaintext-must-not-persist")

    assert refused.value.status_code == 503 and refused.value.code == "CG-2802"
    stored = integration_db.scalar(select(ErpIntegrationConfig).where(ErpIntegrationConfig.tenant_id == "tenant-a"))
    assert stored is None or "plaintext-must-not-persist" not in str(stored.credential_ciphertext)
