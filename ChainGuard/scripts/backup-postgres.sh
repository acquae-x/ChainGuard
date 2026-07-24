#!/bin/sh
# Create a verified logical PostgreSQL backup. This runs in Compose and in the restore drill.
set -eu

umask 077

backup_dir=${BACKUP_DIR:-/backups}
timestamp=${BACKUP_TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}
pg_host=${PGHOST:-postgres}
pg_port=${PGPORT:-5432}
backup_app_state=${BACKUP_APP_STATE:-true}
target="$backup_dir/chainguard_$timestamp.sql.gz"
temporary_sql="$backup_dir/.chainguard_$timestamp.sql"
temporary_gzip="$backup_dir/.chainguard_$timestamp.sql.gz"

cleanup() {
    rm -f "$temporary_sql" "$temporary_gzip"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$backup_dir"
export PGPASSWORD="$POSTGRES_PASSWORD"

# Do not pipe pg_dump to gzip: POSIX sh has no pipefail guarantee, so a failed
# dump could otherwise be published as a valid-looking empty archive.
pg_dump -h "$pg_host" -p "$pg_port" -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$temporary_sql"
gzip -c "$temporary_sql" > "$temporary_gzip"
gzip -t "$temporary_gzip"
mv "$temporary_gzip" "$target"

if [ "$backup_app_state" = "true" ]; then
    appdata_target="$backup_dir/chainguard_appdata_$timestamp.tar.gz"
    workspace_target="$backup_dir/chainguard_workspace_$timestamp.tar.gz"

    tar -C /appdata -czf "$appdata_target" .
    tar -C /workspace -czf "$workspace_target" .
    echo "PostgreSQL、appdata 与 workspace 备份完成：$target；$appdata_target；$workspace_target"
else
    echo "PostgreSQL 备份完成：$target"
fi

# Retain seven days only after the new backup has been generated and verified.
find "$backup_dir" -type f -name 'chainguard_*.sql.gz' -mtime +6 -delete
find "$backup_dir" -type f -name 'chainguard_appdata_*.tar.gz' -mtime +6 -delete
find "$backup_dir" -type f -name 'chainguard_workspace_*.tar.gz' -mtime +6 -delete
