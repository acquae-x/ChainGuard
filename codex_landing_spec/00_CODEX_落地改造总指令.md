# 00 CODEX 落地改造总指令（先读本文件）

## 背景与目标

仓库现状：`ChainGuard/`（Python/FastAPI 决策引擎，仅 7 个演示端点）与 `chainguard-web/`（UmiJS Max 前端，services 层全部走内存 mock `workflowStore.ts`）**互不通信**。本次任务是把两端真正打通，交付一个可部署给真实企业使用的系统，不是演示。

三个阶段按顺序交付，每阶段独立可验收、可运行。**禁止跳阶段、禁止半成品提交。**

冲突裁决顺序：本文件 > `codex_frontend_spec/02`（权限矩阵）> `chainguard-web/src/services/*.ts` 现有函数签名 > 其他文档。

## 硬性约束

- 后端：Python 3.11+，FastAPI + SQLAlchemy 2.x + Alembic + Pydantic v2。禁止引入 Django/Flask。
- 前端：沿用现有 UmiJS Max + antd Pro，网络层用 `@umijs/max` 自带 request。禁止 axios、禁止 redux。
- 不得删除或破坏现有决策引擎模块（`orchestrator.py`、`agents.py` 等）和现有 63 个测试。
- 不得把密钥、密码硬编码进代码或 compose 文件默认值；一律走 `.env`（提供 `.env.example`）。
- 全部新增代码必须有测试；注释与文档用中文。

## 统一契约（动手前先落实，两端共同遵守）

1. **API 前缀**：所有业务端点挂 `/api/v1`。现有 7 个演示端点保留原路径不动，标记 deprecated。
2. **JSON 命名**：API 边界一律 camelCase（Pydantic `alias_generator=to_camel`，`populate_by_name=True`）。
3. **错误信封**：所有非 2xx 返回 `{"code": "CG-xxxx", "message": "用户可读中文", "traceId": "..."}`。**500 禁止携带异常类名与内部消息**（修掉现有 `f"{type(error).__name__}: {error}"` 泄漏），详情只进日志。
4. **认证**：`POST /api/v1/auth/login`（账号+密码，bcrypt 存储）→ 返回 JWT（HS256，secret 走环境变量；预留 RS256 配置位）。前端带 `Authorization: Bearer`。刷新用 `POST /api/v1/auth/refresh`。
5. **角色模型统一为前端的 9 角色**（见 `codex_frontend_spec/02`），权限码与 `chainguard-web/src/access.ts` 的 permission code 一一对应，后端 `ROLE_PERMISSIONS` 据此重写。后端旧 4 角色（admin/operator/approver/viewer）废弃。
6. **多租户**：tenantId 来自 JWT claim，**不再信任 `X-Tenant-ID` 请求头**。所有业务表带 `tenant_id` 列，仓储层强制过滤。
7. **决策生成为异步作业**：`POST /api/v1/incidents/{id}/proposals:generate` → `202 {jobId}`；`GET /api/v1/jobs/{jobId}` 轮询。作业执行加 60s 超时与幂等键（同一 incident 进行中的作业不重复创建）。

## Phase 1：后端业务 API 层（工作量最大，先做）

### 1.1 结构

新增 `ChainGuard/src/webapi/`：`routers/`、`schemas/`、`repository/`、`auth/`、`jobs.py`、`errors.py`、`middleware.py`。`src/api.py` 保留旧端点并 include 新 router。

### 1.2 持久化

- SQLAlchemy 模型 + Alembic 迁移（初始迁移含全部业务表）。`DATABASE_URL` 决定 SQLite（开发）/ PostgreSQL（生产）。
- 业务表：tenants、users、roles、risks、incidents、proposals、approvals、tasks、audit_logs、experience_cards、import_jobs、notification_messages、custom_fields。
- 内置 seed 命令：`python -m src.webapi.seed` 生成演示租户 + 9 账号 + 一条完整 supplier_shutdown 数据链（与前端 mockData.ts 对齐）。

### 1.3 端点清单（以前端 services 为准逐个映射）

**逐个读取** `chainguard-web/src/services/*.ts` 与 `workflowStore.ts` 的每个导出函数，为其提供对应端点。核心资源：

| 资源 | 端点 | 说明 |
|---|---|---|
| auth | login/refresh/logout/me | JWT；me 返回 user+permissions+tenant |
| risks | GET 列表(分页/筛选)、GET 详情、PATCH 状态 | |
| incidents | CRUD + `POST /incidents`（由 riskIds 创建）| 状态机：`pending→planning→deciding→approving→executing→closed`，非法流转返回 409 |
| proposals | 列表/详情/PATCH（重算 overrides）/`:generate` 异步作业 | 生成时调用 `DecisionOrchestrator`，把 `DecisionResult` 映射为前端 `API.Proposal[]` 结构（3 方案+评分+约束+解释），映射函数单独成模块并单测 |
| approvals | 提交/通过/驳回/转办/撤回/加签 | 动作与 `workflowStore.ts` 中 approval 流转逐一对齐；高风险自动抄送 finance |
| tasks | 列表/详情/状态流转 | 审批通过后自动生成任务 |
| auditLogs | GET 分页查询（按人/按对象/按时间） | 所有写操作在同一事务内写审计 |
| imports | 上传→预检→确认→执行→进度 | 复用现有 `import_preflight.py`、`enterprise_ingest.py`、`streaming_import.py`、`intake_review.py`，不要重写这些模块 |
| dashboard | KPI/topRisks/myTasks/pendingApprovals | |
| notifications | 列表/已读 | `WebhookNotifier` 可配置真实 webhook |
| settings | users/roles CRUD、custom_fields | |

