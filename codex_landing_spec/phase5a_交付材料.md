# ChainGuard Phase 5A 交付材料

执行日期：2026-07-12。本文只记录本次实际执行并有输出的验证；没有把环境受限项标记为通过。

## 实现清单

| 规格项 | 交付 |
|---|---|
| 5A-1 / 5A-3 | `decision_details`、`decision_audits` 租户表；作业完成时持久化完整 `DecisionResult` 和敏感性数据；`GET /incidents/{id}/decision-detail`；方案/审批共用完整推演抽屉。|
| 安全硬要求 | detail、JSON 导出和 PDF 导出统一先按请求角色走 `mask_for_requester`；无 `field:cost:view` 的 buyer 成本字段为 `***`；新增 API 回归测试。|
| 会签追认闭环 | 超时放行后 finance 可执行“追认通过”或“追认异议”（理由必填），写审批历史和审计，且不回滚已创建任务。|
| 5A-2 | `notification_rules` 表和固定规则初始数据；同用户/同对象/同事件五分钟未读聚合；决策完成、会签请求/完成/拒签/超时放行已接入站内通知。|
| 5A-4 → 5A-5 | refresh JWT 含 `jti`；发行表+吊销表，刷新轮换、登出、修改密码均吊销；个人设置改密、管理员重置一次性临时密码、首登改密守卫、忘记密码管理员提示。|
| 5A-7 | 可选 `monitoring` compose profile、Prometheus 抓取配置和三条告警规则文件。|

未改变 `src/orchestrator.py` 的决策流水线；未进入 5B 数据真实化范围；未新增权限码。

## 真实验证输出

### Alembic up/down/up

命令：

```powershell
$env:DATABASE_URL='sqlite:///./phase5a_migration_verify.db'
alembic upgrade head
alembic downgrade 20260711_0001
alembic upgrade head
```

原始关键输出：

```text
20260712_0002 (head)
20260711_0001
20260712_0002 (head)
Running upgrade  -> 20260711_0001
Running upgrade 20260711_0001 -> 20260712_0002
Running downgrade 20260712_0002 -> 20260711_0001
Running upgrade 20260711_0001 -> 20260712_0002
```

### 后端回归

命令：`python -m pytest tests/ -q -p no:cacheprovider`

原始结果：

```text
497 passed, 11 warnings in 88.32s (0:01:28)
```

其中新增 `test_decision_detail_and_export_are_masked_by_requester_permissions`：buyer detail/JSON 导出中的 `total_cost` 和 `cost` 为 `***`，boss 仍可取得原值。

### 前端 API 构建

命令：`DATA_MODE=api npm.cmd run build`

原始结果：

```text
√ Webpack: Compiled successfully in 9.98s
[esbuildHelperChecker] No conflicts found.
event - Build index.html
generated D:\github_projects\Chainguard\chainguard-web\docs\route-access-map.md
```

### PDF 脱敏对照

实际生成文件：

- `outputs/phase5a/buyer-masked.pdf`
- `outputs/phase5a/boss-unmasked.pdf`

使用 `pypdf` 实际提取的输出：

```text
buyer: {"cost":"***"} [{"total_cost":"***"}]
boss:  {"cost":70000} [{"total_cost":80000}]
```

## 截图验收状态

规格要求的六项用户可感知变化、追认动作和 PDF 页面截图 **未完成**。已实际尝试 Playwright CLI、浏览器内核和应用内浏览器；前两者被本机子进程策略阻止，应用内浏览器在隔离环境中无法访问本机开发服务器，未获得可信页面内容。因此没有伪造截图或把该项写为已验收。

待可访问本机 `http://127.0.0.1:8000` 的浏览器环境恢复后，应补拍：完整推演、确认点/导出、导入红绿灯、归一化预览、改密/重置、铃铛通知、超时追认，以及 buyer/boss PDF 对照。

## 2026-07-13 评审打回修复记录

本节只记录 `12_Phase5A_评审报告.md` 文末五条打回指令的实际修复和本次执行结果。

