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

---

## 2026-07-15 Phase 5A 续修（P0 安全/角色 + P1 界面阻断 + 遗留 9~14）

执行环境：Cowork 会话内 Linux 沙箱（Ubuntu，Python 3.10.12，Node v22.22.3）。工作区 `D:\github_projects\Chainguard` 以只读/读写挂载方式接入。**诚实声明**：本轮后端 pytest / alembic 在沙箱内实际执行；前端 `DATA_MODE=api npm run build` 与 Playwright 浏览器实测/截图**无法在本沙箱执行**（原因见下"环境限制"），未伪造任何未执行的验证。

### 环境限制（诚实披露，未绕过、未谎报）

1. **前端生产构建无法在本沙箱跑通**：工作区 `chainguard-web/node_modules` 是在 Windows 上安装的，含 `@esbuild/win32-x64`、`@umijs/mako-win32-x64-msvc` 等**平台原生二进制**；Linux 沙箱需要 `@esbuild/linux-x64`、`@umijs/mako-linux-x64-gnu`。补装 Linux 原生包后，`npm install` 在该挂载上因不支持原子 rename 反复 `ENOTEMPTY` 失败，并使若干 `@umijs/*` 包处于半安装状态。因此 `DATA_MODE=api npm run build` 与 Playwright 截图**必须在用户的 Windows 环境执行**（与此前各轮交付一致）。用户在 Windows 上继续开发前需先执行 `npm install` 复原 node_modules（跨平台迁移的标准步骤）。
2. **部分后端测试因挂载 ACL 失败**：`.workspace/`、`demo_assets/enterprise/database/`、`test_tmp/` 等目录由 Windows 用户所有，沙箱 uid 无写权限 → `PermissionError: Operation not permitted`。这类失败与被改代码无关。
3. **依赖版本漂移**：`requirements.txt` 未钉死 fastapi/pydantic 上限；沙箱装到 fastapi 0.115.14 + pydantic 2.13.4，在 `from __future__ import annotations` 下对 `body:/db:` 参数解析异常，导致 `/auth/login` 返回 422（`test_refresh_token_...` 失败）。此为环境问题，登录路由未被本轮改动。
4. **`test_ui_routing.py`** 采集失败：`import app`→`import streamlit`，沙箱未装 streamlit（webapi 不需要）。

### 后端实测（沙箱内真实执行）

Alembic up/down/up（隔离库 `/tmp/cg_alembic.db`，绝对 script_location + 项目 alembic.ini）：

```text
Running upgrade  -> 20260711_0001, 初始业务表迁移
Running upgrade 20260711_0001 -> 20260712_0002, Phase 5A trace/notification/token-revocation
Running upgrade 20260712_0002 -> 20260713_0003, P0-2/P1-10 方案指标可空+归档
Running downgrade 20260713_0003 -> 20260712_0002
Running upgrade 20260712_0002 -> 20260713_0003
```

（本轮无新增迁移：P0-2 复用既有列，assigneeName/KPI 均为运行期计算。）

全量 pytest（分两批规避 45s 命令上限；隔离库 `/tmp/cg_test.db`，`--basetemp=/tmp/cgpt`）：

```text
批次1（tests/test_*.py 前 31 个）：248 passed, 3 failed
批次2（后 31 个，去 test_ui_routing）：257 passed, 2 failed
合计：505 passed, 5 failed, 1 collection error
```

5 个失败 + 1 采集错误逐条核对，**全部为环境原因，无一来自本轮改动**：

| 失败用例 | 根因 | 类别 |
|---|---|---|
| test_webapi::test_refresh_token_is_http_only_cookie_and_rotates | /auth/login 422（fastapi/pydantic 版本漂移，未改登录路由） | 依赖版本 |
| test_webapi::test_upload_rejects_extension_and_oversize | 写 `.workspace/` PermissionError | 挂载 ACL |
| test_confirmation::test_record_confirmation_roundtrip | 写 `.workspace/` PermissionError | 挂载 ACL |
| test_data_source::test_enterprise_source_paths_are_tenant_scoped | 写 `demo_assets/enterprise/database/` PermissionError | 挂载 ACL |
| test_enterprise_ingest::test_import_demo_csvs_into_tenant_and_smoke_ok | 同上 PermissionError | 挂载 ACL |
| test_ui_routing（采集）| `import app`→`import streamlit`（未装） | 缺可选依赖 |

