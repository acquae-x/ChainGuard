# Phase 1 评审修复交付材料

修复依据：`codex_landing_spec/01_Phase1_评审报告.md`。

范围声明：本次只修评审报告列出的问题，未修改 Phase 2/3；未重写报告“做得对的地方”列出的租户隔离、错误信封/traceId、500 防泄漏、登录限流、bcrypt/JWT、seed 密码、幂等作业、事务审计和既有分层模块。

## ① 变更文件清单与说明

| 文件 | 本次评审修复 |
|---|---|
| `ChainGuard/.env.example` | 去除重复的 `WEBHOOK_REMOTE_ENABLED`，增加 `MAX_IMPORT_BYTES`。 |
| `ChainGuard/requirements.txt` | 核对并保留 `pdfplumber`、`psutil`，补全 `psycopg[binary]` 及可选用途注释。 |
| `ChainGuard/src/api.py` | 删除 import 阶段的 `Base.metadata.create_all(engine)`，启动时不再绕过 Alembic。 |
| `ChainGuard/src/webapi/config.py` | 增加导入文件最大字节数配置。 |
| `ChainGuard/src/webapi/schemas/__init__.py` | 事件创建支持显式传入 `type/loss/cost`，默认分别为 `manual/0/0`。 |
| `ChainGuard/src/webapi/jobs.py` | 将作业调度池和决策执行池分离，消除 4 个并发决策作业的线程池自死锁。 |
| `ChainGuard/src/webapi/proposal_mapper.py` | 明确标注前端缺失字段的序位兜底值为 MVP 占位。 |
| `ChainGuard/src/webapi/repository/base.py` | `serialize()` 增加字段白名单能力，默认仍隐藏账号和密码哈希。 |
| `ChainGuard/src/webapi/routers/business.py` | 去除事件演示硬编码；转办必须匹配本租户 active 用户。 |
| `ChainGuard/src/webapi/routers/imports_settings.py` | 管理员用户列表按需返回 account；上传限制为 csv/xlsx 且强制大小上限。 |
| `ChainGuard/alembic/versions/20260711_0001_initial.py` | 改为显式 `op.create_table/create_index/drop_table/drop_index`，不再调用 metadata.create_all/drop_all。 |
| `ChainGuard/tests/test_webapi.py` | 新增事件默认值、转办校验、账号字段、上传安全、4 作业并发和真实迁移结构测试。 |

### 截断文件核验

报告列出的 `src/api.py`、`src/db.py`、`src/observability.py`、`tests/test_api.py`、`src/webapi/auth/security.py`、`src/webapi/jobs.py`、`src/webapi/routers/imports_settings.py`、`src/llm_client.py` 在本次修复开始时实际均已有完整文件结尾。本次仍按报告逐个执行了：

```text
python -m py_compile src/api.py src/db.py src/observability.py tests/test_api.py src/webapi/auth/security.py src/webapi/jobs.py src/webapi/routers/imports_settings.py src/llm_client.py alembic/versions/20260711_0001_initial.py
Exit code: 0
```

### data/demo_assets 说明

- 本次开始时 `demo_assets/` 已无工作树 diff，本次没有修改。
- `data/audit_log.jsonl` 的 275 行增量在本次任务开始前已存在，属于用户既有改动，因此按工作区保护规则保留。
- 本次 pytest/curl 产生的 `data/audit_log.jsonl` 和 `data/model_registry.json` 新增记录已精确清理；未把验证 churn 留在工作树。

## ② 端点清单与契约变化

本次没有增加 Phase 2/3 端点，只修复以下既有 Phase 1 契约：

| 方法 | 路径 | 权限 | 修复后请求/响应示例 |
|---|---|---|---|
| POST | `/api/v1/incidents` | `risk:event:create` | `{ "riskIds": [], "type": "transport_delay", "loss": 123, "cost": 45 }`；不传时为 `manual/0/0`。 |
| POST | `/api/v1/approvals/{id}/transfer` | 对应风险等级审批权限 | `{ "assignee": "u-buyer" }`；非本租户或非 active 用户返回 `CG-2404`。 |
| GET | `/api/v1/settings/users` | `settings:manage` | 返回 `account`，继续禁止返回 `passwordHash`。 |
| POST | `/api/v1/imports/upload?type=...` | `data:import*` | 仅接受 `.csv/.xlsx`；超出 `MAX_IMPORT_BYTES` 返回 `413 CG-2604`。 |

