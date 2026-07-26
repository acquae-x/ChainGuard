"""Run the complete C2 enterprise import reconciliation on an isolated DB."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select


# Keep the documented direct entry point (``python scripts/...py``) working on
# Windows, where Python otherwise places only ``scripts/`` at sys.path[0].
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    database = args.database.resolve()
    default_database = (Path(__file__).resolve().parents[1] / "chainguard.db").resolve()
    print(f"TARGET_DATABASE={database}")
    print(f"DEFAULT_DATABASE={default_database}")
    print(f"CONFIRMED_NON_DEFAULT={database != default_database}")
    if database == default_database:
        raise RuntimeError("refusing to run acceptance against default chainguard.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    os.environ["CHAINGUARD_REQUIRE_GUID_DB"] = "1"
    os.environ["CHAINGUARD_DISABLE_SCHEDULER"] = "1"

    # Import DB-bound modules only after the validated absolute target is in
    # the environment. This prevents an omitted shell variable from silently
    # binding SessionLocal to the repository default database.
    from src.webapi.auth.security import hash_password
    from src.webapi.database import SessionLocal
    from src.webapi.entity_import import import_enterprise_directory
    from src.webapi.models import ImportJob, ImportRejection, ImportSourceRow, Role, Tenant, User
    from src.webapi.seed import BASE, ROLE_PERMISSIONS

    with sqlite3.connect(database) as raw:
        revision = raw.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    with SessionLocal() as db:
        tenant = Tenant(
            id=args.tenant_id,
            name="Phase 5B C2 隔离演示企业",
            industry="电子制造",
            scale="1000+",
            status="active",
            plan="acceptance",
            trial_end_at="",
            demo_data_flag=True,
        )
        role = Role(
            id=f"role-{args.tenant_id}",
            tenant_id=args.tenant_id,
            code="scm_lead",
            name="C2 验收管理员",
            builtin=False,
            permissions=[*BASE, *ROLE_PERMISSIONS["scm_lead"]],
        )
        user = User(
            id=f"user-{args.tenant_id}",
            tenant_id=args.tenant_id,
            account=args.account,
            password_hash=hash_password(args.password),
            name="C2 验收管理员",
            phone="",
            email=args.account,
            dept_id="dept-1",
            role_id=role.id,
            role_code=role.code,
            status="active",
            data_scope="all",
        )
        job = ImportJob(
            id=args.job_id,
            tenant_id=args.tenant_id,
            file_name="enterprise/csv",
            import_type="enterprise",
            status="running",
            progress=60,
            options={"enterpriseMode": True, "enterpriseDir": str(args.data_dir.resolve()), "operator": user.name},
            result={},
        )
        db.add(tenant)
        db.flush()
        db.add(role)
        db.flush()
        db.add_all([user, job])
        db.commit()

        result = import_enterprise_directory(db, args.tenant_id, args.job_id, args.data_dir)
        job.status = "succeeded"
        job.progress = 100
        job.result = result
        db.commit()

        persisted_source_rows = int(
            db.scalar(
                select(func.count()).select_from(ImportSourceRow).where(
                    ImportSourceRow.tenant_id == args.tenant_id,
                    ImportSourceRow.import_job_id == args.job_id,
                )
            )
            or 0
        )
        persisted_rejections = int(
            db.scalar(
                select(func.count()).select_from(ImportRejection).where(
                    ImportRejection.tenant_id == args.tenant_id,
                    ImportRejection.import_job_id == args.job_id,
                )
            )
            or 0
        )

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "database": str(database),
        "alembicRevision": revision,
        "tenantId": args.tenant_id,
        **result,
        "persistedSourceRows": persisted_source_rows,
        "persistedRejections": persisted_rejections,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
