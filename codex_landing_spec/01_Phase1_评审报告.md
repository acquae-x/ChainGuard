# Phase 1 评审报告（结论：不通过，打回修复）

评审时间：2026-07-11。评审方式：直接检查仓库代码 + 实际运行测试（非依据 Codex 自述）。

## 一票否决项：多个文件被截断，服务无法启动

以下文件在生成时被**截断在半截**（无结尾换行、语句写到一半），其中 7 个是语法错误，`import src.api` 直接失败，**服务器起不来，任何"测试通过"的自述均不可信**：

| 文件 | 截断位置（当前最后内容） |
|---|---|
| `src/api.py` | `audit_entry = _as_mapping(result.get("audit_entry"` |
| `src/db.py` | 74 行 `if` 后为空 |
| `src/observability.py` | `observe_http` 相关代码写到一半 |
| `tests/test_api.py` | `mock_loa` |
| `src/webapi/auth/security.py` | `require_permission` 的 implied 映射表写到一半 |
| `src/webapi/jobs.py` | `_run_import_job` 的 except 分支写到一半 |
| `src/webapi/routers/imports_settings.py` | `disable_field` 函数签名写到一半 |
| `src/llm_client.py` | **能编译但必炸**：函数以孤立表达式 `endpoin` 结尾，运行即 NameError |
| `requirements.txt` | 以 `psy` 结尾（psycopg 写一半），且**误删了仍被 `import_preflight.py`、`ingestion_agent.py` 使用的 `pdfplumber`、`psutil`** |
| `.env.example` | `WEBHOOK_REMOTE_ENABLED` 重复出现 3 次 |

实测：`pytest tests/test_webapi.py` 在 collection 阶段即因 `src/db.py` SyntaxError 中断。总指令明确要求"不得破坏现有 63 个测试"，`tests/test_api.py` 已被改坏。

另外 `data/*.json`、`demo_assets/enterprise/csv/*` 出现约 13 万行的 diff churn，未在任务范围内，需要解释或回滚。

## 设计问题（修复截断时一并处理）

1. **线程池自死锁（严重）**：`jobs.py` 中 `_run_decision_job` 本身运行在 4 线程的 executor 里，内部又向**同一个** executor 提交 `run_demo` 并等待结果。4 个决策作业并发时，4 个 worker 全在等永远排不上队的内层任务——整池死锁。修法：内层不要再 submit，直接在当前线程跑并用 `concurrent.futures` 单独的池或信号量做 60s 超时。
2. **Alembic 迁移是假的**：`20260711_0001_initial.py` 里直接 `Base.metadata.create_all()`，且 `api.py` import 时又 `create_all(engine)`。这让迁移体系形同虚设，后续任何表结构变更无法走版本化。修法：迁移文件写真实的 `op.create_table(...)`（可用 alembic autogenerate 生成），删掉 api.py 里的 `create_all`，启动依赖 `alembic upgrade head`。
3. **决策作业与事件无关**：`_run_decision_job` 固定跑 `run_demo()`，不读事件关联的风险/物料上下文。MVP 可接受，但必须在代码注释和已知限制里明说，且 `map_decision_result` 的兜底字段（residual_risk 按序号硬编码 low/medium/high 等）要标注为占位。
4. `create_incident` 硬编码 `loss=860000`、`type="supplier_shutdown"`——演示数据泄进了业务逻辑，改为可传参/置 0。
5. `transfer` 审批不校验 `assignee` 是否为本租户真实用户。
6. `serialize()` 全局隐藏 `account` 但 `settings/users` 场景管理员应能看到账号；按需开白名单。
7. `upload_import` 未限制文件大小与扩展名白名单（csv/xlsx），存在磁盘写满风险。

## 做得对的地方（保留，不要重写）

租户隔离（repository 层强制 tenant_id 过滤）+ 对应测试；错误信封与 traceId 中间件；500 不泄漏内部信息且有专门测试验证；登录限流 5/min；bcrypt + 双 token；seed 密码走环境变量；幂等键防重复决策作业；审计与业务写在同一事务。架构分层（routers/repository/auth/jobs/mapper）符合总指令。

## 给 Codex 的修复指令（原样转发即可）

> Phase 1 评审不通过，按 `codex_landing_spec/01_Phase1_评审报告.md` 修复：
> 1. 补全全部被截断的文件（报告第一节表格逐个核对，每个文件修完后运行 `python -m py_compile` 自检；requirements.txt 恢复 pdfplumber、psutil 并补全 psycopg 可选依赖注释）。
> 2. 修复设计问题 1–7，其中 1（线程池死锁）和 2（假迁移）必须修，3–7 至少修 1、4、7。
> 3. 回滚 data/ 与 demo_assets/ 下与本任务无关的改动，或书面解释每一处为何必要。
> 4. 完成后**实际运行** `python -m pytest tests/ -q` 全量测试，把完整原始输出贴进交付材料；再用 curl 实际走通登录→创建事件→生成方案→审批→任务链路，贴原始请求与响应。禁止提交任何未实际执行的"测试通过"声明。
> 5. 交付四项材料存为文件：`codex_landing_spec/phase1_交付材料.md`。