被改代码的定向测试（新增 + 既有）全绿：

```text
pytest -k "natural_language or tasks_scope or decision_detail_and_export or pdf_export_masks"
4 passed, 36 deselected
pytest -k "task or overdue or countersign or approval"
7 passed, 33 deselected
```

### 前端验证（沙箱内可执行部分）

由于无法跑 umi 生产构建，用 esbuild（Linux 原生二进制）对全部改动文件做 transform 语法/JSX 校验，并用 tsc 做类型级检查：

```text
esbuild transform（11 个改动文件）：全部 OK（app.tsx / NotificationBell / HeaderActions /
  Task/Overdue / Dashboard/index / User/Profile / ImportWizard / Settings/Users /
  Decision/Generate / Decision/Approval / services/notify）
tsc --noEmit：全项目 10 处报错，均为过期 .umi 生成类型导致的环境性误报
  （history.location / RunTimeLayoutConfig，同样出现在未改动的 Login.tsx / request.ts /
  Risk/List.tsx / Incident/Detail.tsx / approval.ts / vitest.config.ts）；
  我改动的 10 个 .tsx/.ts 文件中除 app.tsx 沿用的同款环境误报外，无新增类型错误。
```

**前端待用户在 Windows 执行的验收命令**（本沙箱无法执行）：
`cd chainguard-web && npm install && $env:DATA_MODE='api'; npm run build`；
`npm test`（Vitest）；`npm run test:e2e`（Playwright，1280px/375px），并补齐规格要求的 7 张截图。

### 逐项修复记录（1~14）

| # | 问题 | 修复文件 | 测试/验证 |
|---|---|---|---|
| 1 | buyer 导出自然语言字段泄漏毛利/罚金/客户等级数字 | `src/webapi/decision_detail.py`（新增 `_deep_mask`/`_scrub_text`：按 field:cost/profit/customerLevel:view 递归清洗字符串内嵌金额与等级；GET/JSON/PDF 共用 `mask_for_requester`） | 新增 `test_decision_detail_natural_language_fields_are_scrubbed_for_buyer`（GET+JSON+PDF buyer 无 180000/632000/255000/600000/128000 且无「A类」，boss 全保留）✅ 通过 |
| 2 | GET /tasks 未落实 buyer custom 范围 | `src/webapi/routers/business.py`（`_can_manage_all_tasks`：有 task:manage 看全部，否则仅 assignee==本人；列表/详情/PATCH 三处闸门，复用 task:manage 不新增权限码） | 新增 `test_tasks_scope_enforces_custom_data_range_without_task_manage`（buyer 只见本人任务；他人详情 404、PATCH 403；scm_lead 见全部）✅ 通过 |
| 3 | app.tsx 顶栏 375px 溢出、铃铛落视口外 | `src/components/HeaderActions/index.tsx`（新，Grid.useBreakpoint 响应式；窄屏仅留「更多/通知/用户」，搜索/上报/租户/演练收进「更多」）、`src/app.tsx` | esbuild OK；需 Windows Playwright 375px 实测无横向滚动 |
| 4 | NotificationBell 弹层跳转后遮挡、无受控 open | `src/components/NotificationBell/index.tsx`（受控 open；点击先关层再标记已读再跳转；移动端 Drawer；补时间/类型标签/未读点；Escape 关闭焦点回铃铛）、`src/services/notify.ts`（加 createdAt） | esbuild OK；需浏览器实测 |
| 5 | 数据导入页 375px 截断 | `src/components/ImportWizard/index.tsx`（Steps responsive+small；字段映射 Select 宽度自适应；底部操作 wrap；section overflow 收敛） | esbuild OK；需浏览器实测 |
| 6 | Overdue 柱状图硬编码 [3,1,2]、显示 u-buyer | `src/pages/Task/Overdue.tsx`（真实逾期任务按 assigneeName 聚合；截止时间本地化；无 task:manage 隐藏操作列且仅本人）、后端 `business.py` tasks 返回 `assigneeName`、`services/typings.d.ts` | esbuild OK；后端 assigneeName 由 webapi 通过测试覆盖 |
| 7 | dashboardConfig KPI 硬编码 | `src/pages/Dashboard/index.tsx`（getKpis 覆盖 risk/high/approval/countersign/incident/overdue/mine/late/task 计数）、后端 `business.py` dashboard_kpis（真实计数，任务口径与 /tasks 一致） | esbuild OK；后端 kpis 由 webapi 覆盖 |
| 8 | 首次强制改密页只显示「个人设置」 | `src/pages/User/Profile.tsx`（mustChangePassword 时显示「管理员已重置密码，首次登录必须修改」，标题与 document.title 不再是工作台） | esbuild OK；需浏览器实测 |
| 9 | 审批页 375px 对比表裁切、固定操作区遮挡 | `src/pages/Decision/Approval.tsx`（根容器移动端 paddingBottom 让位 sticky 操作区；对比表 scroll x 内滚） | esbuild OK；需浏览器实测 |
| 10 | boss 无生成权限却显示「生成方案」 | `src/pages/Decision/Generate.tsx`（按 access.canModifyDecision 隐藏生成/重新生成，无权限显文案，不新增权限码） | esbuild OK；权限口径复用 decision:modify |
| 11 | 管理员用户表列宽错误、姓名竖排、无重置确认 | `src/pages/Settings/Users.tsx`（各列显式宽度+scroll x+ellipsis；重置密码 Popconfirm 确认→Modal 展示一次性临时密码可复制） | esbuild OK；需浏览器实测 |
| 12 | PDF 英文状态 submitted/high/ok | `src/webapi/decision_detail.py`（render_pdf 加 cn_status/cn_level，审批链状态/风险级别、决策状态、事件严重度统一中文） | 由 `test_pdf_export_masks_*` 覆盖 PDF 生成路径 ✅ |
| 13 | 方案对比基线/次优长期「数据缺失」 | `src/pages/Decision/Approval.tsx`（有值展示；缺失给具体原因文案：成本待人工测算/交期待供应商确认） | esbuild OK；需浏览器实测 |
| 14 | findDOMNode / Descriptions span / static message 警告 | 全局 `<App>`（`app.tsx`）；`Users.tsx`、`Approval.tsx` 改 App.useApp()；Approval Descriptions span 随断点收敛；`destroyOnClose`→`destroyOnHidden` | 部分修复。**findDOMNode 源自 echarts-for-react 库内部**，不换图表库无法根除，如实保留 |

