# Phase 3 交付材料

交付日期：2026-07-12。

## 本阶段变更

| 文件 | 说明 |
|---|---|
| `ChainGuard/docker-compose.yml` | 全栈服务编排：PostgreSQL、一次性迁移+seed、4 worker API、Nginx 前端和每日备份。数据库、JWT、演示账号密码均要求由 `.env` 注入。 |
| `ChainGuard/Dockerfile`、`.dockerignore` | Python 多阶段构建，wheel 离线安装、非 root `appuser` 运行；不复制 `demo_assets/`。 |
| `chainguard-web/Dockerfile`、`nginx.conf`、`.dockerignore` | Node 构建前端，非 root Nginx 产物服务，`/api/` 反代至 API。 |
| `ChainGuard/scripts/postgres-backup.Dockerfile`、`backup-postgres.sh` | 02:00 cron 执行 gzip `pg_dump`，保留最近 7 天。 |
| `ChainGuard/.env.example`、`.gitignore`、`chainguard-web/.gitignore`、根 `.gitignore` | 补充无默认密码的环境模板与 `dist`、`.umi*`、`*.db-journal` 等运行/构建产物忽略规则。 |
| `.github/workflows/ci.yml` | 工作区单仓模式的后端 Ruff+pytest 和前端 tsc+build CI。 |
| `ChainGuard/.github/workflows/backend-ci.yml`、`chainguard-web/.github/workflows/frontend-ci.yml` | 两个目录独立建仓时可直接使用的 CI 工作流。 |
| `ChainGuard/docs/deploy_guide.md` | 从 `.env` 到启动、健康检查、备份恢复和升级排障的部署说明。 |
| `ChainGuard/src/webapi/routers/auth.py`、`schemas/__init__.py` | 真实企业注册、刷新令牌 HttpOnly Cookie 轮换及注销 Cookie 清理。 |
| `ChainGuard/src/webapi/auth/security.py`、`seed.py`、`auth/__init__.py` | 资料域读取授权；管理员明确业务只读码；既有演示库 seed 时同步内置角色权限。 |
| `ChainGuard/src/webapi/routers/imports_settings.py`、`business.py` | 导入 `confirm` 状态机和显式强制继续；通知已读用户隔离和持久化；审计日志按新到旧排序。 |
| `chainguard-web/src/services/user.ts`、`data.ts`、`approval.ts` | 注册接真实 API，导入携带 `force`，修复 CI 类型检查。 |
| `ChainGuard/tests/conftest.py`、`tests/test_webapi.py`、`tests/test_deployment.py` | 新增注册、Cookie、权限、导入状态机、通知持久化测试，并更新部署断言到 Phase 3 架构。 |

## 新增或变更 API

| 方法与路径 | 权限 | 请求示例 | 响应要点 |
|---|---|---|---|
| `POST /api/v1/auth/register` | 公开 | `{phone,password,companyName,industry,scale,ownerRole}` | `201` 返回 access token、`currentUser`、`tenant`；刷新令牌仅写 HttpOnly Cookie。 |
| `POST /api/v1/auth/login` | 公开 | `{account,password}` | 不再返回 `refreshToken`；写入 HttpOnly、SameSite=Lax、限定 `/api/v1/auth` 的刷新 Cookie。 |
| `POST /api/v1/auth/refresh` | 刷新 Cookie | `{}` | 读取并轮换 HttpOnly Cookie，返回新的 access token。请求体中不能提交刷新令牌。 |
| `GET /api/v1/data/{resourceType}` | `data:view`、全域 `data:manage` 或该资源的 `data:{type}:manage` | `/data/supplier` | 按资料域返回分页数据；仅导出权限不能读取全量资料。 |
| `POST /api/v1/imports/{id}/confirm` | `data:import` | `{values:{force:true}}` | 仅 `preflighted` 可确认；`failed` 必须显式 `force:true`；其他状态返回 `409`。 |
| `POST /api/v1/notifications/{id}/read` | 已登录且为目标用户 | `{}` | 已读状态提交到数据库；其他用户的专属通知返回 `404`。 |

