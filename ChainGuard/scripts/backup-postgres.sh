#!/bin/sh
set -eu

backup_dir=/backups
timestamp=$(date +%Y%m%d_%H%M%S)
target="$backup_dir/chainguard_$timestamp.sql.gz"
appdata_target="$backup_dir/chainguard_appdata_$timestamp.tar.gz"
# 校准注册表与导入暂存落在 .workspace，与 appdata 同属丢了不可重建的业务状态。
workspace_target="$backup_dir/chainguard_workspace_$timestamp.tar.gz"

mkdir -p "$backup_dir"
export PGPASSWORD="$POSTGRES_PASSWORD"
pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip > "$target"
tar -C /appdata -czf "$appdata_target" .
tar -C /workspace -czf "$workspace_target" .
# 保留最近七天；失败备份不会影响已有文件。
find "$backup_dir" -type f -name 'chainguard_*.sql.gz' -mtime +6 -delete
find "$backup_dir" -type f -name 'chainguard_appdata_*.tar.gz' -mtime +6 -delete
find "$backup_dir" -type f -name 'chainguard_workspace_*.tar.gz' -mtime +6 -delete
echo "PostgreSQL、appdata 与 workspace 备份完成：$target；$appdata_target；$workspace_target"