### 尚未解决 / 需用户 Windows 环境闭环

- `DATA_MODE=api npm run build` 与 Playwright 1280px/375px 实测 + 7 张截图：本沙箱不可执行，须在 Windows 跑（先 `npm install`）。
- #14 的 findDOMNode 警告：echarts-for-react 库级，未根除。
- 新增前端可重复测试（NotificationBell 关层-跳转、Overdue 聚合、HeaderActions 375px）：受限于沙箱无法运行 Vitest/Playwright，未新增以免留下未验证测试；建议在 Windows 环境补齐并纳入现有 e2e 套件。

## 2026-07-15 Windows 本机闭环（Codex 实际执行）

本节对应 `phase5a_codex交接.md` 的 1~5 步，执行环境为 Windows 本机、Node `v24.18.0`、npm `11.16.0`、Python `3.13.5`。以下仅记录本次真实执行结果；前一次失败也保留，不以最终通过覆盖失败事实。

### 1. 依赖复原

在 `chainguard-web` 实际执行 `npm install`：

```text
added 117 packages, removed 152 packages, changed 24 packages, and audited 1554 packages in 25s
331 packages are looking for funding
53 vulnerabilities (9 low, 28 moderate, 14 high, 2 critical)
```

未执行会自动改版本的 `npm audit fix --force`；依赖审计提示如实保留。

### 2. Windows 续修改动

本次在 Claude 续修基础上追加的前端闭环修复：

