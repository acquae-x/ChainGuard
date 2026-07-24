from __future__ import annotations

import importlib.util
import io
import os
import sqlite3
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.webapi.auth import AuthContext
from src.webapi.database import Base
from src.webapi.models import ImportJob, Incident, Risk, Tenant
from src.webapi.node_health import NodeHealthBuilder
from src.webapi.reports import executive_report
from src.webapi.routers.business import build_dashboard_kpis


ROOT = Path(__file__).resolve().parents[1]
TZ = timezone.utc


def _run_alembic(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
        text=True, capture_output=True, check=True,
    )


def _head_revision() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1
    return heads[0]


def _tenant(db: Session, tenant_id: str = "tenant-timezone") -> str:
    db.add(Tenant(id=tenant_id, name="Shanghai tenant", timezone="Asia/Shanghai"))
    db.flush()
    return tenant_id


@contextmanager
def _sqlite_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_migration_upgrade_downgrade_upgrade_preserves_existing_tenant_default(tmp_path: Path) -> None:
    database = tmp_path / f"tenant-timezone-{uuid.uuid4().hex}.db"
    try:
        _run_alembic(database, "upgrade", "20260720_0010")
        with sqlite3.connect(database) as connection:
            connection.execute(
                "INSERT INTO tenants (id, name, industry, scale, status, plan, trial_end_at, demo_data_flag) "
                "VALUES ('legacy-tenant', 'Legacy', 'manufacturing', 'small', 'active', 'trial', '', 0)"
            )
            connection.commit()

        _run_alembic(database, "upgrade", "head")
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT timezone FROM tenants WHERE id = 'legacy-tenant'"
            ).fetchone() == ("UTC",)
            assert "timezone" in {row[1] for row in connection.execute("PRAGMA table_info('tenants')")}

        _run_alembic(database, "downgrade", "20260720_0010")
        with sqlite3.connect(database) as connection:
            assert "timezone" not in {row[1] for row in connection.execute("PRAGMA table_info('tenants')")}

        _run_alembic(database, "upgrade", "head")
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT timezone FROM tenants WHERE id = 'legacy-tenant'"
            ).fetchone() == ("UTC",)
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (_head_revision(),)
    finally:
        try:
            database.unlink(missing_ok=True)
        except OSError:
            pass


def test_migration_postgresql_offline_ddl_supports_upgrade_and_downgrade() -> None:
    path = ROOT / "alembic" / "versions" / "20260723_0011_tenant_timezone.py"
    spec = importlib.util.spec_from_file_location("tenant_timezone_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    upgrade_output = io.StringIO()
    upgrade_context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": upgrade_output}
    )
    with Operations.context(upgrade_context):
        module.upgrade()
    assert "ADD COLUMN timezone VARCHAR(64) DEFAULT 'UTC' NOT NULL" in upgrade_output.getvalue()

    downgrade_output = io.StringIO()
    downgrade_context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": downgrade_output}
    )
    with Operations.context(downgrade_context):
        module.downgrade()
    assert "DROP COLUMN timezone" in downgrade_output.getvalue()


def test_shanghai_day_week_and_month_boundaries_use_tenant_calendar() -> None:
    with _sqlite_session() as db:
        tenant_id = _tenant(db, f"tenant-timezone-{uuid.uuid4().hex}")
        # 2026-02-02 is a Monday in Shanghai.  These two UTC instants are only one
        # hour apart, but lie on opposite local days/weeks/months as noted below.
        local_sunday_2330 = datetime(2026, 2, 1, 15, 30, tzinfo=TZ)  # 23:30 +08
        local_monday_0030 = datetime(2026, 2, 1, 16, 30, tzinfo=TZ)  # 00:30 +08
        now = datetime(2026, 2, 1, 16, 40, tzinfo=TZ)  # Monday 00:40 +08
        db.add_all([
            ImportJob(id=f"import-sunday-{tenant_id}", tenant_id=tenant_id, file_name="sun.csv", import_type="material", status="succeeded", progress=100, options={}, result={}, created_at=local_sunday_2330),
            ImportJob(id=f"import-monday-{tenant_id}", tenant_id=tenant_id, file_name="mon.csv", import_type="material", status="succeeded", progress=100, options={}, result={}, created_at=local_monday_0030),
            Risk(id=f"risk-sunday-{tenant_id}", tenant_id=tenant_id, code="R-SUN", level="high", type="supply", object_type="supplier", object_name="S", score=90, rule="r", found_at=local_sunday_2330.isoformat(), status="new", details={}, created_at=local_sunday_2330),
            Risk(id=f"risk-monday-{tenant_id}", tenant_id=tenant_id, code="R-MON", level="high", type="supply", object_type="supplier", object_name="S", score=90, rule="r", found_at=local_monday_0030.isoformat(), status="new", details={}, created_at=local_monday_0030),
        ])
        db.flush()

        context = AuthContext("u-timezone", tenant_id, "Timezone", "admin", ("*",))
        kpis = build_dashboard_kpis(db, context, now=now)
        assert kpis["timezone"] == "Asia/Shanghai"
        assert kpis["weeklyImports"] == 1
        assert kpis["todayRiskCount"] == 1

        # These are 23:30 on Jan 31 and 00:30 on Feb 1 in Shanghai.  The monthly
        # report must bucket them by that local calendar, not their UTC date.
        db.add_all([
            Incident(id=f"incident-jan-{tenant_id}", tenant_id=tenant_id, code="JAN", title="Jan", type="supply", level="high", status="closed", owner="", source_risk_ids=[], loss=10, cost=1, notes=[], created_at=datetime(2026, 1, 31, 15, 30, tzinfo=TZ)),
            Incident(id=f"incident-feb-{tenant_id}", tenant_id=tenant_id, code="FEB", title="Feb", type="supply", level="high", status="closed", owner="", source_risk_ids=[], loss=20, cost=2, notes=[], created_at=datetime(2026, 1, 31, 16, 30, tzinfo=TZ)),
        ])
        db.flush()
        report = executive_report(db, tenant_id, months=2, now=now)
        buckets = {row["month"]: row for row in report["series"]}
        assert report["window"]["timezone"] == "Asia/Shanghai"
        assert buckets["2026-01"]["avoidedLoss"] == 10
        assert buckets["2026-02"]["avoidedLoss"] == 20


def test_node_health_marks_generated_time_with_tenant_timezone() -> None:
    with _sqlite_session() as db:
        tenant_id = _tenant(db, f"tenant-node-timezone-{uuid.uuid4().hex}")
        payload = NodeHealthBuilder(db, tenant_id, now=datetime(2026, 2, 1, 16, 30, tzinfo=TZ)).build()
        assert payload["timezone"] == "Asia/Shanghai"
        assert payload["generatedAt"] == "2026-02-02T00:30:00+08:00"