| 打回项 | 修复记录 | 覆盖测试 |
|---|---|---|
| ① 通知、逾期扫描 | 新增唯一入口 `notify_event(db, tenant_id, event_type, context)`：读取启用的 `notification_rules.recipient_strategy`，解析 `trigger`、`assignee`、`submitter`、`approver` 与既有角色码后去重聚合。六个缺失事件 `task_assigned`、`task_urged`、`task_overdue`、`import_succeeded`、`import_failed`、`risk_high` 已接入；审批提交也会按风险等级通知终审人，满足条件时通知 finance。五分钟调度器增加任务逾期扫描，状态只从 `pending` 流转一次到 `overdue`。 | `test_notification_rules_are_consumed_for_missing_phase5a_events`、`test_overdue_task_scanner_marks_once_and_notifies_assignee_and_scm` |
| ② 导入预检 | 服务端预检结果增加 `normalized.previewRows`（上限 20 行）；导入向导改为红/黄/绿交通灯、容量摘要与归一化表格预览。磁盘不足是硬阻断，前后端均不可用 force 绕过。 | `test_preflight_normalized_preview_and_insufficient_disk_is_not_forceable` |
| ③ 推演持久化与图形 | 决策作业在既有完整结果中持久化 `game_analysis`（含策略空间、协同指标和 Pareto 点/前沿）；不修改 `src/orchestrator.py`。完整推演抽屉以 ECharts 显示策略组合 Pareto 散点/前沿和库存—风险敏感性折线。 | `test_game_analysis_and_pending_job_metric_are_persistable`；API 模式生产构建 |
| ④ 作业积压与主机监控 | Prometheus 新增 `chainguard_jobs_pending` Gauge，在作业状态迁移和 `/metrics` 抓取时刷新；monitoring profile 增加 node-exporter，并由 Prometheus 抓取 `node-exporter:9100`，已有磁盘告警因此有数据源。 | `test_monitoring_bootstrap_exports_job_gauge_and_node_exporter` |
| ⑤ 审批提交通知 | `approval_submitted` 规则由 `notify_event` 消费：高风险投递 boss 和 finance；其他风险投递 scm_lead，符合既有角色口径，未新增权限码。 | `test_notification_rules_are_consumed_for_missing_phase5a_events` |

### 本次实际验证

后端命令：`python -m pytest tests/ -q -p no:cacheprovider`

```text
502 passed, 11 warnings in 94.58s (0:01:34)
```

前端命令：`DATA_MODE=api npm.cmd run build`

```text
√ Webpack: Compiled successfully in 9.76s
[esbuildHelperChecker] No conflicts found.
event - Build index.html
generated D:\github_projects\Chainguard\chainguard-web\docs\route-access-map.md
```

## 2026-07-13 界面实测（phase5a_ui_检查报告）问题修复记录

本节逐项对应实测报告的 P0/P1/P2 编号。**执行环境说明（诚实声明）**：本轮修复在 Cowork 会话中完成，会话的 Linux 执行沙箱启动失败（"VM service not running"，重试 3 次），因此本节所有"测试命令/浏览器验证/截图"项均为 **未执行**——代码与测试已写入，但 pytest、alembic、npm build、真实浏览器复测和截图必须在沙箱或本机环境恢复后补跑。没有任何一项被包装成已通过。