- `NotificationBell.test.tsx`：用 `vi.hoisted` 修复 Vitest mock 初始化顺序，原业务断言未删除、未放宽。
- `NotificationBell/index.tsx`：补显式 Escape 监听，关闭移动端 Drawer 后把焦点还给通知铃铛。
- `Dashboard/index.tsx`：风险表格改为卡片内横向滚动并收敛 `minWidth/maxWidth`；首轮 E2E 的页面宽度由 `462` 修到 `360 <= 375`。
- `HeaderActions/index.tsx`：未登录或会话恢复完成前不渲染鉴权顶栏，消除登录页提前请求通知接口造成的 401 开发错误遮罩。
- `Data/Import.tsx`：375px 下标题、说明分行显示，不再把“数据导入”截成省略号。
- `ImportWizard/index.tsx`：改用 `App.useApp().message`；预检和原始预览使用稳定 row key，消除本流程的静态 message / index rowKey 警告。
- `constants/status.ts`：补 `submitted -> 待审批`，审批抽屉不再显示原始英文状态。

边界复核：`git diff -- ChainGuard/src/orchestrator.py` 为空；未进入 5B 文件范围；未增加任何角色权限码；未弱化既有测试断言。

### 3. 最终前端命令原始结果

第一次 `npm test` 暴露测试自身 hoist 错误：

```text
ReferenceError: Cannot access 'pushMock' before initialization
Test Files 5 passed | 1 failed
Tests 10 passed
```

修复 hoist 后，定向测试继续暴露真实 Escape 关层失败，修复组件行为后最终全量为：

```text
Test Files  6 passed (6)
Tests       13 passed (13)
Duration    8.36s
```

首轮 `npm run test:e2e`：

```text
8 passed, 1 failed
375px 工作台：Expected scrollWidth 462 <= innerWidth 375
```

修复 Dashboard 表格页面级溢出后，最终全量：

```text
Running 9 tests using 1 worker
ok 1  375px 工作台无横向溢出且通知铃铛在视口内
ok 2  375px 点击通知后弹层关闭再跳转
ok 3-5  登录成功/失败/安全 redirect
ok 6-8  审批中心 375px/768px/1280px 无 document 横向溢出
ok 9  推演抽屉 375px 无 document 横向溢出
9 passed (24.9s)
```

最终 `DATA_MODE=api npm run build`：

```text
√ Webpack: Compiled successfully in 11.52s
Memory Usage: 999.08 MB (RSS: 1481.55 MB)
[esbuildHelperChecker] No conflicts found.
event - Build index.html
generated D:\github_projects\Chainguard\chainguard-web\docs\route-access-map.md
```

构建仍有“bundle size significantly larger than recommended”提示；Vitest 仍输出 jsdom `getComputedStyle(pseudoElt)`、测试异步 `act` 和第三方 `rc-resize-observer/ProTable` 的 `findDOMNode` 警告。均未影响退出码，但未宣称“零 warning”。

### 4. 真实 API 栈与 7 张截图

使用全新隔离库 `ChainGuard/phase5a_windows_acceptance_20260715.db`，实际执行 Alembic `upgrade head`（`20260711_0001 -> 20260712_0002 -> 20260713_0003`）和 `src.webapi.seed`；随后启动 `uvicorn:8000 + umi(api):8001`。调度器函数 `release_overdue_tasks` 实际扫描并转换 `3` 条逾期任务。

截图目录：`codex_landing_spec/phase5a_windows_acceptance_20260715/`。

| # | 截图 | 真实验收结果 |
|---|---|---|
| 1 | `01-header-notification-375.png` | 375×812，通知铃铛可访问；全宽 Drawer 展示任务类型、时间和未读点 |
| 2 | `02-notification-jump-closed-375.png` | 点击真实 `task_overdue` 通知后到 `/task/overdue`；`visibleDialogs=0`、`aria-expanded=false`、`scrollWidth=375` |
| 3 | `03-overdue-real-aggregation.png` | 真实聚合为 3 条任务/3 名负责人：采购人员、销售/客服、财务人员；图表和明细一致 |
| 4 | `04-import-preflight-375.png` | 通过 UI 的“使用当前类型示例文件”实际上传；服务端 `verdict=OK`、预估 3 行、显示归一化预览；`scrollWidth=375` |
| 5 | `05-forced-first-password-change-375.png` | 数据库置 `must_change_password=true` 后，受保护页实际强制跳到 `/user/profile`；标题和一次性临时密码说明完整 |
| 6 | `06-approval-boss-375.png` | boss 真实审批详情；`innerWidth=375`、`scrollWidth=375`；状态“待审批”、成本/对比表/操作区可见且不遮挡 |
| 7 | `07-buyer-boss-pdf-redaction-comparison.png` | 同一真实决策报告按 buyer/boss 并排对照；buyer 为 `***`，boss 显示真实财务值 |

