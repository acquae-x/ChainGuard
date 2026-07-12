# TASK-204 各 service 双模式接线（api ↔ mock）

对应总指令 Phase 2 §2.2（逐 service）。规格来源：`codex_landing_spec/00` > `services/*.ts` 现有签名。级别 C（前端）。
**依赖 TASK-201/202/203。工作量最大的一环。**

## 背景与目标

把 `chainguard-web/src/services/*.ts` 每个导出函数改为双模式：api 模式调 `/api/v1` 真实端点并把响应映射回现有 `API.*` 结构；mock 模式走 `workflowStore`。**函数签名与返回结构不变**，页面层零改动。端点映射见 `ADR-Phase2 §3`。

## 涉及文件（逐个）

`user.ts`(见 TASK-203) `risk.ts` `incident.ts` `decision.ts` `approval.ts` `task.ts` `settings.ts`(含审计) `dashboard.ts` `notify.ts` `data.ts` `onboarding.ts` `report.ts`。

## 实现要求

1. 每个函数用 TASK-202 的 `pick(apiFn, mockFn)` 二选一；mock 分支即现有实现，原样保留。
2. **响应映射**：后端 camelCase → 现有 `API.*` typings。字段不齐时以 typings 为准补齐/默认值，不得让页面拿到 undefined 崩溃。
3. **决策生成异步**：`decision.generateProposals` api 模式 → `POST /incidents/{id}/proposals:generate` 得 `jobId` → 轮询 `GET /jobs/{jobId}` 到 succeeded/failed（前端轮询间隔 1~2s，最长与后端 60s 超时对齐），succeeded 后取 proposals。mock 模式保留同步返回。
4. **导入**：`data.parseFile` 保持前端 SheetJS 解析；`getFieldMapping/validateRows/确认/执行` api 模式对接 `/imports/*`（upload→preflight→confirm→execute→轮询 GET /imports/{id}）。复用后端既有 preflight/ingest 模块，不重写。
5. **缺口按 ADR §4 处理**：
   - 通知已读、自定义字段 PATCH/DELETE（缺口-A）：api 模式本地乐观更新 + `// TODO 后端补` 注释，不谎报成功。
   - 数据 5 表读写（缺口-B）：逐表核对后端端点，无则该表 api 模式回退 mock 且黄条标注，列 TODO。
   - onboarding（缺口-C）：**保留 mock**（总指令允许向导进度走 mock 服务端保存），注释说明。
   - report 三页（缺口-D，P2）：保留 mock，保持可替换结构。
6. 不改 `workflowStore.ts`；不引入 axios/redux；不使用 localStorage/sessionStorage 存业务数据。

## 验收标准（对应 §D）

- api 模式后端起着时，**四条核心流程真实数据走通**：①风险→事件→生成方案（异步轮询）→审批通过→任务生成→审计可查；②登录三账号权限差异；③数据导入 upload→preflight→execute；④仪表盘 KPI/待办来自后端。全程无死链、无白屏。
- 每个 service 的 mock 分支仍可独立运行（`DATA_MODE=mock`）。
- `npm run build` 零 error。
- 提交物列出：每个 service 的 api 端点、映射说明、缺口处置与 TODO。

## DoD

12 个 service 双模式全部合入；四条核心流程 api 模式录屏/截图或 curl 佐证；mock 模式回归通过；缺口 TODO 清单明确；`workflowStore.ts` git diff 为空。