| # | 问题 | 修复位置 | 覆盖测试（已写入，未执行） | 浏览器验证 | 截图 |
|---|---|---|---|---|---|
| P0-1 | 超时追认 409 不可用 | `src/webapi/routers/business.py`：追认分支移到通用"审批单已处理"检查之前；新增只能追认一次（CG-2405）；追认通过/异议均写审批历史+审计，并经 `countersign_ratified` 规则通知 boss 与提交人（`notifications.py` 增加该规则）；不回滚任务。前端 `ApprovalActionBar/index.tsx` 全部动作经 `run()` 捕获错误，业务错误以 message 呈现，Modal 校验失败留在弹窗，杜绝整页 Unhandled Rejection | `test_ratify_approve_after_timeout_release_persists_and_notifies`、`test_ratify_object_requires_reason_and_writes_history`、`test_ratify_rejected_when_not_timeout_released_or_wrong_role` | 未执行 | 未完成 |
| P0-2 | 新方案显示 ¥0/0 客户/0 天 | `src/webapi/proposal_mapper.py` 重写：订单/客户等级从 `context.orders`（按受影响物料过滤，A 类计高等级）映射，交期从方案点名供应商的 `context.suppliers.lead_time_hours` 瓶颈向上取整为天，剩余风险从 `scores.risk_reduction` 分档；未知值一律 None。`models.py` proposals 五个指标列+approvals.cost_impact 改可空（迁移 `20260713_0003`）。中风险成本未知按保守口径抄送财务（business.py + notifications.py）。前端 `utils/proposalMetrics.ts` 统一"数据缺失"口径，`Generate.tsx`、`Decision/List.tsx`、`Approval.tsx`、`Dashboard/index.tsx` 与 `typings.d.ts` 同步。未修改 `src/orchestrator.py` | `test_mapper_maps_trusted_context_fields_and_never_fakes_zero`、`test_medium_risk_with_unknown_cost_conservatively_ccs_finance`、既有 `test_decision_mapper_always_returns_three_frontend_proposals` | 未执行 | 未完成 |
| P0-3 | buyer/boss PDF 导出返回 CG-5000 | 根因是运行服务的 Python 环境未安装 `reportlab`（requirements.txt 已含）。修复：`business.py` 导出端点把缺依赖转为 503 CG-2505 明确业务错误；`services/decision.ts` 透出后端错误文案；DecisionTrace/Approval 导出按钮 message 提示。**运行环境需执行 `pip install -r requirements.txt` 后重启 API**。GET/JSON/PDF 三出口共用 `mask_for_requester`（既有 `test_decision_detail_and_export_are_masked_by_requester_permissions` 锁定 buyer=***、boss=原值） | 既有脱敏测试 + 待环境恢复后 pypdf 实提两份 PDF 对照 + PNG 渲染目视 | 未执行 | 未完成 |
| P1-4 | XLSX 假绿灯 | `imports_settings.py`：新增 `normalize_xlsx_to_csv()`（openpyxl 解析→CSV，失败抛异常），preflight 对 .xlsx 先归一化再按行预检；解析失败落 `PARSE_ERROR` 红灯且 confirm 阶段禁止 force；`camelize_report()` 统一转 camelCase 解决 estimatedRows/canProceed 契约错位。前端 `ImportWizard` 红灯态覆盖 PARSE_ERROR/canProceed=false 且隐藏"仍要导入"，解析失败停在上传步骤展示业务红灯；`services/data.ts` 把 PARSE_ERROR 列为硬闸门。openpyxl 移入运行时 requirements.txt | 既有 `test_xlsx_preflight_normalizes_rows_before_estimating`（此前缺实现）+ 新增 `test_corrupted_xlsx_preflight_is_red_light_and_not_forceable` | 未执行 | 未完成 |
| P1-5 | 推演第 4 节 3600 字符原始 JSON | `components/DecisionTrace/index.tsx`：第 4 节改为敏感性折线与 Pareto 散点/前沿前置 + 结构化摘要（可行组合数/最优组合/最优系统效用/约束违反/推荐调整），移除 `JSON.stringify(constraint_analysis)` 主展示；两张图带文字替代摘要与空态 | 前端构建验证（未执行）；数据结构由 `test_game_analysis_and_pending_job_metric_are_persistable` 锁定 | 未执行 | 未完成 |
| P1-6 | 风险总览图表为空 | `pages/Risk/Overview.tsx`：散点图坐标轴此前缺 `type:'value'`（category 轴导致数值坐标全部无法落点）已补；气泡大小裁剪、x 轴按数据自适应；KPI 与类型饼图改为从真实风险数据聚合；两图均有空态与文字替代摘要 | 浏览器目视验证（未执行） | 未执行 | 未完成 |
| P1-7 | 375px 审批页横向溢出 | `Approval.tsx`：抽屉标题长单号 break-all、抽屉 body overflow-x hidden（宽表仍在 antd Table 局部容器内横向滚动）、决策摘要 Descriptions 局部滚动；DecisionTrace 抽屉同样 overflow-x hidden，且第 4 节 JSON 长行（既往溢出主因之一）已移除 | 必须浏览器实测 `document.documentElement.scrollWidth <= window.innerWidth`（未执行，本项不声明通过） | 未执行 | 未完成 |
| P1-8 | boss 终批后跳 /task/all 空页 | `Approval.tsx`：移除 approve 后的 `history.push('/task/all')`；高风险终批留在详情并提示"待会签"；仅 status=approved 时显示"审批已生效，执行任务已生成"成功条与"查看执行任务"入口 | 前端行为，待浏览器验证 | 未执行 | 未完成 |
| P1-9 | 会签后第 3 步未完成 | `Approval.tsx`：Steps current 计算修正（approved→全链 finish，pending_countersign→停第 3 步）；抽屉模式动作完成后原地重拉详情+刷新列表而不是关闭丢状态。5 条任务生成由既有 `test_high_risk_approval_requires_countersign_before_creating_tasks` 锁定 | 既有任务测试 + 浏览器验证（未执行） | 未执行 | 未完成 |
| P1-10 | 重新推演删除审批引用的 Proposal | `jobs.py`：只删除未被 Approval 引用的旧方案，被引用者置 `archived=True` 永久保留（audit 追溯）；`models.py`+迁移 0003 增加 archived 列；方案列表与审批对比 options 排除归档，审批详情按 id 仍可取 | `test_regeneration_archives_referenced_proposal_and_keeps_approval_detail_alive`（含"旧审批详情仍为 200"强断言） | 未执行 | 未完成 |
| P1-11 | 管理员进审批中心无权限 | `auth/security.py`：`approval:view` 隐含 `settings:manage`（复用口径，不新增权限码），管理员可只读列表/详情；所有动作在 `approval_action` 内有独立权限检查，管理员 approve/reject/countersign 一律 403；前端动作区对无动作角色显示"当前角色仅可查看审批记录"（既有） | `test_admin_can_read_approvals_but_cannot_act` | 未执行 | 未完成 |
| P2-12 | SCM 提交后按钮状态不刷新 | `Approval.tsx`：submit/withdraw 能力跟随审批单实际状态；动作完成后 onDone 重拉详情与列表 | 浏览器验证（未执行） | 未执行 | 未完成 |
| P2-13 | 审批业务错误整页覆盖 | `ApprovalActionBar` run() 捕获、`Generate.tsx` 保存草稿/提交审批 try/catch、导出按钮 try/catch、`services/decision.ts` 透出业务文案——全部以 message/表单内联提示呈现 | 浏览器验证（未执行） | 未执行 | 未完成 |
| P2-14 | 图表缺文字替代与空态 | 风险矩阵/类型饼图/Pareto/敏感性四处均补文字摘要与明确空态（Overview.tsx、DecisionTrace） | 浏览器验证（未执行） | 未执行 | 未完成 |
| P2-15 | pytest 污染默认 chainguard.db | `tests/conftest.py`：在任何应用模块导入前设置隔离临时 `DATABASE_URL`（临时目录内 chainguard-test.db，预创建空库以兼容 src/db.py 的存在性检查），atexit 清理临时目录；不覆盖 CI 显式注入的 DATABASE_URL | `test_pytest_database_url_is_isolated_from_default_db` | 不适用 | 不适用 |

