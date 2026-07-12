# ChainGuard Phase 4 交付材料

交付日期：2026-07-12。范围严格限于 A1–A5、B1–B7、E-2、F1–F5（仅 appdata 备份短期项）、F7–F9；未实现 C 组、5A/5B、E-1/E-3/E-4/E-5、F6、D2。

## 验收证据

| 项目 | 实现与复现/修复对照证据 |
| --- | --- |
| A1 | 复现：浏览器 SheetJS 预览与服务端执行曾各自校验，导致前端通过、execute 拒绝。修复：API 模式上传后立即调用 `/imports/{id}/preflight`，导入向导展示该报告并标明“最终口径”；CSV/XLSX 仍保留字段映射交互。 |
| A2 | 复现：approve 时创建的 5 条任务 `due_at=""`，`assignee` 是角色中文名。修复：任务仅由 `_create_execution_tasks` 创建，负责人查询本租户 active 用户 ID；高风险到期为 T+1、中风险为 T+3；改派也校验本租户 active 用户（CG-2404）。显式测试覆盖 5 个任务均有 user ID 与 due_at。 |
| A3 | 复现：引擎实际输出 `proposal_title`、`proposal`、`reasoning`，mapper 未读取而显示 Agent 名/成本 0 的静默兜底。修复：映射 `proposal_title` 与 `proposal`；无成本、订单影响等引擎字段时 `explanation.dataMissing` 显式标记，未伪造序号数据。`test_decision_mapper_always_returns_three_frontend_proposals` 锁定标题、理由与缺失标记。 |
| A4 | 复现：`/incidents/{id}/impact` 固定返回四个空数组。修复：从关联风险 `object_name/details` 抽取物料/供应商关键词，匹配本租户 `data_records`；各未命中维度返回 `dataMissing`，前端显示“数据不足，完善基础资料后可见”。 |
| A5 | 复现：高风险 boss approve 立即生成任务。修复：高风险进入 `pending_countersign`，财务会签才 `approved` 并建任务；`COUNTERSIGN_TIMEOUT_HOURS` 默认 4，小型后台线程每 5 分钟调用扫描器，超时自动放行并通知财务追认；财务拒签必须填理由、审批 rejected、事件回 planning。前端展示“待会签”。显式回归：boss approve→无任务→finance countersign→5 任务；超时放行；finance 拒签打回。 |
| B1–B5 | API 模式不再预填/展示 Demo@1234，隐藏验证码登录与注册验证码；企业名称改为普通输入，不泄露种子租户；授权码灰置“即将上线”；API 模式隐藏“演练”和角色切换。 |
| B6 | 部署文档增加正确的手动备份命令。 |
| B7 | `notify.webhookConfig` API 模式改接真实 GET/PUT `/notifications/webhook-config`。 |
| E-2 | upload 白名单扩展至 PDF/PNG/JPG/JPEG；服务端 preflight 通过 `ingest_files` 级联，成功提取时落 `normalized.csv` 后复用预检/执行管线；无 OCR/视觉可用时保留 staging 原文件并返回 `manual_required` 与“待人工处理”。前端 accept 与文案同步放开，并且图片/PDF不再交给 SheetJS。当前验收环境未配置 QWEN OCR 证明材料；按复审注意事项第 5 条采用第三种合格判定：无可用 OCR 时明确 staging/manual_required，不静默失败。 |
| F1 | 新增 `scripts/export-images.ps1`（`docker save`）与 `scripts/import-images.ps1`（`docker load`），部署文档新增离线安装流程。 |
| F2 | SQLAlchemy `OperationalError/DBAPIError` 统一返回 HTTP 503、`CG-5030`“依赖服务不可用”，前端既有 503 黄条逻辑自动生效。 |
| F3–F4 | compose 的所有常驻服务使用 json-file 50m×5 日志轮转；API 2 CPU/2 GB、PostgreSQL 1 CPU/1 GB 资源限制；文档说明约 4 并发决策作业容量口径。 |
| F5（短期） | 备份服务只读挂载 `appdata`，`backup-postgres.sh` 追加 `chainguard_appdata_*.tar.gz` 并按 7 天清理。未实现审计入库长期项。 |
| F7–F9 | 部署文档补充 Caddy/nginx 前置 TLS 与 `REFRESH_COOKIE_SECURE`、RPO=24h/RTO 无固定承诺与 WAL 选项、`.env` ACL/密钥轮换及 JWT 会话失效说明。 |

## 实际验证原始输出

### E-2 三选一判定（第三种：无 OCR 的 staging 降级）

```text
upload 201 uploaded
preflight 200 manual_required manual_required
message 待人工处理：未配置可用的 OCR/视觉提取能力，原始文件已保留在 staging。
```

上述为实际 TestClient 上传内存 PNG 占位文件后调用 preflight 的输出；因此符合复审注意事项第 5 条的第三种验收路径。

### `python -m pytest tests/ -q`（干净可写测试目录）