迁移实测：

```text
alembic upgrade head
upgrade_tables= 15

alembic downgrade base
after_downgrade_tables= []
```

## ③ pytest 全量原始输出与 curl 链路记录

### pytest 原始命令

```powershell
python -m pytest tests/ -q
```

### pytest 完整原始输出

```text
........................................................................ [ 14%]
........................................................................ [ 29%]
........................................................................ [ 44%]
........................................................................ [ 59%]
........................................................................ [ 74%]
........................................................................ [ 89%]
....................................................                     [100%]
============================== warnings summary ===============================
tests/test_model_comparison.py::test_compare_models_returns_six_results
tests/test_model_comparison.py::test_best_model_has_highest_f1_macro
tests/test_model_comparison.py::test_report_json_serializable
tests/test_model_comparison.py::test_prior_classifier_always_included
tests/test_model_comparison.py::test_svm_included_and_gaussian_nb_retained
tests/test_model_comparison.py::test_random_forest_has_feature_importance
tests/test_model_comparison.py::test_best_model_beats_prior_on_real_data
tests/test_model_comparison.py::test_best_model_not_overfit
  D:\Python313\Lib\site-packages\sklearn\svm\_base.py:239: FutureWarning: The `probability` parameter was deprecated in 1.9 and will be removed in version 1.11. Use `CalibratedClassifierCV(SVC(), ensemble=False)` instead of `SVC(probability=True)`
    warnings.warn(

tests/test_security.py::test_encrypt_degrades_without_lib
  D:\github_projects\Chainguard\ChainGuard\tests\test_security.py:91: RuntimeWarning: cryptography is not installed; encryption degraded to plaintext.
    result = encrypt_bytes(b"x")

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
484 passed, 9 warnings in 87.36s (0:01:27)
```

### curl 运行环境

```powershell
$env:DATABASE_URL='sqlite:///.workspace/phase1_review_acceptance.db'
$env:SEED_DEMO_PASSWORD='<redacted>'
alembic upgrade head
python -m src.webapi.seed
python -m uvicorn src.api:app --host 127.0.0.1 --port 8012
```

以下记录来自实际 `curl.exe` 执行。密码、access token、refresh token 仅在材料中脱敏，其余业务响应保持本次原始值。

#### 1. 供应链负责人登录

```http
POST /api/v1/auth/login
Content-Type: application/json

{"account":"scm_lead@chainguard.demo","password":"<redacted>"}

HTTP 200
{"token":"<redacted>","refreshToken":"<redacted>","expiresIn":1800,"currentUser":{"id":"u-scm_lead","tenantId":"tenant-demo","name":"供应链负责人","phone":"13800000003","email":"scm_lead@chainguard.demo","deptId":"dept-3","roleIds":["role-scm_lead"],"roleCode":"scm_lead","status":"active","permissions":["dashboard:view","risk:view","incident:view","risk:event:create","risk:manage","decision:view","decision:modify","approval:low","approval:medium","approval:submit_high","task:execute","task:manage","data:manage","data:import","data:export","case:view","report:operation","settings:approval","field:cost:view","field:profit:view","field:contract:view","field:customerLevel:view","field:supplierPrice:view"],"dataScope":"all","readonly":false},"tenant":{"id":"tenant-demo","name":"华东精密制造有限公司","industry":"电子制造","scale":"200-1000","status":"active","plan":"trial","trialEndAt":"2026-08-10","demoDataFlag":true}}
```

#### 2. 创建事件

