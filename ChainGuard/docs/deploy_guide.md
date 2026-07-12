# ChainGuard 部署指南

## 前置条件

准备 Docker Engine 24+ 与 Docker Compose v2。仓库根目录必须同时包含 `ChainGuard/`（API）和 `chainguard-web/`（前端）；compose 文件位于 `ChainGuard/docker-compose.yml`，前端由该文件以相邻目录作为构建上下文。

## 首次部署

1. 进入 `ChainGuard`，复制环境变量模板：`cp .env.example .env`。
2. 在 `.env` 设置 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`JWT_SECRET` 和 `SEED_DEMO_PASSWORD`。这些值没有默认值，禁止提交 `.env`。
3. 生产 HTTPS 反向代理场景将 `REFRESH_COOKIE_SECURE=true`，并将 `CORS_ORIGINS` 改为实际前端域名；仅本机 HTTP 调试保持 `false`。
4. 启动：`docker compose up -d --build`。
5. 检查一次性迁移和初始化数据：`docker compose logs migrate`；服务应显示 Alembic 成功和演示数据初始化信息。
6. 打开 `http://localhost:8080` 访问前端。API 健康检查 `/healthz` 位于后端根路径，未经 nginx `/api/` 反代暴露（`/api/` 保留 URI 转发到 `api:8000/api/...`，故 `http://localhost:8080/api/healthz` 会 404，此为预期）。健康状态由 compose 在内网直连探测（`api:8000/healthz`），用 `docker compose ps` 查看 `api` 是否 `healthy`；如需手动探活可用 `docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read())"`。使用 `.env` 中的 `SEED_DEMO_PASSWORD` 与 `scm_lead@chainguard.demo` 完成风险、事件、方案、审批和任务演练；用 `admin@chainguard.demo` 验证导入。

`migrate` 仅在启动编排时执行迁移和幂等 seed，`api` 只有在其成功后才启动。API 使用 4 个 Uvicorn worker，可通过 `API_WORKERS` 调整。

## 数据库与备份

PostgreSQL 只暴露在 compose 内部网络，持久卷为 `pgdata`。`postgres-backup` 每天 02:00（由 `TZ` 控制）执行 `pg_dump`，压缩文件输出到 `ChainGuard/backups/postgres/`，并清除 7 天以前的备份。

恢复示例：`gunzip -c backups/postgres/chainguard_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"`。恢复前请先停止 API 写入并备份当前数据。

## 升级与排障

代码升级后执行 `docker compose up -d --build`；迁移由 `migrate` 自动串行执行。查看状态用 `docker compose ps`，查看 API 日志用 `docker compose logs -f api`。若迁移失败，修正环境或数据库连接后运行 `docker compose run --rm migrate`，不要手工修改 Alembic 版本表。
