#!/bin/sh
set -eu

backup_dir=/backups
timestamp=$(date +%Y%m%d_%H%M%S)
target="$backup_dir/chainguard_$timestamp.sql.gz"

mkdir -p "$backup_dir"
export PGPASSWORD="$POSTGRES_PASSWORD"
pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip > "$target"
# 保留最近七天；失败备份不会影响已有文件。
find "$backup_dir" -type f -name 'chainguard_*.sql.gz' -mtime +6 -delete
echo "PostgreSQL 备份完成：$target"
