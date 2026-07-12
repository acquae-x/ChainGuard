# ADR Phase 2：前端接入真实后端（架构设计与端点映射）

状态：已定稿，供 Codex 实现（对应 TASK-201~204）。
规格来源顺序：`codex_landing_spec/00 总指令` > `codex_frontend_spec/02 权限` > `chainguard-web/src/services/*.ts` 现有签名 > 其他。
本阶段为 C 级（前端）改动，偏离规格先改规格再改代码。

## 0. 设计目标（来自总指令 Phase 2）

把 `chainguard-web/` 从内存 mock（`workflowStore.ts`）切到 Phase 1 已交付的 `/api/v1` 真实后端，同时**完整保留 mock 作为显式降级**（后端不可用时页面顶部黄条提示，禁止静默降级）。四条核心流程真实数据走通、9 账号权限由后端 `permissions` 驱动、刷新不丢数据。

## 1. 分层设计

```
pages / components
      │  （不动，只依赖 services 的现有函数签名）
services/*.ts   ← 每个导出函数内部按 DATA_MODE 分流
      ├── api 模式  → apiClient(request.ts) → /api/v1/...
      └── mock 模式 → workflowStore.ts（完整保留）
request.ts（新增，基于 @umijs/max request）
proxy: /api → http://127.0.0.1:8000
```

**不变量（不得破坏）**
- `services/*.ts` 每个导出函数的**签名与返回结构保持不变**，页面层零改动即可两模式通用。api 模式必须把后端 camelCase 响应映射回现有 `API.*` typings 结构。
- `workflowStore.ts` 一行不删，mock 模式行为与 Phase 1 演示完全一致。
- 演示数字红线：mock 模式下台风-宁波港案例数字（风险指数 70.25 等）不变；api 模式数字来自后端 seed（应与 mockData 对齐，Phase 1 已声明对齐）。

## 2. DATA_MODE 双数据源机制

- 环境变量 `DATA_MODE=api|mock`，默认 `api`；`.env.development` 可切 `mock`。经 umi `define` 注入前端（`config.ts` 的 `define: { 'process.env.DATA_MODE': ... }`），运行时可读。
- 统一出口 `src/services/dataMode.ts`：导出 `DATA_MODE` 常量与 `isApiMode()`；**降级事件**：api 模式下 apiClient 探测到后端不可用（网络错误 / `/readyz` 失败）时，置全局降级标志并触发黄条，不自动改 mock 数据（黄条文案："当前为演示数据模式 / 服务暂不可用"，二者区分）。
- 黄条组件挂在 `app.tsx` 布局 `childrenRender` 外层，读全局降级标志（zustand 或 useModel，禁止 redux）。

## 3. 端点 ↔ service 映射表（已逐个核对 Phase 1 后端）

后端前缀统一 `/api/v1`。✅=后端已有；⚠=缺口（见 §4）。

