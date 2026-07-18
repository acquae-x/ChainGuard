from __future__ import annotations

from collections.abc import Generator, Mapping
import os
from pathlib import Path
import re
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_PROJECT_DEFAULT_DATABASE = (Path(__file__).resolve().parents[2] / "chainguard.db").resolve()
_TRUE_VALUES = {"1", "true", "yes", "on"}
_GUID_PATTERN = re.compile(
    r"(?i)(?:^|[^0-9a-f])"
    r"(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"(?:[^0-9a-f]|$)"
)


def validate_database_target(database_url: str, environment: Mapping[str, str] | None = None) -> Path | None:
    """Fail closed before SQLAlchemy can connect to the repository default DB.

    Normal local use of ``chainguard.db`` now requires the explicit
    ``CHAINGUARD_ALLOW_DEFAULT_DB=1`` acknowledgement. Acceptance runs may
    additionally require an absolute GUID-named SQLite database by setting
    ``CHAINGUARD_REQUIRE_GUID_DB=1``.
    """

    env = os.environ if environment is None else environment
    allow_default = str(env.get("CHAINGUARD_ALLOW_DEFAULT_DB", "")).strip().lower() in _TRUE_VALUES
    require_guid = str(env.get("CHAINGUARD_REQUIRE_GUID_DB", "")).strip().lower() in _TRUE_VALUES
    explicit_url = str(env.get("DATABASE_URL", "")).strip()
    if not explicit_url and not allow_default:
        raise RuntimeError(
            "DATABASE_URL must be explicit; set CHAINGUARD_ALLOW_DEFAULT_DB=1 only for intentional default DB use"
        )

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.database in {None, "", ":memory:"}:
        return None

    raw_path = Path(str(url.database))
    resolved = raw_path.resolve() if raw_path.is_absolute() else (Path.cwd() / raw_path).resolve()
    if resolved == _PROJECT_DEFAULT_DATABASE and not allow_default:
        raise RuntimeError(
            f"refusing repository default database without CHAINGUARD_ALLOW_DEFAULT_DB=1: {resolved}"
        )
    if require_guid:
        if not raw_path.is_absolute():
            raise RuntimeError(f"acceptance SQLite database must use an absolute path: {raw_path}")
        if not _GUID_PATTERN.search(resolved.name):
            raise RuntimeError(f"acceptance SQLite database filename must contain a GUID: {resolved}")
    return resolved


validate_database_target(settings.database_url)
engine_kwargs = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
engine = create_engine(settings.database_url, **engine_kwargs)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        """SQLite disables FK enforcement unless every connection opts in."""
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

SessionLocal = sessionmaker(engine, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
