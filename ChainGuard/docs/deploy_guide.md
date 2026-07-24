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

## 多 worker 下的共享状态

多 worker 意味着任何"进程内状态"都会被复制 N 份，三处必须落在进程外：

- **限流计数桶**由 `redis` 服务承载，compose 默认注入 `RATE_LIMIT_STORAGE_URI=redis://redis:6379/0`。未配置该变量且数据库后端不是 SQLite 时，API **拒绝启动**——多 worker 下静默退回进程内计数等同于关闭限流（5/minute 会变成 `worker 数 × 5/minute`），宁可起不来也不带病上线。本地非容器开发用 SQLite 时自动退回 `memory://`，不需要起 Redis；确知单进程又用了非 SQLite 后端，显式设 `RATE_LIMIT_STORAGE_URI=memory://` 即可。
- **`.workspace` 卷**存租户校准注册表与导入暂存。它原本只存在于镜像层，容器重建即随镜像层消失，且代码会自动重建空注册表——故障形态是"漂移基线悄悄归零"而非报错。现由命名卷 `workspace` 持久化，并纳入每日备份。
- **遗留作业回收**：作业执行体与待执行队列都在进程内，worker 崩溃会留下永远停在 `pending` 或 `running` 的作业，而决策入队的去重条件恰好包含这两态，导致该事件再也无法重新发起决策。每个 worker 启动时会把超过 `JOB_RECOVERY_STALE_MINUTES`（默认 15）仍处于 `pending/running` 的作业判死为 `failed`，用户可直接重试。该逻辑用“状态 + `updated_at`”双守卫的条件 UPDATE 实现：四个 worker 同时执行也只会回收一次，候选扫描后刚被活跃 worker 推进的作业也不会被误杀。

## 数据库与备份

PostgreSQL 只暴露在 compose 内部网络，持久卷为 `pgdata`。`postgres-backup` 每天 02:00（由 `TZ` 控制）执行 `pg_dump`，压缩文件输出到 `ChainGuard/backups/postgres/`，并清除 7 天以前的备份。

手动立即备份使用 `docker compose run --rm postgres-backup /usr/local/bin/backup-postgres`。除数据库 SQL 备份外，脚本会同时生成 `chainguard_appdata_*.tar.gz`（决策引擎审计与经验卡所在的 `appdata` 卷）和 `chainguard_workspace_*.tar.gz`（租户校准注册表与导入暂存所在的 `workspace` 卷）。这两个卷与数据库同属丢失后不可重建的业务状态，备份范围必须一致。

Redis 只承载可重建的限流计数（键自带 TTL），不属于备份对象；其 `redisdata` 卷启用 AOF 只是为了避免重启瞬间出现一个完全不限流的窗口。

恢复示例：`gunzip -c backups/postgres/chainguard_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"`。恢复前请先停止 API 写入并备份当前数据。

## 离线安装

在可联网的构建机中，先执行 `powershell -ExecutionPolicy Bypass -File scripts/export-images.ps1`，将生成的 `chainguard-images.tar`、代码目录和已准备好的 `.env` 一并转移到目标内网服务器。目标服务器执行 `powershell -ExecutionPolicy Bypass -File scripts/import-images.ps1 -ImageArchive .\chainguard-images.tar`，再执行 `docker compose up -d`。离线包只解决镜像拉取；首次构建仍应在构建机完成，目标机不要使用 `--build`。

## TLS、容量与恢复目标

生产部署必须在 web 前置 TLS 反向代理（例如 Caddy 或 nginx），将证书终止在代理层并转发到 `web:8080`；此时设置 `REFRESH_COOKIE_SECURE=true` 与实际 HTTPS 域名的 `CORS_ORIGINS`。单机 compose 不是高可用方案：默认每日备份的 RPO 为 24 小时，RTO 取决于人工重启和备份恢复时间，不作固定承诺。若不能接受 24 小时数据窗口，应采用更高频备份或 PostgreSQL WAL 归档。

API 以 4 个 worker 运行，决策和普通作业线程池各 4 个；部署容量按约 4 个并发决策作业估算。compose 已为 API（2 CPU/2 GB）和 PostgreSQL（1 CPU/1 GB）设置基础限额，生产应按实际压测上调。

## 机密管理

`.env` 仅应由部署管理员读取（Windows 使用 NTFS ACL，Linux 使用 `chmod 600 .env`），不得提交到版本控制或复制到工单/聊天。轮换数据库密码后同步更新 `.env` 并重启服务。定期轮换 `POSTGRES_PASSWORD`、JWT 密钥与演示账户密码。

### JWT 密钥轮换（灰度窗口）

JWT 轮换采用“当前签发、当前和历史验签”模式。灰度窗口长度由系统所有者与安全负责人按**最长 JWT 有效期 + 时钟偏差 + 发布观察时间**确定；本系统的默认最长值由 `REFRESH_TOKEN_DAYS` 决定，不能只按 `ACCESS_TOKEN_MINUTES` 计算。疑似密钥泄露时不走灰度窗口：立即移除泄露密钥并使现有会话失效。

1. 生成新密钥，将现有 `JWT_SECRET` 移入 `JWT_SECRET_PREVIOUS`（多个历史值以逗号分隔），将新值写入 `JWT_SECRET`；RS256 则生成新密钥对，将新私钥写入 `JWT_RS256_PRIVATE_KEY`、将上一把公钥移入 `JWT_RS256_PUBLIC_KEY_PREVIOUS`，并将新公钥写入 `JWT_RS256_PUBLIC_KEY`。旧私钥不参与验签，无需保留。
2. 在所有实例上同时发布该配置并滚动重启。重启后新 token 只由当前签名密钥签发，旧 token 仍可由历史验签密钥验证。
3. 灰度窗口结束且最长可能存活的旧 token 全部过期后，从 `*_PREVIOUS` 删除对应旧值，再次滚动重启。被删除密钥签发的 token 必须被拒绝。

当前实现不使用 JWT `kid`：服务端按“当前、历史 1、历史 2…”尝试验签。这避免为内部 token 增加密钥标识、分发和撤销契约；未来若需要向外部验证方公开 RS256/JWKS，再引入 `kid`。

## 升级与排障

代码升级后执行 `docker compose up -d --build`；迁移由 `migrate` 自动串行执行。查看状态用 `docker compose ps`，查看 API 日志用 `docker compose logs -f api`。若迁移失败，修正环境或数据库连接后运行 `docker compose run --rm migrate`，不要手工修改 Alembic 版本表。