### 待执行验证清单（沙箱/本机环境恢复后按序补跑）

1. `python -m pytest tests/test_webapi.py -q -p no:cacheprovider`（定向）——**未执行**
2. `alembic upgrade head` → `alembic downgrade 20260712_0002` → `alembic upgrade head`（0003 迁移 up/down/up 实测）——**未执行**
3. ChainGuard 目录 `python -m pytest tests/ -q -p no:cacheprovider` 全量——**未执行**
4. chainguard-web 目录 `$env:DATA_MODE='api'; npm.cmd run build`——**未执行**
5. API 模式起前后端，真实浏览器逐项复测（XLSX 红绿灯、推演结构化摘要与两图、boss 终批不跳转、finance 会签+5 任务、超时放行通知直达、追认通过/异议双流程、管理员只读、375px 无页面级溢出、风险两图可见、buyer/boss PDF 实提对照）——**未执行**
6. 截图写入 `codex_landing_spec/phase5a_ui_audit_fixed/`——**未完成**（目录未创建，避免造成"已截图"假象）
7. PDF 依赖：运行服务的 Python 环境需 `pip install -r requirements.txt`（本轮把 openpyxl 也移入运行时依赖）后重启，再做第 5 步的 PDF 项

## 2026-07-13 Codex 接续修复与真实复测

本节覆盖上一节明确标为“未执行”的项目，只把本轮实际执行并取得输出的项目更新为通过。验证使用当前工作区代码、隔离数据库 `ChainGuard/phase5a_continue_verify_20260713.db` 和 API 模式前端；没有修改 `src/orchestrator.py`，没有进入 5B，没有新增权限码，也没有放宽既有断言。

