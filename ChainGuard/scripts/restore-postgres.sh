#!/bin/sh
# Restore one logical backup. It drops and recreates POSTGRES_DB, so it is guarded.
set -eu

usage() {
    echo "用法：CHAINGUARD_RESTORE_CONFIRM=DESTROY_AND_RESTORE $0 /backups/chainguard_YYYYmmdd_HHMMSS.sql.gz" >&2
    exit 64
}

[ "$#" -eq 1 ] || usage
[ "${CHAINGUARD_RESTORE_CONFIRM:-}" = "DESTROY_AND_RESTORE" ] || {
    echo "拒绝恢复：必须设置 CHAINGUARD_RESTORE_CONFIRM=DESTROY_AND_RESTORE。" >&2
    exit 64
}

backup_file=$1
[ -f "$backup_file" ] || {
    echo "恢复失败：找不到备份文件 $backup_file" >&2
    exit 66
}

case "$POSTGRES_DB" in
    postgres|template0|template1|'')
        echo "恢复失败：POSTGRES_DB 不能是 PostgreSQL 系统数据库。" >&2
        exit 64
        ;;
esac

pg_host=${PGHOST:-postgres}
pg_port=${PGPORT:-5432}
export PGPASSWORD="$POSTGRES_PASSWORD"

gzip -t "$backup_file"
restore_sql=$(mktemp "${TMPDIR:-/tmp}/chainguard-restore.XXXXXX.sql")
cleanup() {
    rm -f "$restore_sql"
}
trap cleanup EXIT HUP INT TERM

# Do not stream decompression into psql: POSIX sh has no pipefail, so an I/O
# failure in gzip could otherwise leave psql with a truncated but successful
# input stream.  Materialize only after gzip exits successfully.
gzip -cd "$backup_file" > "$restore_sql"

# PostgreSQL 16's dropdb --force terminates active connections and passes the
# database name as an argument, avoiding unsafe SQL identifier interpolation.
dropdb -h "$pg_host" -p "$pg_port" -U "$POSTGRES_USER" --force "$POSTGRES_DB"
createdb -h "$pg_host" -p "$pg_port" -U "$POSTGRES_USER" "$POSTGRES_DB"

psql -h "$pg_host" -p "$pg_port" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 < "$restore_sql"
echo "PostgreSQL 恢复完成：$backup_file"