```text
........................................................................ [ 14%]
........................................................................ [ 29%]
........................................................................ [ 43%]
........................................................................ [ 58%]
........................................................................ [ 72%]
........................................................................ [ 87%]
...............................................................          [100%]
============================== warnings summary ===============================
src\api.py:62: DeprecationWarning: on_event is deprecated, use lifespan event handlers instead.
tests/test_model_comparison.py: FutureWarning: SVC(probability=True) is deprecated in scikit-learn 1.9.
tests/test_security.py: RuntimeWarning: cryptography is not installed; encryption degraded to plaintext.
495 passed, 11 warnings in 87.12s (0:01:27)
```

首次在受限沙箱内运行同一命令时，pytest 无法清理既有 `.tmp/pytest`、且无法写入 `data/`，产生 1 failed/38 errors 的 Windows 权限错误；随后在可写干净测试目录重跑以上同一命令，完整通过。未改动任何现有测试断言；A5 的审批语义测试已显式重写并新增。

### `DATA_MODE=api npm run build`（Windows 以等价环境变量与 `npm.cmd` 执行）

```text
> chainguard-web@1.0.0 build
> max build

info  - Umi v4.6.74
info  - Preparing...
i Compiling Webpack
√ Webpack: Compiled successfully in 8.46s
info  - Memory Usage: 500.93 MB (RSS: 1585.54 MB)
info  - [esbuildHelperChecker] Checking esbuild helpers from your dist files...
info  - [esbuildHelperChecker] No conflicts found.
event - Build index.html

> chainguard-web@1.0.0 postbuild
> node scripts/generate-route-access-map.cjs

generated D:\github_projects\Chainguard\chainguard-web\docs\route-access-map.md
```

PowerShell 执行策略阻止 `npm.ps1`，因此使用同一 Node/npm 安装提供的 `npm.cmd`；沙箱首次阻止 esbuild 子进程（EPERM），随后在允许实际子进程的环境执行并成功。

## 变更文件清单

### 实现

- `ChainGuard/src/webapi/routers/business.py`
- `ChainGuard/src/webapi/routers/imports_settings.py`
- `ChainGuard/src/webapi/proposal_mapper.py`
- `ChainGuard/src/webapi/errors.py`
- `ChainGuard/src/webapi/config.py`
- `ChainGuard/src/api.py`
- `ChainGuard/tests/test_webapi.py`
- `chainguard-web/src/services/data.ts`
- `chainguard-web/src/services/notify.ts`
- `chainguard-web/src/components/ImportWizard/index.tsx`
- `chainguard-web/src/pages/Decision/Approval.tsx`
- `chainguard-web/src/pages/Incident/Detail.tsx`
- `chainguard-web/src/pages/User/Login.tsx`
- `chainguard-web/src/pages/User/Register.tsx`
- `chainguard-web/src/app.tsx`
- `chainguard-web/src/constants/status.ts`

### 部署与运维

- `ChainGuard/docker-compose.yml`
- `ChainGuard/scripts/backup-postgres.sh`
- `ChainGuard/scripts/export-images.ps1`
- `ChainGuard/scripts/import-images.ps1`
- `ChainGuard/docs/deploy_guide.md`

### 验证运行产生的已有跟踪数据改动

- `ChainGuard/data/audit_log.jsonl`
- `ChainGuard/data/model_registry.json`

`codex_landing_spec/05_验收后改进清单.md` 在开始时已是用户工作区既有修改，未改动。

## 评审须修项 1 修复记录（2026-07-12）

评审发现会签超时曾错误从审批单 `created_at`（提交时刻）起算。现改为只解析审批历史中最后一次 `approve` 动作的 `time`：即 boss 将高风险单转入 `pending_countersign` 的时刻。没有该状态转换时间的遗留/异常记录不会被调度器自动放行。

新增回归测试 `test_late_boss_approval_does_not_skip_countersign_timeout_window`：审批单提交已超过 5 小时后，boss 才批准；随即扫描必须返回 0，审批仍为 `pending_countersign`、事件仍为 `approving`、且没有任务。原超时放行测试同步改为回拨 `approve` 历史时间，而不是回拨提交时间。

同时完成两项评审建议：扫描查询使用 `with_for_update(skip_locked=True)` 降低多 worker 并发竞争；impact 关键词仅使用长度至少为 2 的字符串，不再纳入风险 details 中的数值。

### 实际验证原始输出：`python -m pytest tests/test_webapi.py -q`

```text
......................                                                   [100%]
============================== warnings summary ===============================
src\api.py:62
  D:\github_projects\Chainguard\ChainGuard\src\api.py:62: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.

..\..\..\Python313\Lib\site-packages\fastapi\applications.py:4601
  D:\Python313\Lib\site-packages\fastapi\applications.py:4601: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.

..\..\..\Python313\Lib\site-packages\_pytest\cacheprovider.py:475
  PytestCacheWarning: could not create cache path D:\github_projects\Chainguard\ChainGuard\.pytest_cache\v\cache\nodeids: [WinError 5] 拒绝访问。

22 passed, 3 warnings in 1.89s
```