| service 导出 | 后端端点 | 状态 |
|---|---|---|
| user.login / currentUser / logout | POST /auth/login、GET /auth/me、POST /auth/logout | ✅ |
| （token 刷新） | POST /auth/refresh | ✅ |
| risk.getRisks | GET /risks（分页/筛选） | ✅ |
| risk 矩阵 / 详情 / 改状态 | GET /risks/matrix、GET /risks/{id}、PATCH /risks/{id}/status | ✅ |
| incident.getIncidents/getIncident | GET /incidents、GET /incidents/{id} | ✅ |
| incident 创建 / 更新 / 删除 | POST /incidents、PATCH /incidents/{id}、DELETE /incidents/{id} | ✅ |
| incident.getImpact / getTimeline | GET /incidents/{id}/impact、/timeline | ✅ |
| decision.generateProposals | POST /incidents/{id}/proposals:generate → 202 {jobId}；GET /jobs/{jobId} 轮询 | ✅ |
| decision.getProposalsForIncident / detail | GET /proposals?incidentId、GET /proposals/{id} | ✅ |
| decision.recalc / getExplanation | PATCH /proposals/{id}、GET /proposals/{id}/explanation | ✅ |
| decision.submitForApproval / draft | POST /proposals/{id}/submit、/draft、GET /incidents/{id}/draft | ✅ |
| approval.getApprovals / detail | GET /approvals、GET /approvals/{id} | ✅ |
| approval 动作（通过/驳回/转办/撤回/加签） | POST /approvals/{id}/{action} | ✅ |
| task.getTasks / updateTaskStatus / urge | GET /tasks、PATCH /tasks/{id}、POST /tasks/{id}/urge | ✅ |
| settings.getAuditLogs | GET /audit-logs（按人/对象/时间分页） | ✅ |
| dashboard KPI/topRisks/myTasks/pendingApprovals | GET /dashboard/kpis、/top-risks、/my-tasks、/pending-approvals | ✅ |
| notify.getNotifications | GET /notifications | ✅ |
| notify 标记已读 | （无） | ⚠ 缺口-A |
| data.getDataTable / createRecord | GET /settings/...（各数据表）/ 导入 | ⚠ 缺口-B（数据表读写端点需核对） |
| data 导入：parseFile/getFieldMapping/validateRows | 客户端 SheetJS 解析 + POST /imports/upload、/{id}/preflight、/confirm、/execute、GET /imports/{id} | ✅（parse 保持前端） |
| settings.getUsers/createUser + 用户 CRUD | GET/POST/PATCH/DELETE /settings/users | ✅ |
| settings.getRoles/saveRole + 角色 CRUD | GET/POST/PATCH/DELETE /settings/roles | ✅ |
| settings.getDepartments / getTenant | GET /settings/departments、/settings/tenant | ✅ |
| settings.getFieldSchema / saveField | GET/POST /settings/custom-fields | ✅（PATCH/DELETE 暂缺，见缺口-A） |
| onboarding.getTemplates/saveProgress/applyTemplate/startDrillIncident | （无独立端点） | ⚠ 缺口-C |
| report.getExecutive/Operation/Response | （无 /reports） | ⚠ 缺口-D（P2） |

## 4. 缺口与处置（不阻塞 Phase 2 前端，按下述处理，写入已知限制）

- **缺口-A（通知已读 / 自定义字段 PATCH·DELETE）**：后端次要缺失。Phase 2 前端对应动作在 api 模式下降级为本地乐观更新 + TODO 注释，或走 mock；列入 TODO 交后端补。**不许**假装成功后误导用户。
- **缺口-B（数据表 5 表读写）**：`data.getDataTable/createRecord` 覆盖 material/supplier/customer/order/inventory。需 Codex 逐个核对后端是否有对应查询端点；无则该表 api 模式暂走 mock 并黄条标注，列 TODO。
- **缺口-C（初始化向导）**：总指令 00 明确"向导进度走 mock 服务端保存"，故 onboarding 系列**允许保留 mock**，不算缺口，注释说明即可。
- **缺口-D（报表三页）**：P2 骨架，本阶段保持 mock，`services/` 保留可替换结构。
- **遗留事项 1（决策作业接入真实事件上下文）**：属**后端** MVP 占位（Phase 1 已声明），不在 Phase 2 前端范围。前端只按 jobId 轮询，拿到什么展示什么。单列后端独立任务，不塞进本阶段前端任务。

## 5. §2.3 认证与权限的承重点（务必先做，否则菜单会碎）

`access.ts` 当前仍有**硬编码 role 判断**：`canData(isAdmin)`、`canTask(role!=='admin')`、`canTaskManage(boss/scm_lead)`、`canDataLogistics(scm_lead)`、`canCase/canReport(role!=='warehouse')`、`canSettings/canAudit/canApprovalConfig(role 枚举)`。

总指令 §2.3 要求"删除前端硬编码角色→权限推导，全部消费后端 permissions"。因此**前置动作**：把上述每个 role 门禁映射成一个权限码（如 `menu:case:view`、`menu:report:view`、`settings:view`、`audit:view`、`task:view`、`data:logistics:view` 等），核对 `codex_frontend_spec/02` 能力矩阵 + 后端 `ROLE_PERMISSIONS` 是否已发放这些码；缺的先补规格（02）再补后端发放，最后 access.ts 改为纯 `permissions.includes(...)`。**顺序不能反**：先对齐权限目录，再删 role 逻辑，否则 9 账号菜单会缺项/多项，直接掉 §2.4 验收。

## 6. 验收锚点（详见 acceptance/Phase2_验收清单.md）

`npm run build` 零 error；后端起着时四条核心流程真实数据走通；后端关掉切 mock 仍可演示且有黄条；9 账号权限矩阵与 02 一致（后端 permissions 驱动）；刷新页面业务数据不丢。