## 终审后端跟进项处理

1. `data:view`：改为资源域读权限；`buyer` 仅能读供应商，不能读取物料等其他域。管理员补齐 `data:view`、`decision:view`、`task:view`、`report:view`，但**不**补 `readonly`，避免管理员写操作被前端隐藏。
2. 通知已读：`notification_messages.read` 已在数据库提交；增加跨用户访问拒绝和刷新读取测试。
3. imports confirm：已实现 `uploaded → preflighted → confirmed → pending/running/succeeded|failed`，失败预检须显式 `force`。
4. refresh token：响应 JSON 不再携带刷新令牌，登录和刷新都会旋转 HttpOnly Cookie；Cookie 的 `Secure` 由 `REFRESH_COOKIE_SECURE` 控制。
5. Phase 2 的 API 模式角色切换混用风险：注册/登录后的 API 会话不再依赖演示角色切换，注册服务直接签发真实租户 access token。

## 验证原文

在 `ChainGuard/` 运行：

```text
$ python -m ruff check src/webapi tests/test_webapi.py --ignore E701,E702
All checks passed!

$ python -m pytest tests/test_webapi.py tests/test_deployment.py -q ...
........................                                                 [100%]
24 passed, 1 warning in 1.80s

$ alembic upgrade head  # DATABASE_URL=sqlite:///./phase3_migration_verify.db
INFO  [alembic.runtime.migration] Running upgrade  -> 20260711_0001, 初始业务表迁移：使用显式 Alembic 操作创建全部 Phase 1 表。
alembic_version,approvals,audit_logs,custom_fields,data_records,experience_cards,import_jobs,incidents,jobs,notification_messages,proposals,risks,roles,tasks,tenants,users
```

在 `chainguard-web/` 运行：

```text
$ npm exec tsc -- --noEmit
Exit code: 0

$ npm run build
√ Webpack: Compiled successfully
generated .../chainguard-web/docs/route-access-map.md
```

## 已知限制与待执行验收

- 当前执行环境没有 `docker` 和 `psql` 命令，因此**未能在此机器实际启动 PostgreSQL 容器**，也未能声称“真实 PostgreSQL 迁移、浏览器全链路、CI PR 全绿”已经完成。SQLite 的 Alembic 全表迁移已验证；真实 PostgreSQL 的明确验收命令为：`cd ChainGuard && cp .env.example .env`（填好机密）后执行 `docker compose up -d --build`、`docker compose logs migrate`、浏览器完成注册→导入→演练。
- 曾运行全量 `pytest -q`：结果为 `450 passed, 4 failed, 38 errors`，并在约 160 秒超时。失败与错误集中在当前 Windows 工作区既有 `.tmp/pytest` 和 `data/` 目录的 `WinError 5` 权限清理，以及旧版部署断言；本阶段部署断言已更新，目标性 24 项测试通过。Linux CI 的干净工作目录不复现该 Windows 文件锁问题，但仍应以 CI 结果为准。
- 当前工作区的 Git 仓库位于 `ChainGuard/`，而 `chainguard-web/` 与根 `.github/` 不在该 Git 根下。为支持两种仓库布局，已同时提供工作区级 CI 和两个目录独立 CI；正式提交前需确认实际远端采用单仓还是双仓，并提交对应工作流文件。

## 新增 backlog（Phase 4 加固，仅登记不实现）

- **刷新令牌服务端吊销 / 重用检测**：当前刷新令牌轮换基于无状态 JWT，旧 refresh token 在到期前仍有效，无服务端吊销或重用检测。企业级加固可加 `jti` 白名单或重用检测。来源：Phase 3 评审报告「新增 backlog」。本次仅登记，不在 Phase 3 实现。

## 修复记录（Phase 3 评审打回，2026-07-12）

按 `codex_landing_spec/04_Phase3_评审报告.md`「打回指令」修复缺陷 1（阻断）、2、3；未触碰评审报告「核验通过项」覆盖的内容；「新增 backlog」（refresh token 吊销）仅登记未实现。

