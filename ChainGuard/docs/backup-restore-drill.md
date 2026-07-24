# PostgreSQL backup and restore drill

`postgres-backup` creates a verified logical database backup at 02:00 each day (container `TZ`) in `./backups/postgres`. It validates the gzip archive before reporting success.

## Production database recovery

Stop API and migration processes first, select a specific backup, then run:

```sh
docker compose --profile maintenance run --rm \
  -e CHAINGUARD_RESTORE_CONFIRM=DESTROY_AND_RESTORE \
  postgres-restore /backups/chainguard_YYYYmmdd_HHMMSS.sql.gz
```

The command terminates database connections and drops then recreates `POSTGRES_DB`; the confirmation variable is an intentional second guard. Never run it against an uncertain database.

`appdata` and `workspace` are also backed up, but the automated command restores PostgreSQL only. A production incident that needs cross-volume recovery must restore matching volume snapshots and complete application-level acceptance before traffic is enabled.

## One-command database drill

The drill refuses to run unless its target database name contains `test` or `drill` and an explicit destructive confirmation is present:

```sh
CHAINGUARD_RESTORE_DRILL=DESTROY_DATABASE \
POSTGRES_DB=chainguard_test POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
PGHOST=127.0.0.1 bash scripts/backup-restore-drill.sh
```

It writes Unicode, NULL, quoted text, and JSON probe rows; records every application table's name, row count, and deterministic content digest; backs up; destroys the database; restores; and compares the two snapshots. It prints `恢复后一致性校验通过` on success, or `恢复后一致性校验失败` and exits non-zero on any discrepancy. The existing `backend-postgres` CI job runs this drill against its disposable PostgreSQL service.

## RPO/RTO conventions

RPO is measured from the completion time of the latest successful, verified logical backup to the failure time. With the daily schedule, the target is no more than 24 hours plus the time taken to finish a backup.

RTO is measured from running the guarded recovery command to the drill's all-table consistency check passing. The current objective is 30 minutes; update the operations runbook from each drill's measured duration.

The database dump and the two volume archives are not a cross-volume atomic snapshot. These RPO/RTO statements therefore do not claim cross-volume transactional consistency. Use storage snapshots or a maintenance-window write stop if that guarantee is required.