PDF 原文件及逐页渲染位于 `ChainGuard/output/pdf/phase5a-windows-20260715/`。先通过真实 SCM 账号调用异步方案生成，作业实际 `succeeded / progress=100`，再分别以 buyer 和 boss 登录导出：

```text
buyer.pdf  6778 bytes，2 pages，'***' 4 处
boss.pdf   6801 bytes，2 pages，'***' 0 处
buyer: 128000/600000/180000/420000 均不存在
boss : 128000/600000/180000/420000 均存在
```

四页 PDF 均用 Poppler 实际渲染并逐页目检：无重叠、截断或黑块；保留 Poppler 原始字体提示：

```text
Syntax Error: No display font for 'Symbol'
Syntax Error: No display font for 'ArialUnicode'
Syntax Error: Couldn't find a font for 'STSong-Light', subst is 'SimSun'
```

中文实际可读。验收后已关闭 Playwright 会话，并停止 8000/8001/8002 临时服务。

### 5. 全量后端复跑

受限文件沙箱内首次执行同一命令，因 `data/`、`test_tmp/pytest`、`.pytest_cache` 的 Windows ACL 被拒绝而失败；原始摘要：

```text
pytest tests/ -q
1 failed, 474 passed, 53 warnings, 40 errors in 96.15s
全部失败/错误的共同根因：PermissionError / WinError 5
```

未把该结果伪装成通过。随后脱离受限文件沙箱，在同一 Windows 工作区以同一测试命令重跑：

```text
........................................................................ [ 13%]
........................................................................ [ 27%]
........................................................................ [ 41%]
........................................................................ [ 55%]
........................................................................ [ 69%]
........................................................................ [ 83%]
........................................................................ [ 97%]
...........                                                              [100%]
515 passed, 11 warnings in 96.72s (0:01:36)
```

11 个 warning 为 FastAPI `on_event` 弃用、sklearn SVC `probability` 未来弃用和缺少可选 `cryptography` 时的预期降级提示。

### 6. 对 1~14 续修项的 Windows 核验

| 项 | Windows 本机核验 |
|---|---|
| 1 | buyer/boss 真实 PDF 对照及全量 pytest 通过；四个财务值按角色严格分离 |
| 2 | `/tasks` 作用域相关后端断言纳入 515 个全量测试并通过 |
| 3 | E2E 375px 顶栏与页面宽度通过；真实截图显示铃铛在视口内 |
| 4 | NotificationBell 3 个 Vitest 通过；真实通知 `visibleDialogs=0` 后再跳转 |
| 5 | 375px 真 API 预检截图通过；标题/副标题、Steps、绿灯与预览均可读 |
| 6 | Overdue Vitest 通过；真 API 图表与 3 人明细一致，不再显示用户 ID |
| 7 | 真实 Dashboard 显示超时任务 3，进入看板后与后端扫描结果一致 |
| 8 | Profile 2 个 Vitest 通过；真 API 强制改密路由和文案截图通过 |
| 9 | E2E 审批页 375/768/1280 与推演抽屉 375 全通过；真 boss 截图无页面级溢出 |
| 10 | 代码复核继续复用 `access.canModifyDecision`/`decision:modify`，未新增权限码；最终 build 通过 |
| 11 | Users 重置密码确认框 Vitest 通过；既有断言未弱化 |
| 12 | 真 PDF 审批链显示中文“已提交/高”，并通过 515 个后端测试 |
| 13 | 真 boss 审批截图显示本方案、基线不作为和次优方案的实际成本/交期值 |
| 14 | ImportWizard 静态 message/index rowKey 已修；第三方 ProTable/rc-resize-observer 的 `findDOMNode` 仍如实保留 |

结论：交接单 1~5 步均在 Windows 本机实际执行；最终生产构建、13 个 Vitest、9 个 Playwright E2E、515 个 pytest 全部通过，7 张指定证据齐全。未修改 orchestrator，未进入 5B，未新增权限码，未弱化测试断言。

## 2026-07-15 最终产品界面复验（Codex 实际执行）

