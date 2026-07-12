from __future__ import annotations

import os
import sqlite3
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_DB = (
    PROJECT_ROOT
    / "demo_assets"
    / "enterprise"
    / "database"
    / "chainguard_enterprise_demo.db"
)


_TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def get_connection(url: str | None = None, tenant_id: str = "default") -> sqlite3.Connection:
    """
    Return a database connection selected by URL.

    - None reads DATABASE_URL, then falls back to the enterprise SQLite demo DB.
    - sqlite:///path opens SQLite and sets row_factory to sqlite3.Row.
    - postgresql://... (or postgresql+psycopg://...) opens psycopg with dict rows.
    """
    tenant_id = _normalize_tenant_id(tenant_id)
    database_url = url or os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE_DB}"
    if database_url.startswith("sqlite:///"):
        path = database_url.removeprefix("sqlite:///")
        resolved_path = _sqlite_path_for_tenant(Path(path), tenant_id)
        if not resolved_path.exists():
            raise ValueError(f"未知租户: {tenant_id}")
        connection = sqlite3.connect(resolved_path)
        connection.row_factory = sqlite3.Row
        return connection

    if database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise ImportError(
                "PostgreSQL DATABASE_URL requires the optional psycopg package. "
                "Install it with: pip install 'psycopg[binary]>=3'."
            ) from exc
        # psycopg 只认 postgresql:// scheme;剥离 SQLAlchemy 风格的 +psycopg 驱动后缀
        conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        connection = psycopg.connect(
            conninfo,
            row_factory=dict_row,
            connect_timeout=int(os.getenv("DATABASE_CONNECT_TIMEOUT", "3")),
        )  # type: ignore[assignment]
        if tenant_id != "default":
            schema_name = f"tenant_{tenant_id}"
            with connection.cursor() as cursor:
                cursor.execute(f"SET search_path TO {schema_name}")
        return connection  # type: ignore[return-value]

    raise ValueError(
        "Unsupported DATABASE_URL scheme. Use sqlite:///path, "
        "postgresql://... or postgresql+psycopg://..."
    )


def _normalize_tenant_id(tenant_id: str | None) -> str:
    normalized = (tenant_id or "default").strip() or "default"
    if not _TENANT_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"未知租户: {normalized}")
    return normalized


def _sqlite_path_for_tenant(path: Path, tenant_id: str) -> Path:
    if tenant_id == "default":
        return path
    return path.with_name(f"{path.stem}.{tenant_id}{path.suffix}")