### 接续修复

1. `src/webapi/decision_detail.py`
   - 财务字段先做 camelCase → snake_case 规范化，再递归识别 `cost/amount/price/profit/benefit/savings/penalty` 财务语义，覆盖 `costImpact`、`penalty_cost`、`cost_multiplier`、`net_benefit`、`profit_protected` 等嵌套字段。
   - GET detail、JSON 和 PDF 共用 `mask_for_requester`；PDF 只接收已脱敏 payload。
   - PDF 改成业务章节、键值表、方案表、审批链和页脚页码，不再输出原始 JSON 文本墙；补入总成本、决策成本、净收益、节省、保护利润和审批成本影响。
2. `tests/test_webapi.py`
   - 补真实嵌套 GET/JSON 脱敏断言和 buyer/boss PDF 文本提取对照；PDF 对照覆盖 6 个不同财务数值及真实 `approval_chain.costImpact`。
3. `chainguard-web/src/pages/User/Login.tsx`
   - 用 `flushSync` 在导航前提交 initialState，消除 `layout.onPageChange` 读取旧登录态并推回 `/user/login` 的竞态；redirect 只接受站内安全路径。
4. `chainguard-web/src/pages/Decision/Approval.tsx`、`components/DecisionTrace/index.tsx`
   - 页面、抽屉和表格容器补 `min-width:0/max-width:100%`，ProTable 的宽表滚动限制在局部容器；没有使用 body 级 `overflow-x:hidden` 掩盖问题。
   - 375px 抽屉改为满宽，方案 Tag 可折行；ECharts 使用 `containLabel`，横轴名称置中，避免移动端轴名裁切。
5. `pytest.ini`、`tests/conftest.py`
   - 原始 `pytest tests/ -q` 首次实际执行暴露 54 个 `No module named 'src'` 收集错误，增加 `pythonpath = .` 后直接命令可运行。
   - 测试数据库改为工作区 `test_tmp` 下的唯一 SQLite 文件，继续保证不接触默认 `chainguard.db`，同时避开 Windows `tempfile.mkdtemp` 的跨沙箱 ACL 问题。

### 实际命令与原始结果

定向后端：

```text
python -m pytest tests/test_webapi.py -q -p no:cacheprovider
......................................                                   [100%]
38 passed, 2 warnings in 6.18s
```

完整后端（按要求使用原始命令；修复 `pythonpath` 后重跑）：

```text
pytest tests/ -q
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 42%]
........................................................................ [ 56%]
........................................................................ [ 70%]
........................................................................ [ 84%]
........................................................................ [ 98%]
.........                                                                [100%]
513 passed, 11 warnings in 91.13s (0:01:31)
```

Alembic 隔离库 down/up：

```text
20260713_0003 (head)
Running downgrade 20260713_0003 -> 20260712_0002
20260712_0002
Running upgrade 20260712_0002 -> 20260713_0003
20260713_0003 (head)
```

最终 API 模式构建：

```text
$env:DATA_MODE='api'; npm.cmd run build
√ Webpack: Compiled successfully in 9.79s
[esbuildHelperChecker] No conflicts found.
event - Build index.html
generated D:\github_projects\Chainguard\chainguard-web\docs\route-access-map.md
```

运行依赖导入：

```text
D:\Python313\python.exe
deps-ok
```

实际导入了 `reportlab`、`openpyxl`、`pypdf`、`pdfplumber`。

### 真实浏览器复测

- 登录：SCM 登录提交后实际从 `http://127.0.0.1:8001/user/login` 到达 `/dashboard`，不再被推回登录页。
- 375×812 审批详情：`innerWidth=375`、`documentElement.scrollWidth=375`、页面级 overflow 为 0。
- 375×812 推演抽屉：`documentElement.scrollWidth=375`；两张 canvas 均为 `left=28.67/right=331.67/width=303`，完整落在视口内；方案 Tag 三个实测 `within=true`。
- 768px：`scrollWidth=768`，两张 canvas 均在视口内。
- 1280px：`scrollWidth=1265 <= innerWidth=1280`。
- 本轮截图：
  - `codex_landing_spec/phase5a_ui_audit_fixed/11-approval-mobile-375-fixed.png`
  - `codex_landing_spec/phase5a_ui_audit_fixed/12-trace-mobile-375-fixed.png`

