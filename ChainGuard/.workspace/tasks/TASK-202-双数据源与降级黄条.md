# TASK-202 双数据源 DATA_MODE 与降级黄条

对应总指令 Phase 2 §2.2。规格来源：`codex_landing_spec/00`。级别 C（前端）。
**这是 Phase 2 降级设计的核心，先于 TASK-204 完成。**

## 背景与目标

每个 service 需能在 `api`（真实后端）与 `mock`（现有 `workflowStore`）之间切换。`workflowStore.ts` **完整保留**，作为离线演示与后端不可用时的**显式**降级：页面顶部出黄条"当前为演示数据模式"，**禁止静默降级**。

## 涉及文件

- 新增 `chainguard-web/src/services/dataMode.ts`
- 改 `chainguard-web/config/config.ts`（`define` 注入 `DATA_MODE`）
- 新增 `.env.example` 与 `.env.development`（含 `DATA_MODE=api` / 可切 `mock`）
- 改 `chainguard-web/src/app.tsx`（布局外层挂黄条）
- 不改 `workflowStore.ts`（保持不变）

## 实现要求

1. `DATA_MODE=api|mock`，默认 `api`。经 umi `define: { 'process.env.DATA_MODE': JSON.stringify(process.env.DATA_MODE || 'api') }` 注入。
2. `dataMode.ts` 导出：`DATA_MODE` 常量、`isApiMode()`；全局降级状态用 zustand（禁止 redux/localStorage）——`markBackendDown(reason)`、`isBackendDown()`、`resetBackend()`，供 request.ts 调用。
3. 区分两种黄条文案：
   - `DATA_MODE=mock`（人为演示）：黄条"当前为演示数据模式"。
   - api 模式但后端不可用（`markBackendDown`）：黄条"后端服务暂不可用，正在展示离线数据/请稍后重试"。**此时不自动改写 mock 数据**，仅提示；由各 service 决定是否回退 mock 展示（回退时黄条常驻）。
4. 黄条组件（antd Alert，banner 型）挂在 `app.tsx` 的 `childrenRender` 外层，全局可见、可手动关闭但刷新后据状态重现。
5. `dataMode.ts` 暴露 `pick(apiFn, mockFn)` 辅助器，供 TASK-204 每个 service 统一二选一，避免各文件重复 if。

## 验收标准（对应 §B）

- `DATA_MODE=mock` 时全站走 workflowStore，行为与 Phase 1 演示一致，黄条常驻。
- `DATA_MODE=api` 且后端关闭：出现"服务暂不可用"黄条，页面不白屏、不静默显示假数据（除非明确回退且黄条提示）。
- `workflowStore.ts` 无改动（git diff 为空）。

## DoD

机制合入并被 TASK-204 复用；两种模式手动切换均可运行；黄条在两种降级场景正确显示；提交物列出自查结果。