```http
POST /api/v1/incidents
Authorization: Bearer <redacted>
Content-Type: application/json

{"riskIds":["risk-1"]}

HTTP 201
{"code":"INC-20260711-4CCDFD","title":"苏州芯片封测厂风险应急事件","type":"manual","level":"high","status":"pending","owner":"供应链负责人","sourceRiskIds":["risk-1"],"loss":0,"cost":0,"notes":[],"id":"inc-de001abf756b47d3997e8fd5f9819700","tenantId":"tenant-demo","createdAt":"2026-07-11T13:47:27.417988+00:00"}
```

#### 3. 创建异步决策作业

```http
POST /api/v1/incidents/inc-de001abf756b47d3997e8fd5f9819700/proposals:generate
Authorization: Bearer <redacted>

HTTP 202
{"jobId":"job-4fdc1ffa22414888afe33c814010d4af","status":"pending"}
```

#### 4. 轮询作业完成

```http
GET /api/v1/jobs/job-4fdc1ffa22414888afe33c814010d4af
Authorization: Bearer <redacted>

HTTP 200
{"kind":"decision","resourceId":"inc-de001abf756b47d3997e8fd5f9819700","idempotencyKey":"decision:inc-de001abf756b47d3997e8fd5f9819700","status":"succeeded","progress":100,"result":{"proposalIds":["prop-e44d778fcacd468f8386883fb263e986","prop-2cb76bddbda54e3aadb8f9020a031b51","prop-21066550d69f406fa1981ed42fbf9951"],"count":3},"errorCode":null,"id":"job-4fdc1ffa22414888afe33c814010d4af","tenantId":"tenant-demo","createdAt":"2026-07-11T13:47:44.666209"}
```

#### 5. 提交审批

```http
POST /api/v1/proposals/prop-e44d778fcacd468f8386883fb263e986/submit
Authorization: Bearer <redacted>

HTTP 200
{"proposalId":"prop-e44d778fcacd468f8386883fb263e986","incidentId":"inc-de001abf756b47d3997e8fd5f9819700","status":"submitted","riskLevel":"high","summary":"采购 Agent","costImpact":0.0,"submitter":"供应链负责人","waitingHours":0,"ccRoleCodes":["finance"],"transferredTo":null,"countersigned":false,"history":[],"id":"ap-f583c412b69e46deac81155a879d574f","tenantId":"tenant-demo","createdAt":"2026-07-11T13:48:27.292948+00:00"}
```

#### 6. 老板批准

老板账号先通过 `/api/v1/auth/login` 实际登录，登录密码和 token 在材料中脱敏。

```http
POST /api/v1/approvals/ap-f583c412b69e46deac81155a879d574f/approve
Authorization: Bearer <redacted>
Content-Type: application/json

{}

HTTP 200
{"ok":true,"id":"ap-f583c412b69e46deac81155a879d574f","action":"approve","approval":{"proposalId":"prop-e44d778fcacd468f8386883fb263e986","incidentId":"inc-de001abf756b47d3997e8fd5f9819700","status":"approved","riskLevel":"high","summary":"采购 Agent","costImpact":0.0,"submitter":"供应链负责人","waitingHours":0.0,"ccRoleCodes":["finance"],"transferredTo":null,"countersigned":false,"history":[{"action":"approve","userId":"u-boss","reason":null,"time":"2026-07-11T21:48:48.858364"}],"id":"ap-f583c412b69e46deac81155a879d574f","tenantId":"tenant-demo","createdAt":"2026-07-11T13:48:27.292948"}}
```

#### 7. 查询自动生成任务

