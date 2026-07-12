# ChainGuard Phase 1 提交物

> 完成范围：仅 Phase 1 后端业务 API 层；未修改 Phase 2/3。

## ① 变更文件清单

### 基础配置与迁移

- `ChainGuard/.env.example`：提供数据库、JWT、CORS、DashScope、Webhook 和 seed 环境变量模板。
- `ChainGuard/requirements.txt`：加入 SQLAlchemy、Alembic、PyJWT、bcrypt、slowapi 和 psycopg。
- `ChainGuard/alembic.ini`：Alembic 主配置。
- `ChainGuard/alembic/env.py`：从 `DATABASE_URL` 加载 SQLite/PostgreSQL 迁移环境。
- `ChainGuard/alembic/script.py.mako`：迁移脚本模板。
- `ChainGuard/alembic/versions/20260711_0001_initial.py`：创建全部 Phase 1 业务表和作业表。

### 原后端接入点

- `ChainGuard/src/api.py`：保留并标记旧端点 deprecated，接入 `/api/v1`、CORS、限流、错误处理、探针和 webhook 双开关。
- `ChainGuard/src/db.py`：为 PostgreSQL 连接补充可配置超时。
- `ChainGuard/src/llm_client.py`：接入 DashScope 兼容接口，含 10 秒超时、2 次重试和 Mock 降级。
- `ChainGuard/src/observability.py`：增加 HTTP 请求量和耗时指标。

### Web API 核心

- `ChainGuard/src/webapi/__init__.py`：声明企业业务 API 包。
- `ChainGuard/src/webapi/config.py`：集中读取数据库、JWT、CORS 等配置。
- `ChainGuard/src/webapi/database.py`：SQLAlchemy 2.x engine、session 和基类。
- `ChainGuard/src/webapi/models.py`：定义租户、用户、风险、事件、方案、审批、任务、审计、导入、通知等模型。
- `ChainGuard/src/webapi/errors.py`：统一 `CG-xxxx` 错误信封并屏蔽 500 内部信息。
- `ChainGuard/src/webapi/middleware.py`：注入 traceId、访问日志、响应头和 HTTP 指标。
- `ChainGuard/src/webapi/limits.py`：全局与登录接口限流配置。
- `ChainGuard/src/webapi/jobs.py`：线程池决策/导入作业、60 秒决策超时与幂等控制。
- `ChainGuard/src/webapi/proposal_mapper.py`：将 `DecisionResult` 映射为前端三方案结构。
- `ChainGuard/src/webapi/seed.py`：生成演示租户、9 个角色账号及 supplier_shutdown 数据链。
- `ChainGuard/src/webapi/auth/__init__.py`：导出认证入口。
- `ChainGuard/src/webapi/auth/security.py`：bcrypt、JWT、tenant claim 校验和权限依赖。
- `ChainGuard/src/webapi/schemas/__init__.py`：Pydantic v2 camelCase API 模型。
- `ChainGuard/src/webapi/repository/__init__.py`：导出仓储辅助函数。
- `ChainGuard/src/webapi/repository/base.py`：租户强制过滤、序列化和事务审计辅助函数。
- `ChainGuard/src/webapi/routers/__init__.py`：导出聚合路由。
- `ChainGuard/src/webapi/routers/router.py`：聚合 `/api/v1` 路由。
- `ChainGuard/src/webapi/routers/auth.py`：登录、刷新、登出、当前用户。
- `ChainGuard/src/webapi/routers/business.py`：风险、事件、方案、审批、任务、审计、看板和通知端点。
- `ChainGuard/src/webapi/routers/imports_settings.py`：导入、设置、基础资料、风险规则、报表和初始化端点。

### 测试

- `ChainGuard/tests/test_webapi.py`：覆盖鉴权、租户隔离、非法流转、错误信封、审计、映射、设置 CRUD 和基础资料。
- `ChainGuard/tests/test_api.py`：适配统一错误信封并增加 webhook 双开关测试。
- `ChainGuard/tests/test_llm_client.py`：覆盖 DashScope 成功、重试和降级路径。