### 1.4 工业级要素（本阶段必须全部落地）

- `CORSMiddleware`（白名单走环境变量）。
- `/healthz` 免鉴权纯存活探针；`/readyz` 检查 DB 连通；旧 `/health` 保留鉴权版。
- traceId 中间件：每请求生成 traceId，注入日志与错误信封，响应头 `X-Trace-Id`。
- 限流：slowapi，登录接口单独更严（如 5 次/分钟）。
- 决策作业与导入作业用后台线程池 + 数据库作业表（状态 pending/running/succeeded/failed），**不引入 Celery/Redis**（当前规模不需要，留接口）。
- 结构化日志沿用 `observability.py`，补 request 访问日志；`/metrics` 增加 HTTP 层指标。
- `QwenLLMClient.generate` 修掉"配置了 key 反而 raise NotImplementedError"：接入 DashScope 真实调用，带 10s 超时、2 次重试、失败降级 MockLLM 并打日志。

### 1.5 Phase 1 验收

- `pytest` 全绿（含新增端点测试：鉴权、租户隔离、状态机非法流转、错误信封、审计写入）。
- `curl` 走通：login → 创建 incident → 生成方案(轮询 job) → 提交审批 → 通过 → 任务生成 → 审计可查。
- 500 响应体不含任何异常类名/堆栈。SQLite 与 Postgres 两种 DATABASE_URL 均可跑。

## Phase 2：前端接入真实后端

### 2.1 网络层

新增 `src/utils/request.ts`：基于 `@umijs/max` request 统一封装——超时 10s；错误信封解析并 `message.error`；401 清 token 跳登录；网络错误提示"服务暂不可用"；重试仅限幂等 GET（最多 2 次，指数退避）。

### 2.2 双数据源（这是降级设计的核心）

- 环境变量 `DATA_MODE=api|mock`（默认 api，`.env.development` 可切 mock）。
- 每个 service 文件改为：`api` 模式调真实端点，`mock` 模式走现有 `workflowStore`。**workflowStore 完整保留**，作为离线演示与后端不可用时的显式降级（页面顶部出黄条"当前为演示数据模式"，禁止静默降级）。
- proxy 修正：`/api` → `http://127.0.0.1:8000`（后端已带 `/api/v1` 前缀，无需 rewrite）。

### 2.3 认证与权限

- 登录页对接真实 login；token 存 cookie（HttpOnly 由后端 Set-Cookie 时预留，当前先前端可读 + SameSite=Lax）；`getInitialState` 调 `/auth/me`。
- `access.ts` 的 permission code 全部改为消费后端返回值，删除前端硬编码角色→权限推导。

### 2.4 Phase 2 验收

- `npm run build` 零 error；后端起着时 4 条核心流程真实数据走通；后端关掉时切 mock 模式仍可演示且有黄条提示。
- 9 账号真实登录，菜单/按钮/字段权限与 02 文档矩阵一致（后端返回 permissions 驱动）。
- 刷新页面业务数据不丢（已在数据库）。

## Phase 3：部署与工程化

- `docker-compose.yml` 重构为全栈：`web`（前端 build 产物 + nginx，反代 `/api` 到 api 服务）、`api`（uvicorn 多 worker，注入 DATABASE_URL/JWT_SECRET/CORS 白名单）、`postgres`、`migrate`（一次性 alembic upgrade）。移除 compose 内默认密码。
- Dockerfile：多阶段构建、非 root 用户运行、不 COPY `demo_assets/`（seed 按需挂载）。
- CI（GitHub Actions）：后端 ruff + pytest；前端 tsc + build；任一失败即红。
- `.gitignore` 补 `chainguard-web/dist`、`src/.umi*`、`*.db-journal`；仓库里已提交的这些产物删除。
- 备份：postgres-backup 服务改为 cron 每日一备 + 保留 7 份的脚本。
- 交付 `docs/deploy_guide.md`：一台裸机从 clone 到可访问的完整步骤。

### Phase 3 验收

- 全新机器 `docker compose up -d` 后浏览器可完成注册→导入→演练全流程。
- CI 在 PR 上运行且全绿。

## 提交物要求（供后续人工评审）

每个 Phase 完成后输出：①变更文件清单及每个文件一句话说明；②新增端点清单表（方法/路径/权限码/请求响应示例）；③测试运行结果原文；④已知限制与 TODO 列表。**不允许**在总结中声称完成了未实现的功能。