```http
GET /api/v1/tasks
Authorization: Bearer <redacted>

HTTP 200
{"data":[{"title":"锁定替代供应商订单","source":"INC-20260711-4CCDFD","incidentId":"inc-de001abf756b47d3997e8fd5f9819700","assignee":"采购人员","roleCode":"buyer","status":"pending","dueAt":"","priority":"高","checklist":[],"id":"task-fd61afda43834d64aaaf35dba996ffff","tenantId":"tenant-demo","createdAt":"2026-07-11T13:48:48.860011"},{"title":"安排关键物料加急运输","source":"INC-20260711-4CCDFD","incidentId":"inc-de001abf756b47d3997e8fd5f9819700","assignee":"供应链负责人","roleCode":"scm_lead","status":"pending","dueAt":"","priority":"高","checklist":[],"id":"task-5a189760b51d40af80b707ae9df55255","tenantId":"tenant-demo","createdAt":"2026-07-11T13:48:48.860012"},{"title":"通知受影响高等级客户","source":"INC-20260711-4CCDFD","incidentId":"inc-de001abf756b47d3997e8fd5f9819700","assignee":"销售/客服","roleCode":"sales","status":"pending","dueAt":"","priority":"高","checklist":[],"id":"task-2a3d9d4736c44b31855305220b28652a","tenantId":"tenant-demo","createdAt":"2026-07-11T13:48:48.860012"},{"title":"调整安全库存与调拨","source":"INC-20260711-4CCDFD","incidentId":"inc-de001abf756b47d3997e8fd5f9819700","assignee":"仓库人员","roleCode":"warehouse","status":"pending","dueAt":"","priority":"高","checklist":[],"id":"task-08d9d2a8f71c4167b792e3fdde7a8493","tenantId":"tenant-demo","createdAt":"2026-07-11T13:48:48.860013"},{"title":"调整生产排程","source":"INC-20260711-4CCDFD","incidentId":"inc-de001abf756b47d3997e8fd5f9819700","assignee":"生产计划人员","roleCode":"planner","status":"pending","dueAt":"","priority":"高","checklist":[],"id":"task-886576a06eb24932bcfa8737df832179","tenantId":"tenant-demo","createdAt":"2026-07-11T13:48:48.860013"}],"total":5,"success":true}
```

#### 8. 查询审批审计

管理员账号先通过 `/api/v1/auth/login` 实际登录，登录密码和 token 在材料中脱敏。

```http
GET /api/v1/audit-logs?targetType=approval
Authorization: Bearer <redacted>

HTTP 200
{"data":[{"time":"2026-07-11T21:48:27.291855+08:00","userId":"u-scm_lead","userName":"供应链负责人","roleCode":"scm_lead","action":"提交审批","targetType":"approval","targetId":"ap-f583c412b69e46deac81155a879d574f","targetName":"采购 Agent","detail":{"incidentId":"inc-de001abf756b47d3997e8fd5f9819700"},"ip":"127.0.0.1","id":"audit-3dd0eefab89042f0988918ba519c1eee","tenantId":"tenant-demo","createdAt":"2026-07-11T13:48:27.293710"},{"time":"2026-07-11T21:48:48.858378+08:00","userId":"u-boss","userName":"老板/总经理","roleCode":"boss","action":"审批approve","targetType":"approval","targetId":"ap-f583c412b69e46deac81155a879d574f","targetName":"采购 Agent","detail":{"reason":null,"assignee":null},"ip":"127.0.0.1","id":"audit-841bcf57b9f84618912ff65dc9a5d6ca","tenantId":"tenant-demo","createdAt":"2026-07-11T13:48:48.859349"}],"total":2,"success":true,"current":1,"pageSize":20}
```

链路结论：登录成功；事件创建返回 `manual/0/0`；异步作业成功生成 3 个方案；高风险审批成功提交并由老板批准；审批通过后生成 5 个任务；同事务审计可查询 2 条审批记录。

## ④ 已知限制与 TODO

- 按评审要求已在 `jobs.py` 和 `proposal_mapper.py` 明确记录：当前决策作业仍调用 `run_demo()`，尚未把 Incident 风险/物料上下文映射为决策引擎输入；前端缺失字段的序位兜底值也是 MVP 占位。
- PostgreSQL 本次未连接真实服务；显式迁移已在 SQLite 上完成 upgrade/downgrade 实测，PostgreSQL 驱动和 Alembic 配置保持不变。
- `data/audit_log.jsonl` 的 275 行任务前既有增量未擅自回滚；该文件不是本次评审修复产生的 churn。
- 未修改 Phase 2/3。