XLSX 的后端真实解析和预检由本轮完整测试中的 `test_xlsx_preflight_normalizes_rows_before_estimating`、`test_corrupted_xlsx_preflight_is_red_light_and_not_forceable` 覆盖并通过；本轮尝试用 Windows 文件选择器补拍导入向导，但 Windows 自动化授权超时，因此没有把 UI 上传截图写成已完成。此前真实 API 上传 25 行 XLSX 得到 `verdict=OK`、`canProceed=true`、`estimatedRows=25` 和 20 行 `previewRows` 的记录仍有效。

### buyer / boss JSON 与 PDF 实际对照

实际文件：`output/pdf/phase5a-final/`。

```text
buyer.pdf    6792 bytes
boss.pdf     6807 bytes
buyer.json  26999 bytes
boss.json   27156 bytes
```

- buyer JSON 共识别 80 个财务语义字段，`all-masked=True`，未发现非 `***` 值。
- buyer PDF：`128000`、`600000`、`180000`、`420000` 均不存在，`***` 共 4 处。
- boss PDF：上述四个真实值全部存在，`***` 为 0。
- buyer/boss PDF 均实际渲染为 2 页 PNG；结构化章节、表格、换行和页码目视无重叠或截断：
  - `output/pdf/phase5a-final/buyer-render-1.png`
  - `output/pdf/phase5a-final/buyer-render-2.png`
  - `output/pdf/phase5a-final/boss-render-1.png`
  - `output/pdf/phase5a-final/boss-render-2.png`
- Poppler 渲染产生 `STSong-Light` 由本机 `SimSun` 替代的字体警告；实际四页中文均可读。该警告如实保留，未宣称不存在。

---

## 追加验收（2026-07-13，Opus 会话，真实执行）

运行环境：Windows 11 / Python 3.13.5 / Node v24.18.0。本节所有结论均来自实际执行，未执行的部分明确标注。

### 0. 依赖闭环
清华镜像 `pypi.tuna.tsinghua.edu.cn` 出现 SSL `WRONG_VERSION_NUMBER`，改用官方源安装成功：

```text
python -m pip install -i https://pypi.org/simple reportlab openpyxl pypdf pdfplumber pypdfium2
Successfully installed reportlab-5.0.0 openpyxl-3.1.5 pypdf-6.14.2 et-xmlfile-2.0.0
python -c "import reportlab,openpyxl,pypdf,pdfplumber" -> ALL OK
```

### 1. 全量后端回归（默认项目环境）

```text
python -m pytest tests/ -q
513 passed, 11 warnings in 92.82s
```

未删除或放宽任何断言；P0/P1 相关断言为新增/加强。

### 2. Alembic 隔离库迁移环（DATABASE_URL=sqlite:///./_alembic_check.db）

```text
upgrade head       ->  20260711_0001 -> 20260712_0002 -> 20260713_0003 (head)
downgrade -1       ->  20260713_0003 -> 20260712_0002
upgrade head       ->  20260712_0002 -> 20260713_0003
```

三步全部无异常。

### 3. 前端 api 模式构建

```text
DATA_MODE=api npm run build
BUILD_EXIT=0
postbuild: generated chainguard-web/docs/route-access-map.md
```

### 4. P0 统一财务脱敏（decision_detail.py 重写）

- 新增递归分类器 `is_financial_key`：先 camelCase→snake_case（costImpact→cost_impact），再匹配 7 类财务词根 `cost/amount/price/profit/benefit/savings/penalty`，覆盖复合字段，非逐样例补丁。
- GET decision-detail、JSON 导出、PDF 导出共用 `mask_for_requester` 一条路径；PDF 只消费脱敏后 payload；复用既有 `field:cost:view`，未新增权限码。
- pytest 加强（真实嵌套结构，buyer/boss 对照，GET+JSON+PDF）：

```text
python -m pytest tests/test_webapi.py -k "decision_detail_and_export or pdf_export_masks" -q
2 passed
```