原先已存在的 `app.py`、`data/audit_log.jsonl`、`.workspace/` 等用户改动未纳入本次修改；测试产生的数据库和日志已清理。

## ② 新增端点清单

所有响应均使用 camelCase；除公开端点外均从 JWT 获取 tenantId。

| 方法 | 路径 | 权限码 | 请求 / 响应示例 |
|---|---|---|---|
| GET | `/healthz` | 公开 | `→ {"status":"ok"}` |
| GET | `/readyz` | 公开 | `→ {"status":"ready"}` |
| POST | `/api/v1/auth/login` | 公开；5/min | `{account,password}` → `{token,refreshToken,currentUser,tenant}` |
| POST | `/api/v1/auth/refresh` | refresh token | `{refreshToken}` → `{token,refreshToken,expiresIn}` |
| POST | `/api/v1/auth/logout` | 已登录 | `→ 204` |
| GET | `/api/v1/auth/me` | 已登录 | `→ {currentUser,tenant}` |
| GET | `/api/v1/risks` | `risk:view` | `?level=high&pageSize=20` → `{data,total,success}` |
| GET | `/api/v1/risks/matrix` | `risk:view` | `→ [{name,value,level}]` |
| GET | `/api/v1/risks/{id}` | `risk:view` | `→ Risk` |
| PATCH | `/api/v1/risks/{id}/status` | `risk:manage*` | `{status,reason}` → `Risk` |
| GET/POST | `/api/v1/incidents` | `incident:view` / `risk:event:create` | `{riskIds,title?}` → `201 Incident` |
| GET/PATCH/DELETE | `/api/v1/incidents/{id}` | `incident:view` / `incident:manage` | `{status:"planning"}` → `Incident`；非法流转 `409` |
| GET | `/api/v1/incidents/{id}/impact` | `incident:view` | `→ {materials,orders,suppliers,inventory}` |
| GET | `/api/v1/incidents/{id}/timeline` | `incident:view` | `→ AuditLog[]` |
| GET | `/api/v1/incidents/{id}/draft` | `decision:view*` | `→ Proposal|null` |
| POST | `/api/v1/incidents/{id}/proposals:generate` | `decision:modify*` | `→ 202 {jobId,status}` |
| GET | `/api/v1/jobs/{jobId}` | 已登录、同租户 | `→ {status,progress,result,errorCode}` |
| GET | `/api/v1/proposals` | `decision:view*` | `?incidentId=...` → `{data,total,success}` |
| GET | `/api/v1/proposals/{id}` | `decision:view*` | `→ Proposal` |
| GET | `/api/v1/proposals/{id}/explanation` | `decision:view*` | `→ {proposalId,evidence,...}` |
| PATCH | `/api/v1/proposals/{id}` | `decision:modify*` | `{overrides:{totalCost:...}}` → `Proposal` |
| POST | `/api/v1/proposals/{id}/draft` | `decision:modify*` | `→ {proposalId,savedAt}` |
| POST | `/api/v1/proposals/{id}/submit` | `approval:*` | `→ Approval` |
| GET | `/api/v1/approvals` | `approval:*` | `?tab=pending|done|cc` → `{data,total}` |
| GET | `/api/v1/approvals/{id}` | `approval:*` | `→ {approval,proposal,chain,comparison}` |
| POST | `/api/v1/approvals/{id}/approve` | `approval:{riskLevel}` | `{reason?}` → `{ok,approval}` |
| POST | `/api/v1/approvals/{id}/reject` | `approval:{riskLevel}` | `{reason}` → `{ok,approval}` |
| POST | `/api/v1/approvals/{id}/recalc` | `approval:{riskLevel}` | `{reason}` → `{ok,approval}` |
| POST | `/api/v1/approvals/{id}/transfer` | `approval:{riskLevel}` | `{assignee}` → `{ok,approval}` |
| POST | `/api/v1/approvals/{id}/submit` | `approval:submit_high` | `→ {ok,approval}` |
| POST | `/api/v1/approvals/{id}/withdraw` | 原提交人 | `→ {ok,approval}` |
| POST | `/api/v1/approvals/{id}/countersign` | `approval:countersign` | `→ {ok,approval}` |
| GET | `/api/v1/tasks` | `task:view` 或 `task:execute` | `?scope=overdue` → `{data,total}` |
| GET | `/api/v1/tasks/{id}` | `task:view` 或 `task:execute` | `→ Task` |
| PATCH | `/api/v1/tasks/{id}` | `task:execute` | `{status,assignee}` → `Task` |
| POST | `/api/v1/tasks/{id}/urge` | `task:manage` | `→ {ok,message}` |
| GET | `/api/v1/audit-logs` | `audit:view` | `?userId=&targetType=&action=` → `{data,total}` |
| GET | `/api/v1/dashboard/kpis` | 已登录 | `→ {riskCount,pendingApprovals,myTasks,incidentCount}` |
| GET | `/api/v1/dashboard/top-risks` | 已登录 | `→ Risk[]` |
| GET | `/api/v1/dashboard/my-tasks` | 已登录 | `→ Task[]` |
| GET | `/api/v1/dashboard/pending-approvals` | 已登录 | `→ Approval[]` |
| GET | `/api/v1/dashboard/audit` | 已登录 | `→ AuditLog[]` |
| GET | `/api/v1/notifications` | 已登录 | `→ {data,unread}` |
| POST | `/api/v1/notifications/{id}/read` | 已登录 | `→ {ok,id}` |
| GET/PUT | `/api/v1/notifications/webhook-config` | `settings:manage` | `{enabled,url}` → `{enabled,url:"***"}` |
| POST | `/api/v1/imports/upload` | `data:import*` | multipart + `type` → `ImportJob` |
| POST | `/api/v1/imports/{id}/preflight` | `data:import*` | `→ {status,result}` |
| POST | `/api/v1/imports/{id}/confirm` | `data:import*` | `{values:{duplicatePolicy,...}}` → `ImportJob` |
| POST | `/api/v1/imports/{id}/execute` | `data:import*` | `→ 202 {jobId,status}` |
| GET | `/api/v1/imports/{id}` | `data:import*` | `→ {status,progress,result}` |
| GET | `/api/v1/imports` | `data:import*` | `→ {data}` |
| POST | `/api/v1/imports/{id}/rollback` | `data:import*` | `→ {ok,id}` |
| GET/POST | `/api/v1/settings/users` | `settings:manage` | `UserCreate` → `{ok,id}` |
| PATCH/DELETE | `/api/v1/settings/users/{id}` | `settings:manage` | `{status,roleId,...}` → `{ok,id}` / `204` |
| GET/POST | `/api/v1/settings/roles` | `settings:manage` | `{code,name,permissions}` → `{ok,id}` |
| PATCH/DELETE | `/api/v1/settings/roles/{id}` | `settings:manage` | 内置角色修改返回 `409`；自定义角色可更新/删除 |
| GET | `/api/v1/settings/departments` | 已登录 | `→ Department[]` |
| GET | `/api/v1/settings/tenant` | 已登录 | `→ Tenant` |
| GET/POST | `/api/v1/settings/custom-fields` | 已登录 / `settings:manage` | `?objectType=` / `FieldCreate` |
| DELETE | `/api/v1/settings/custom-fields/{id}` | `settings:manage` | `→ {ok,id}` |
| GET/POST | `/api/v1/data/{resourceType}` | `data:view` / `data:manage` | `{name,...}` → 持久化基础资料 |
| GET | `/api/v1/risk-rules` | 已登录 | `→ {data}` |
| PUT | `/api/v1/risk-rules/{id}` | `risk:manage*` | `{threshold,enabled}` → `{ok,id,...}` |
| GET | `/api/v1/reports/executive` | `report:executive` | `→ {netBenefit,riskCount,avgResponseHours}` |
| GET | `/api/v1/reports/operation` | `report:operation` | `→ {funnel,overdueRate}` |
| GET | `/api/v1/reports/response` | 任一 `report:*` | `→ {events}` |
| GET | `/api/v1/onboarding/templates` | 公开 | `→ Template[]` |
| POST | `/api/v1/onboarding/progress` | 已登录 | `Progress` → `{ok,progress}` |
| POST | `/api/v1/onboarding/templates/{id}/apply` | 已登录 | `→ {ok,tenant}` |

