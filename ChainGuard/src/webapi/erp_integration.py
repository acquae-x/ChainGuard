"""Safe, tenant-scoped ERP integration configuration helpers for E01/E02."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.connectors.rest_connector import ErpConnectorError, RestErpConnector
from src.security.encryption import decrypt_bytes, encrypt_bytes, encryption_status

from .errors import ApiError
from .models import ErpIntegrationConfig


_SAFE_PARAMS = {"timeoutSeconds", "pageSize", "catalogPath"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _valid_base_url(value: Any) -> str:
    base_url = str(value or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiError(422, "CG-2801", "ERP 地址必须是有效的 http:// 或 https:// URL")
    return base_url


def _credential(values: dict[str, Any]) -> str | None:
    for key in ("apiKey", "token", "credential"):
        value = values.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _encrypt_credential(value: str) -> str:
    status = encryption_status()
    if not status["active"]:
        raise ApiError(503, "CG-2802", "凭证加密未启用，不能保存 ERP 凭证")
    encrypted = encrypt_bytes(value.encode("utf-8"))
    if encrypted == value.encode("utf-8"):
        raise ApiError(503, "CG-2802", "凭证加密不可用，不能保存 ERP 凭证")
    return base64.urlsafe_b64encode(encrypted).decode("ascii")


def _decrypt_credential(item: ErpIntegrationConfig) -> str:
    if not item.credential_ciphertext:
        return ""
    try:
        encrypted = base64.urlsafe_b64decode(item.credential_ciphertext.encode("ascii"))
        return decrypt_bytes(encrypted).decode("utf-8")
    except Exception as error:
        raise ApiError(503, "CG-2802", "ERP 凭证不可用，请重新配置") from error


def get_config(db: Session, tenant_id: str) -> ErpIntegrationConfig | None:
    return db.scalar(select(ErpIntegrationConfig).where(ErpIntegrationConfig.tenant_id == tenant_id))


def public_config(item: ErpIntegrationConfig | None) -> dict[str, Any]:
    if item is None:
        return {
            "configured": False, "credentialConfigured": False, "baseUrl": "",
            "connectionParams": {}, "lastTestStatus": "not_tested", "lastTestAt": None,
            "lastTestError": None, "availableResources": [],
        }
    return {
        "configured": True,
        "baseUrl": item.base_url,
        "credentialConfigured": bool(item.credential_ciphertext),
        "credentialMasked": "已配置" if item.credential_ciphertext else "未配置",
        "connectionParams": dict(item.connection_params or {}),
        "lastTestStatus": item.last_test_status,
        "lastTestAt": item.last_test_at.isoformat() if item.last_test_at else None,
        "lastTestError": item.last_test_error,
        "availableResources": list(item.available_resources or []),
    }


def save_config(db: Session, tenant_id: str, values: dict[str, Any]) -> ErpIntegrationConfig:
    base_url = _valid_base_url(values.get("baseUrl"))
    params_source = values.get("connectionParams") or {}
    if not isinstance(params_source, dict):
        raise ApiError(422, "CG-2801", "连接参数必须是对象")
    params = {key: params_source[key] for key in _SAFE_PARAMS if key in params_source}
    item = get_config(db, tenant_id)
    supplied = _credential(values)
    if item is None:
        item = ErpIntegrationConfig(
            id=f"erp-config-{uuid.uuid4().hex}", tenant_id=tenant_id, base_url=base_url,
            credential_ciphertext=_encrypt_credential(supplied) if supplied else None,
            connection_params=params,
        )
        db.add(item)
    else:
        item.base_url = base_url
        item.connection_params = params
        if supplied:
            item.credential_ciphertext = _encrypt_credential(supplied)
    db.flush()
    return item


def connector_for_config(item: ErpIntegrationConfig) -> RestErpConnector:
    params = item.connection_params or {}
    timeout = float(params.get("timeoutSeconds") or 8.0)
    page_size = int(params.get("pageSize") or 500)
    return RestErpConnector(item.base_url, api_key=_decrypt_credential(item), timeout=min(max(timeout, 1.0), 30.0), retries=1, page_size=page_size)


def safe_erp_error(error: Exception) -> str:
    message = str(error).lower()
    if "401" in message or "403" in message or "unauthorized" in message or "forbidden" in message:
        return "认证失败，请检查凭证"
    if "timed out" in message or "timeout" in message:
        return "ERP 服务响应超时"
    return "ERP 服务不可用或连接配置不正确"


def record_test_result(item: ErpIntegrationConfig, *, result: dict[str, Any] | None = None, error: Exception | None = None) -> None:
    item.last_test_at = _utcnow()
    if error is None:
        item.last_test_status = "available"
        item.last_test_error = None
        item.available_resources = list((result or {}).get("resources") or [])
    else:
        item.last_test_status = "unavailable"
        item.last_test_error = safe_erp_error(error)
        item.available_resources = []


__all__ = [
    "ErpConnectorError", "connector_for_config", "get_config", "public_config", "record_test_result",
    "safe_erp_error", "save_config",
]