### 变更文件清单

| 文件 | 变更 |
|---|---|
| `ChainGuard/Dockerfile` | 缺陷1。在 `COPY src ./src` 后增加 `COPY --chown=appuser:appgroup config ./config` 与 `COPY --chown=appuser:appgroup data ./data`，保持 `appuser:appgroup` 属主；后续 `chown -R appuser:appgroup /app` 保证 data 可写。 |
| `ChainGuard/.dockerignore` | 缺陷1。移除整体排除的 `data/`（否则 `COPY data ./data` 会因构建上下文缺失而失败），改为仅排除运行时生成的审计日志 `data/audit_log*.jsonl`；`config/` 本就未被忽略。 |
| `ChainGuard/docker-compose.yml` | 缺陷1。为 `api` 服务的 `/app/data` 挂命名卷 `appdata`（保持容器内审计/经验卡 jsonl 可写并持久化；命名卷首建时以镜像内 `data/` 内容初始化），并在 `volumes:` 声明 `appdata`。 |
| `ChainGuard/tests/test_deployment.py` | 缺陷1。新增 `test_dockerfile_includes_config_and_data`（断言镜像 COPY config 与 data）、`test_dockerignore_does_not_exclude_data_dir`（断言未整体排除 data/）、`test_compose_mounts_writable_data_volume`（断言 `appdata:/app/data` 挂卷）。 |
| `ChainGuard/src/db.py` | 缺陷2。`get_connection` 的 Postgres 分支识别 `postgresql://` 与 `postgresql+psycopg://` 两种前缀；连接前将 `postgresql+psycopg://` 归一化为 psycopg 可识别的 `postgresql://`；同步更新 docstring 与不支持 scheme 的报错文案。 |
| `ChainGuard/docs/deploy_guide.md` | 缺陷3。修正健康检查说明：`/healthz` 在后端根路径，经 nginx `/api/` 保留 URI 转发到 `api:8000/api/healthz` 故 404（预期）；改为用 `docker compose ps` 看 `api` healthy，或 `docker compose exec api` 内网直连 `127.0.0.1:8000/healthz` 手动探活。选择「改文档」而非「nginx 加 /healthz」，因 nginx `/api/` 反代属评审「核验通过项」，避免改动其覆盖内容。 |
| `codex_landing_spec/phase3_交付材料.md` | 登记 Phase 4 backlog（refresh token 吊销/重用检测，仅登记不实现）+ 本修复记录。 |

### pytest 运行结果

**未能执行。** 本会话的隔离 Linux 沙盒 VM 反复启动失败，`mcp__workspace__bash` 多次返回原始错误：

```text
Workspace unavailable. The isolated Linux environment failed to start
(VM service not running. The service failed to start.).
```

因此 `python -m pytest tests/test_webapi.py tests/test_deployment.py -q` **未实际运行**，本节不提供任何伪造的测试输出（遵守「禁止声称任何未实际执行的验证」）。

已做的替代性静态核对（非等价于跑测试，仅确认新增断言与被测文件字符串一致）：Dockerfile 含两条 `COPY ... config ./config` / `COPY ... data ./data`；`.dockerignore` 逐行 strip 后不含 `data` 或 `data/`；compose 含 `appdata:/app/data` 且 `volumes:` 已声明 `appdata`；compose 仍含 `postgresql+psycopg` 且不含 `POSTGRES_PASSWORD:-`（既有 `test_compose_uses_nginx_and_multi_worker_api_without_default_password` 不回归）。

**已补验收（2026-07-12，用户本机 PowerShell 实际执行）：**

```text
PS D:\github_projects\Chainguard\ChainGuard> python -m pytest tests/test_webapi.py tests/test_deployment.py -q
.........................                                                [100%]
27 passed in 1.80s
```

27 = 原 24 项 + 本次新增 3 条部署断言，全部通过。pytest 待补项闭环。