本轮没有复用上一轮截图结论，而是在 Windows 本机重新启动真实 API 栈（`uvicorn:8000 + umi(api):8001`），使用隔离验收库 `ChainGuard/phase5a_windows_acceptance_20260715.db`，通过产品界面依次登录供应链负责人、老板、财务、采购四个角色完成复验。

### 1. 本轮真实界面闭环

- 375×812 登录页、工作台、顶栏与通知抽屉：无 document 横向溢出，通知铃铛在视口内。
- 点击真实 `task_overdue` 通知后进入 `/task/overdue`：通知层关闭，`visibleDialogs=0`、`aria-expanded=false`；桌面端图表与 3 条逾期明细一致。
- 数据导入：从界面点击“使用当前类型示例文件”，真实显示“绿灯：容量与格式预检通过”和归一化预览；页面级无横向溢出，宽表在组件内滚动。
- 老板审批：375px 审批抽屉宽度收敛到视口，摘要、确认点、方案对比、审批动作可读可操作。
- 完整推演：敏感性折线与 Pareto 散点图在 375px 内可读，无图表裁切。
- 财务追认：同一超时放行状态下真实显示“追认通过/追认异议”；本轮分别对两个隔离验收审批单提交，均成功落地并显示“已通知老板与提交人”；异议空理由先被界面拦截为“请填写说明”。
- 强制改密：将隔离验收用户 `u-buyer.must_change_password` 临时置为 `1` 后从登录页进入，真实强制跳转 `/user/profile`；截图后已恢复为 `0`，未修改用户密码。

### 2. 本轮发现并修复的窄屏问题

采购角色在 `/decision/generate/inc-supplier-shutdown?readonly=1` 打开完整推演时，底层方案卡片的 Ant Design Ribbon 角标将 document 撑到 `388px`：

```text
修复前：innerWidth=375, document.scrollWidth=388, body.scrollWidth=388
修复后（抽屉关闭）：innerWidth=375, document.scrollWidth=360, body.scrollWidth=360
修复后（抽屉打开）：innerWidth=375, document.scrollWidth=375, body.scrollWidth=360
```

修复文件：`chainguard-web/src/pages/Decision/Generate.tsx`。方案网格最小列宽改为不超过容器的 `min(340px, 100%)`，并为 Ribbon 角标预留 8px 内边距；不可行方案容器采用同一口径。新增 `chainguard-web/e2e/overflow.spec.ts` 回归“方案卡片和角标在 375px 无 document 横向溢出”，未删除或弱化原有断言。

### 3. 本轮截图与 PDF 证据

当前轮全部截图位于 `output/playwright/phase5a-final-ui-audit-20260715/`，核心证据包括：

- `01-login-375.png`、`02-dashboard-375.png`
- `03-notification-task-375.png`、`04-overdue-jump-closed-375.png`、`05-overdue-aggregation-1280.png`
- `06-import-preflight-375.png`、`07-import-normalized-preview-375.png`
- `08-approval-drawer-boss-375.png`、`09-decision-trace-375.png`、`10-pareto-chart-375.png`
- `11-ratification-actions-finance-375.png`、`12-ratify-approve-success-375.png`、`13-ratify-object-success-375.png`
- `14-forced-password-change-375.png`
- `15-buyer-redacted-trace-375.png`（修复前，可见底部 document 横向滚动条）
- `16-buyer-redacted-trace-fixed-375.png`（修复后，无横向滚动条）

老板与采购 PDF 都由本轮产品界面“导出 PDF”按钮实际下载，请求日志均为 `GET .../decision-detail/export?format=pdf 200`：

- `17-boss-decision-detail.pdf`：2 页，`600000.0/180000.0/420000.0/128000.0` 各出现 1 次，`***` 0 次。
- `18-buyer-decision-detail-redacted.pdf`：2 页，上述四个数值均出现 0 次，`***` 出现 6 次。

两份 PDF 的四页 Poppler 渲染位于 `output/pdf/phase5a-final-ui-audit-20260715/`，已逐页目检：中文可读，无重叠、截断、黑块或表格越界；Poppler 仍如实输出既有字体替代提示（`STSong-Light -> SimSun`）。

### 4. 本轮修复后的实际命令结果