覆盖字段：`costImpact`(approval_chain)、`penalty_cost`/`gross_profit`(context.orders)、`cost_multiplier`(context.suppliers / game_analysis.pareto / constraint_analysis.all_combos)、`cost_level`(transport)、`net_benefit`/`penalty_savings`/`profit_protected`(audit_entry)、`scores.cost`；非财务字段 `timeliness/demand_qty/reliability_score/system_utility/coordination_gain` 保留。

### 5. P1 决策 PDF 业务可读布局（render_pdf 重写）

- platypus `SimpleDocTemplate` + `LongTable`/`Paragraph`，七个业务章节（基本信息/仲裁结论/方案摘要/审批链/风险推演/执行确认点/审计记录），字段标签化、长文本换行、自动分页；不再 `json.dumps` 整段。
- 中文用 reportlab 内置 CID 字体 `STSong-Light`，不依赖 ArialUnicode/Symbol。
- 实际导出 buyer/boss 两份 PDF 并用 pypdfium2 渲染成 PNG 人工核对：

```text
buyer: 5863 bytes, 2 pages | 128000/600000/180000 均不存在 | *** 存在 | 中文“空运”存在
boss : 5901 bytes, 2 pages | 128000/600000/180000 全部存在 | *** 不存在
```

- 渲染图（本仓库留档）：
  - `codex_landing_spec/phase5a_artifacts/decision-buyer-p1.png`（净收益/违约节省/保护利润/成本分/成本影响全为 ***）
  - `codex_landing_spec/phase5a_artifacts/decision-boss-p1.png`（同字段显示 600000.0/180000.0/420000.0/55.0/128000.0）
  - `codex_landing_spec/phase5a_artifacts/decision-buyer.pdf`、`decision-boss.pdf`
- 目视：表格、标签、分章、页码无重叠或截断。

### 6. 浏览器实测（真实 api 栈：uvicorn:8000 + umi dev:8001，proxy /api→8000，隔离库 _demo_run.db + seed）

后端启动需 `JWT_SECRET`、`SEED_DEMO_PASSWORD`；`REFRESH_COOKIE_SECURE` 默认 false（http localhost 可用）。

- **登录跳转**（375px）：`buyer@chainguard.demo` 登录 API 200 → 前端由 `/user/login` 跳到 `/dashboard`（渲染采购人员工作台）；`boss@`、`admin@` 同样成功跳转。修复方式：`flushSync(setInitialState)` 后再 `history.replace`，并对 `redirect` 查询参数只放行站内安全路径。根因：登录后 SPA 跳转与 ProLayout `onPageChange` 鉴权守卫/`initialState` 传播存在竞态（后端返回结构与 `tenant.status` 均正常，非结构问题）。
- **审批页横向溢出**：`document.documentElement.scrollWidth <= window.innerWidth` 实测通过：

```text
375px: scrollWidth 375 <= 375  ok
768px: scrollWidth 768 <= 768  ok
1280px: scrollWidth 1280 <= 1280 ok
```

  （ProLayout header actions 内部有 580px 元素，但被固定头部裁剪，不撑大 document。）
- **推演抽屉**（375px）：为 `inc-supplier-shutdown` 注入含 27 点 Pareto + 3 点敏感性的 DecisionDetail 后打开抽屉，`scrollWidth 375 <= 375 ok`；两个 ECharts 容器实测 318px×260 / 318px×300，均 < 375 视口不裁切，敏感性与 Pareto 文字摘要正常渲染。注：预览浏览器（无 GPU/rAF）下 echarts canvas 像素绘制被延迟，容器尺寸与布局已确认正确。
- **导入向导**（admin，桌面宽）：向导内“使用当前类型示例文件”生成 XLSX 上传真实后端预检 —— **绿灯**（`ant-alert-success`，“绿灯：容量与格式预检通过”），服务端结论 `verdict=OK`，预估行数=3（示例文件行数），归一化预览表渲染（3 张表）。**红灯**：损坏 XLSX 经 `normalize_xlsx_to_csv` 抛 `BadZipFile` → 路由置 `verdict=PARSE_ERROR, canProceed=false` → 前端映射红灯（ImportWizard L52-60）。黄灯 REVIEW 走同一 verdict→颜色确定性映射。

### 7. 未完成 / 诚实缺口（不掩盖）

