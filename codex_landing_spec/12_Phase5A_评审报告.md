# Phase 5A 评审报告（结论：复核后通过，待用户本机截图实测关闭）

评审时间：2026-07-12。评审方式：直读磁盘逐项对照 10 号总规格 5A 节核验。

## 核验通过项（主体质量高）

| 项 | 结果 |
|---|---|
| 5A-1 后端 | ✅ decision_details/decision_audits 租户表、作业持久化（含敏感性数据）、GET decision-detail、导出 JSON/PDF；迁移 0002 up/down/up 实测 |
| 安全硬要求 | ✅✅ 脱敏单一路径（mask_payload + SENSITIVE_KEYS 硬性递归兜底），detail/JSON/PDF 三出口共用；buyer/boss 回归测试 + pypdf 实提 PDF 对照证据——这条做得教科书级 |
| 追认闭环 | ✅ ratify_approve/ratify_object（异议必填理由、审计留痕、不回滚任务）；前端按钮时序判断正确（仅超时放行且未追认时显示） |
| 5A-4→5A-5 | ✅ jti 签发表+吊销表、刷新轮换/登出/改密全吊销、过期清理；/user/profile 页+路由、管理员重置临时密码、首登改密守卫、忘记密码提示 |
| 5A-2 部分 | ✅ notification_rules 表+全矩阵种子；5 分钟聚合（同人同事件同对象未读合并）；决策完成/失败、会签请求/完成/拒签/超时放行 7 类事件接入；铃铛统一 /notifications 单源 |
| 5A-7 部分 | ✅ monitoring profile + prometheus.yml + alerts.yml 三规则文件 |
| 推演前端 | ✅ DecisionTrace 抽屉双入口（方案页+审批页）、确认点清单、导出双按钮；reportlab 已入运行时依赖 |
| 回归与诚实度 | ✅ 497 passed、build 零 error、截图受限如实声明未伪造 |

## 必修项（不通过的原因）

1. **通知闭环断了六类事件**：task_assigned / task_urged / task_overdue / import_succeeded / import_failed / risk_high 规则种进了表，但**全无调用点**——任务生成（_create_execution_tasks）、催办、导入作业完成/失败处未接通知；**任务逾期扫描作业未实现**（规格明确要求在调度器上加逾期扫描）。用户可感知的"铃铛覆盖任务/导入"（09 验收 6 项之一）落空。
2. **规则表是死数据**：notify_roles 收件人由调用点硬编码，完全不读 notification_rules——"规则即数据"的设计意图（未来自定义订阅=开放这张表的 CRUD）落空。修法：统一 `notify_event(db, tenant_id, event_type, context)` 从规则表解析 recipient_strategy（trigger/assignee/submitter/approver/角色码），调用点只报事件不定收件人。
3. **5A-6 完全未做**：导入预检仍是原始 JSON `<pre>`（三态徽标/磁盘余量/预计增量未实现），归一化预览表格未实现——同为 09 验收 6 项之一，且是用户实测点名过的痛点。

## 应修项

4. Pareto 前沿缺失（game_analysis 未持久化、前端无图）；敏感性展示为 Tag 列表而非曲线（可接受的简化，但需在交付材料明示）；敏感性扫描点硬编码 [360,720,1080]（demo 量级——5B 接真实数据时必须按当前库存比例取点，先记入 11 号文档遗留）。
5. 告警三条规则两条是死的：`chainguard_jobs_pending` 指标无人导出；DiskUsageHigh 依赖 node_exporter 而 compose 未含。补指标导出 + compose 加 node-exporter（monitoring profile 内），或改用可用表达式。
6. 审批提交事件（approval_submitted）有规则无调用（提交时仅通知了 finance 会签，对应等级审批人未收提醒），并入必修 1 一起接。

## 记入后续

- AI 解释三层的"关键因素/证据链"当前是硬编码占位文案（EXP-019 写死）——5B E-3/C1 接真实 explanation 与经验引用时替换，已记 11 号文档。
- 截图验收（6 项可感知 + 追认 + PDF 对照页面）因实现环境无浏览器未完成——修复复审通过后由用户本机实测统一补。

## 打回指令（原样转发实现方）

> Phase 5A 评审不通过，读 `codex_landing_spec/12_Phase5A_评审报告.md`，修必修 1–3 与应修 4–6：
> 1. 通知统一入口 notify_event 消费 notification_rules（recipient_strategy 解析含 trigger/assignee/submitter/approver），现有 7 个调用点迁移；接入六类缺失事件（任务生成/催办、导入成功/失败、新高风险、审批提交通知审批人）；调度器新增任务逾期扫描（每 5 分钟，逾期置 status=overdue 并通知负责人+scm_lead，幂等防重复通知）。
> 2. 导入向导第 4 步：预检红绿灯三态徽标 + 磁盘余量/预计增量数字 + 消息列表（⛔ 时"仍要导入"禁用）；归一化预览表格（服务端 normalized 数据，表名+行数+前 N 行）。
> 3. 作业持久化补 game_analysis（Pareto 27 组合），推演约束段加可折叠散点图（ECharts）；敏感性改用 ECharts 折线。
> 4. 导出 chainguard_jobs_pending 指标（观测既有 Metrics 处补 Gauge）；monitoring profile 加 node-exporter 或改 DiskUsageHigh 表达式。
> 5. 每项带测试；完成后 pytest 全量 + build 原始输出追加 phase5a_交付材料.md 修复记录。禁止声称未实际执行的验证。

## 复核记录（2026-07-12，通过）

必修 1–3 与应修 4–6 全部核验到位：notify_event 统一入口消费规则表（trigger/assignee/submitter/approver/finance_if_required 策略解析完整，聚合窗口从规则读取），六类事件全部接入，逾期扫描 release_overdue_tasks 已入调度循环（含幂等测试）；导入红绿灯三态+磁盘缺口字节数+归一化预览表格+硬阻断禁用强制导入；game_analysis 持久化 + Pareto ECharts 散点/前沿虚线；chainguard_jobs_pending 指标导出 + node-exporter 入 monitoring profile（含测试）；审批提交通知审批人。

复核发现一处残留由评审方直接修复：**通知直达链接路由错位**（后端写的 /tasks/mine、/tasks/{id}、/incident/detail/{id} 均非前端真实路由，点击 404）——已改为 /task/mine、/task/overdue、/incident/{id}，同步修正对应测试断言。教训记档：通知 target 属于前后端契约，后续新增通知必须对照 config/routes.ts。

**结论：5A 代码评审通过。** 关闭条件：用户本机 `pytest tests/test_webapi.py -q` 复跑（评审方改动后确认）+ 截图实测（6 项可感知变化 + 追认 + buyer/boss PDF 对照 + 通知点击直达验证）。