`DATA_MODE=api npm.cmd run build`（沙箱内 esbuild 因 Windows `spawn EPERM` 失败后，按授权在沙箱外原命令重跑）：

```text
√ Webpack: Compiled successfully in 11.27s
Memory Usage: 1002.6 MB (RSS: 1488.86 MB)
[esbuildHelperChecker] No conflicts found.
event - Build index.html
generated D:\github_projects\Chainguard\chainguard-web\docs\route-access-map.md
Exit code: 0
```

`npm.cmd test`（同样因沙箱内 `spawn EPERM`，按授权在沙箱外原命令重跑）：

```text
Test Files  6 passed (6)
Tests       13 passed (13)
Duration    10.70s
Exit code: 0
```

Vitest 仍输出既有 jsdom `getComputedStyle(pseudoElt)`、异步 `act` 和第三方 `findDOMNode` 警告，未宣称零 warning。

新增窄屏回归 `npm.cmd run test:e2e -- e2e/overflow.spec.ts`：

```text
Running 5 tests using 1 worker
ok 1-3 审批中心 375/768/1280px 无 document 横向溢出
ok 4   推演抽屉 375px 无 document 横向溢出
ok 5   方案卡片和角标 375px 无 document 横向溢出
5 passed (25.5s)
Exit code: 0
```

真实浏览器日志未发现请求失败或运行时异常；仅有 Ant Design 静态 `message/Modal` 上下文提示和第三方 `rc-resize-observer/ProTable` 的 `findDOMNode` 弃用提示。API stderr 仅包含 Uvicorn 正常启动信息，Web stderr 为空。

本轮未再次执行全量 `pytest tests/ -q`；最近一次全量后端实跑结果仍为本文件上一节记录的 `515 passed, 11 warnings in 96.72s`。本轮唯一产品代码变更为前端响应式样式，已用生产构建、13 个 Vitest、5 个定向 Playwright 以及真实 375px 界面复验闭环。

最终结论：Phase 5A 的产品界面验收通过；本轮发现的最后一个 375px Ribbon 页面级横向溢出已修复并加回归。未修改 orchestrator，未进入 5B，未新增权限码，未弱化既有测试断言。

---

## 2026-07-15 Phase 5A 完整度核对与阶段闸门结论

按 `10_Phase5_总规格.md` 5A 节逐项直读磁盘核验（非仅信文档）。

### 代码落点核对（全部到位）

| 规格项 | 核验证据 | 结论 |
|---|---|---|
| 5A-1/3 完整推演+审计 | `decision_details`/`decision_audits` 表；`GET /incidents/{id}/decision-detail`；`format==json/pdf` 导出；`render_pdf` | ✓ |
| 5A-2 通知规则+逾期扫描 | `notification_rules` 表；10 类事件全接（task_assigned/urged/overdue、import_succeeded/failed、risk_high、approval_submitted、countersign_*、decision_succeeded/failed）；`notify_event` 唯一入口；`release_overdue_tasks` 已入 `api.py` 调度线程 | ✓ |
| 5A-4 令牌吊销 | `refresh_tokens`/`revoked_tokens` 表 + jti | ✓ |
| 5A-5 账户 | `must_change_password` 列、管理员重置、首登改密守卫、忘记密码提示 | ✓ |
| 5A-6 导入预检 | verdict 三态 + `normalized.previewRows` 归一化预览 + PARSE_ERROR/INSUFFICIENT_DISK 硬阻断 | ✓ |
| 5A-7 监控 | `config/prometheus.yml`、`alerts.yml`、compose node-exporter、`chainguard_jobs_pending` gauge | ✓ |
| 硬要求·追认闭环 | `ratify_approve`/`ratify_object` | ✓ |
| 硬要求·detail 脱敏 | `mask_for_requester`（本轮补自然语言递归脱敏）| ✓ |
| 可选·价值看板 | `chainguard-web/src/pages/Report/Executive.tsx` | ✓ |
| C3 邀请建号 | `User/Join.tsx` + `Settings/Users.tsx` | ✓ |
| 迁移 up/down/up | 0001→0002→0003，本会话实测全绿 | ✓ |
| 本轮 14 项 | 代码全在；后端 505 passed（5 失败全环境原因） | ✓ |

### 阶段闸门结论（重要）