统一错误示例：

```json
{
  "code": "CG-2201",
  "message": "事件不能从pending流转到executing",
  "traceId": "0bfdac4b2b25417ea4581dda41e8b0fd"
}
```

## ③ 测试运行结果原文

最终全量回归：

```text
........................................................................ [ 15%]
........................................................................ [ 30%]
........................................................................ [ 45%]
........................................................................ [ 60%]
........................................................................ [ 75%]
........................................................................ [ 90%]
..............................................                           [100%]
============================== warnings summary ===============================
tests/test_model_comparison.py::test_compare_models_returns_six_results
tests/test_model_comparison.py::test_best_model_has_highest_f1_macro
tests/test_model_comparison.py::test_report_json_serializable
tests/test_model_comparison.py::test_prior_classifier_always_included
tests/test_model_comparison.py::test_svm_included_and_gaussian_nb_retained
tests/test_model_comparison.py::test_random_forest_has_feature_importance
tests/test_model_comparison.py::test_best_model_beats_prior_on_real_data
tests/test_model_comparison.py::test_best_model_not_overfit
  D:\Python313\Lib\site-packages\sklearn\svm\_base.py:239: FutureWarning: The `probability` parameter was deprecated in 1.9 and will be removed in version 1.11.
    warnings.warn(

tests/test_security.py::test_encrypt_degrades_without_lib
  D:\github_projects\Chainguard\ChainGuard\tests\test_security.py:91: RuntimeWarning: cryptography is not installed; encryption degraded to plaintext.
    result = encrypt_bytes(b"x")

478 passed, 9 warnings in 88.97s (0:01:28)
```

