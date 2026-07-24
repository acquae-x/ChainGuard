#!/usr/bin/env bash
# End-to-end PostgreSQL restore drill: snapshot -> backup -> destroy -> restore -> compare.
set -euo pipefail

required=(POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD)
for name in "${required[@]}"; do
    [[ -n "${!name:-}" ]] || { echo "恢复后一致性校验失败：缺少 $name" >&2; exit 64; }
done

[[ "${CHAINGUARD_RESTORE_DRILL:-}" == "DESTROY_DATABASE" ]] || {
    echo "拒绝演练：必须设置 CHAINGUARD_RESTORE_DRILL=DESTROY_DATABASE。" >&2
    exit 64
}
if [[ "$POSTGRES_DB" != *test* && "$POSTGRES_DB" != *drill* && "${CHAINGUARD_ALLOW_NONTEST_RESTORE_DRILL:-}" != "1" ]]; then
    echo "拒绝演练：POSTGRES_DB 必须包含 test 或 drill；非测试库须额外设置 CHAINGUARD_ALLOW_NONTEST_RESTORE_DRILL=1。" >&2
    exit 64
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
pg_host=${PGHOST:-postgres}
pg_port=${PGPORT:-5432}
export PGPASSWORD="$POSTGRES_PASSWORD"
drill_dir=$(mktemp -d "${TMPDIR:-/tmp}/chainguard-restore-drill.XXXXXX")
before_snapshot="$drill_dir/before.snapshot"
after_snapshot="$drill_dir/after.snapshot"

cleanup() {
    rm -rf "$drill_dir"
}
trap cleanup EXIT

psql_cmd() {
    psql -X -h "$pg_host" -p "$pg_port" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 "$@"
}

snapshot_database() {
    local destination=$1 qualified_table count checksum
    : > "$destination"
    while IFS= read -r qualified_table; do
        [[ -n "$qualified_table" ]] || continue
        IFS='|' read -r count checksum < <(
            psql_cmd -Atq -F '|' -c "SELECT count(*), coalesce(md5(string_agg(md5(to_jsonb(row_data)::text), ',' ORDER BY md5(to_jsonb(row_data)::text))), md5('')) FROM $qualified_table AS row_data;"
        )
        printf '%s|%s|%s\n' "$qualified_table" "$count" "$checksum" >> "$destination"
    done < <(
        psql_cmd -Atq -c "SELECT format('%I.%I', namespace.nspname, relation.relname) FROM pg_class AS relation JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace WHERE relation.relkind IN ('r', 'p') AND namespace.nspname NOT IN ('pg_catalog', 'information_schema') AND namespace.nspname !~ '^pg_toast' ORDER BY 1;"
    )
}

# Make an empty migrated CI database a meaningful restore test, not schema-only.
psql_cmd -c 'DROP TABLE IF EXISTS backup_restore_drill_probe;'
psql_cmd -c 'CREATE TABLE backup_restore_drill_probe (id integer PRIMARY KEY, label text, payload jsonb, optional_note text);'
psql_cmd -c "INSERT INTO backup_restore_drill_probe VALUES (1, '中文 / quote '' / emoji ✅', '{\"nested\": {\"number\": 42}, \"items\": [\"a\", \"b\"]}', NULL), (2, 'second row', '{\"active\": true}', 'restorable');"

snapshot_database "$before_snapshot"
backup_timestamp=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$drill_dir" BACKUP_TIMESTAMP="$backup_timestamp" BACKUP_APP_STATE=false PGHOST="$pg_host" PGPORT="$pg_port" \
    sh "$script_dir/backup-postgres.sh"
backup_file="$drill_dir/chainguard_$backup_timestamp.sql.gz"

CHAINGUARD_RESTORE_CONFIRM=DESTROY_AND_RESTORE PGHOST="$pg_host" PGPORT="$pg_port" \
    sh "$script_dir/restore-postgres.sh" "$backup_file"
snapshot_database "$after_snapshot"

if cmp -s "$before_snapshot" "$after_snapshot"; then
    echo "恢复后一致性校验通过"
else
    echo "恢复后一致性校验失败" >&2
    diff -u "$before_snapshot" "$after_snapshot" >&2 || true
    exit 1
fi