- **前端自动化测试基建缺失**：`chainguard-web` 无 jest/vitest/playwright，`package.json` 无 test 脚本。因此“登录跳转/失败、审批与抽屉 scrollWidth 断言、导入红黄绿”目前是**浏览器实测**证据（本节），尚未落成可重复的前端测试文件。补齐需引入测试框架，属独立工作项。
- 导入“黄灯”未在真实 UI 触发（仅确定性映射与绿/红实测）；`estimatedRows=25` 为特定 25 行样本，示例文件为 3 行。
- 预览浏览器 `screenshot` 工具多次 30s 超时，改用 DOM 断言取证；PDF 图片为 pypdfium2 本地渲染留档。

---

## 追加：前端可重复测试基建（2026-07-13，补齐上一节缺口）

引入 **Vitest（组件）+ Playwright（e2e）**，把三类前端断言固化为可重复测试。新增 devDeps：`vitest jsdom @vitejs/plugin-react @testing-library/{react,dom,jest-dom,user-event} @playwright/test cross-env`。脚本：`npm test`(vitest run) / `npm run test:e2e`(playwright)。

### Vitest：导入向导红黄绿灯 + 预览（组件级，自洽无后端）
`src/components/ImportWizard/PreflightSummary.test.tsx`（`PreflightSummary` 已导出）。

```text
npm test
✓ 绿灯 verdict=OK 显示 success 且展示归一化预览行
✓ 黄灯 verdict=REVIEW 显示 warning
✓ 红灯 verdict=PARSE_ERROR 显示 error 并阻止
✓ 红灯 INSUFFICIENT_DISK 硬阻断
✓ 红灯 canProceed=false 无 verdict 也不放假绿灯
Test Files 1 passed | Tests 5 passed
```

### Playwright：登录跳转 + 审批/推演横向溢出（e2e，mock 模式单服务自洽）
`playwright.config.ts`（webServer 起 `cross-env DATA_MODE=mock max dev`，无需后端/seed）；`e2e/login.spec.ts`、`e2e/overflow.spec.ts`。

```text
npx playwright test
ok 1 登录跳转 › 成功登录后跳转到工作台
ok 2 登录跳转 › 登录失败：停留在登录页并提示错误
ok 3 登录跳转 › redirect 查询参数仅放行站内安全路径
ok 4 审批中心在 375px 无 document 横向溢出
ok 5 审批中心在 768px 无 document 横向溢出
ok 6 审批中心在 1280px 无 document 横向溢出
ok 7 推演抽屉在 375px 无 document 横向溢出（图表容器不超视口）
7 passed (23.2s)
```

新增测试文件不影响 `DATA_MODE=api npm run build`（BUILD_EXIT=0 复跑通过）。

## 追加：Phase5A 全量浏览器复检（2026-07-13，真实 api 栈）

隔离库 `_demo_run.db` + seed，uvicorn:8000 + umi(api):8001。

| 面 | 结果 |
|---|---|
| 登录跳转 | boss/buyer/admin 登录 → /dashboard |
| P0 脱敏（真实事件 inc-supplier-shutdown，HTTP API）| GET/JSON/PDF：buyer 的 costImpact/penalty_cost/cost_multiplier/net_benefit/pareto.cost_multiplier 全 `***`；boss 全真实值（128000/180000/1.0/600000/4.45）；PDF buyer 无 128000+有 ***、boss 有 128000+无 ***，各 2 页 |
| 风险总览 | 2 个图表容器（风险矩阵图 486×320、按类型分布 328×320），无溢出 |
| 审批详情（boss UI）| 总成本 ¥128,000 未脱敏（boss 有 field:cost:view），决策摘要/审批链/推演齐全，无溢出 |
| 推演抽屉（boss UI）| 敏感性(360→1080)+Pareto 前沿(27 组合/最优 203.84) 摘要与 2 图表容器，无溢出 |
| 方案列表 | prop-1 ¥128,000 / prop-2 ¥196,000 真实值，无伪造 ¥0，无溢出 |
| 导入向导（admin）| 示例 XLSX → 绿灯 verdict=OK + 归一化预览；损坏 XLSX → 红灯 PARSE_ERROR |
| /metrics | `chainguard_jobs_pending` gauge 已导出 |

结论：P0 脱敏、P1 PDF、P1 375px、登录跳转、导入闭环、依赖闭环均已在真实栈复检通过；三类前端断言已固化为 `npm test` / `npm run test:e2e` 可重复回归。