真实 curl 核心流程结果：

```json
{"login":"200","incidentId":"inc-d5958d9984ca48d09ded662cc952ab49","jobId":"job-fe7fa79222d44ad3804aec87eee2c88d","jobStatus":"succeeded","proposalCount":3,"approvalId":"ap-1a86cbd84930487c88096a456cd9ded6","approvalStatus":"approved","generatedTasks":5,"approvalAuditCount":2}
```

数据库验证：

```text
SQLite: alembic upgrade head 成功
PostgreSQL: 15 张表的 DDL 方言编译成功，alembic --sql 生成成功
```

## ④ 已知限制与 TODO

- PostgreSQL 已做驱动、模型和离线迁移验证，但当前环境没有可连接的真实 PostgreSQL 实例，尚未执行在线集成测试。
- DashScope 和 webhook 均已完成代码与 mock 测试；因未提供真实密钥和目标地址，本次未实际向外部服务发送数据。
- 后台作业使用进程内线程池；服务进程异常退出时，数据库中的 `pending/running` 作业需要后续增加启动恢复扫描。
- `dataScope=dept/custom` 已保留用户字段，当前后端强制实现的是 tenant 级隔离；部门、仓库、客户和供应商等更细粒度行权限仍需补充范围配置数据和查询策略。
- 基础资料目前使用统一 `data_records + JSON payload` 持久化；如后续需要复杂关联查询，应拆分为物料、供应商、客户、订单和库存专用表。
- 报表和 onboarding 模板中的部分展示值仍是固定模板数据；核心风险、事件、审批、任务和 KPI 已从数据库读取。
- refresh cookie 在本地开发配置下未强制 `Secure`；生产 HTTPS 部署时应启用。
- 9 个 seed 账号密码不硬编码，运行 seed 前必须设置 `SEED_DEMO_PASSWORD`。