**5A 代码完整、后端已验，但尚未达到"可签收"状态。** 差最后一道（即当初打回本轮的那道）验收门：本轮 P1 界面修复 #3~#14 的
`DATA_MODE=api npm run build 零 error` + 全量 `pytest tests/ -q` 全绿 + 规格要求的 7 张 375/1280px 截图。
该三项无法在 Cowork Linux 沙箱执行（node_modules 为 Windows 原生），须在用户 Windows 环境闭环。**这三项通过后 5A 方可关闭。** 已知遗留：#14 的 findDOMNode 属 echarts-for-react 库级警告，未根除。

**开启 5B 需同时满足两闸，缺一不可：**
1. 上述 5A Windows 验收关闭；
2. `11_Phase5B_前置产出.md`（当前 v1 草稿，评审方主笔 2026-07-12）**评审通过**——规格明确"5B 动工须待前置产出评审通过"。

**建议顺序**：Codex 跑 Windows 验收关 5A 的同时，并行启动 5B 前置产出评审（规格评审动作，不受 5A 验收阻塞）；两闸皆过后再动 5B 的 C2（实体表）第一批。**5B 实现不要现在开工。**

## 2026-07-17 Windows 最后一闸复核（Codex 实际执行）

本节只关闭上节尚未关闭的 5A Windows 验收闸门；不进入 5B 实现。

### 命令复核

- 在 `chainguard-web` 执行 `$env:DATA_MODE='api'; npm.cmd run build`：退出码 `0`，Webpack 在 `11.24s` 编译成功，`esbuildHelperChecker` 无冲突，并完成 `route-access-map.md` 生成。输出保留 bundle 体积建议，但没有 error；未将该 warning 说成零 warning。
- 在 `ChainGuard` 执行 `python -m pytest tests/ -q`：受限文件沙箱首次因 `data/` 与 `test_tmp/` 正常临时写入被 Windows ACL 拒绝而失败，未计为通过；随后按同一命令在本机非沙箱环境复跑，结果为 `515 passed, 11 warnings in 98.89s`，退出码 `0`。11 条为 FastAPI/sklearn 弃用提示和可选 cryptography 降级提示。

### 7 张规格证据复核

不重命名、不伪造、不重新生成既有证据。逐张读取并目检已由真实 API 栈产生的 `codex_landing_spec/phase5a_windows_acceptance_20260715/` 证据：

| # | 文件 | 尺寸 | 复核内容 |
|---|---|---:|---|
| 1 | `01-header-notification-375.png` | 375×812 | 移动端通知抽屉、任务类型和未读点可见 |
| 2 | `02-notification-jump-closed-375.png` | 375×812 | 通知跳转后的逾期看板，抽屉已关闭 |
| 3 | `03-overdue-real-aggregation.png` | 1280×900 | 按负责人真实聚合，3 条逾期任务与明细一致 |
| 4 | `04-import-preflight-375.png` | 375×812 | 导入预检绿灯、容量结论和归一化预览可见 |
| 5 | `05-forced-first-password-change-375.png` | 375×812 | 首次登录强制改密说明和完整表单可见 |
| 6 | `06-approval-boss-375.png` | 375×812 | boss 审批详情、成本、方案对比和操作区可见 |
| 7 | `07-buyer-boss-pdf-redaction-comparison.png` | 1400×1000 | 同一报告 buyer 为 `***`、boss 显示真实财务值 |

PDF 原件与逐页渲染仍位于 `ChainGuard/output/pdf/phase5a-windows-20260715/`，未改动。

### 阶段结论更新

本轮最后一闸的三项均已具备实际证据：API 生产构建退出码 0、全量 pytest 全绿、7 张规定视口/对照截图齐全且已复核（其中 5 张为 375px、逾期聚合为 1280px、PDF 对照为双栏 1400px）。因此，**Phase 5A Windows 验收闸门关闭，5A 可签收/关闭。**

关闭 5A 本身不自动开启 5B。同日后续已将 `11_Phase5B_前置产出.md` 修订为 v2，并完成黄金参照字段与真实产品界面列覆盖核对；复审结论为通过。至此两道开工闸门均已关闭，但本轮只完成规格修订与界面核实，尚未开始 5B C2 实体表或其他实现。
