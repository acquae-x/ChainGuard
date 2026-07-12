# Phase 2 验收清单（前端接入真实后端）

依据总指令 §2.4 + `codex_frontend_spec/00` 硬性验收 + 变更控制红线。Codex 自查逐项打勾，Claude 回归复核。

## 前置：红线不得触碰（变更控制 A 级）

- [ ] `workflowStore.ts` git diff 为空（mock 演示行为不变）。
- [ ] mock 模式下台风-宁波港案例数字（风险指数 70.25 等）与 Phase 1 一致。
- [ ] 未改任何风险/评分公式、`config/*.yaml`、`data/*.json`（本阶段纯前端，不应触及）。
- [ ] 后端 62 测试文件 / Phase 1 484 测试仍全绿（若因 TASK-205 动了后端权限码，需回归并附输出）。

## §A 网络层（TASK-201）

- [ ] `src/utils/request.ts` 存在，基于 @umijs/max request，超时 10s。
- [ ] 错误信封 `{code,message,traceId}` 解析并 message.error。
- [ ] 401 清 token 跳登录；网络错误提示"服务暂不可用"并触发降级标志。
- [ ] 重试仅幂等 GET（≤2 次指数退避）；写操作不重试。
- [ ] 无 axios、无 redux、无 localStorage/sessionStorage 存业务数据。

## §B 双数据源与降级（TASK-202）

- [ ] `DATA_MODE=api|mock` 可切；默认 api；`.env.example`/`.env.development` 就位。
- [ ] `DATA_MODE=mock` 全站走 workflowStore，黄条"演示数据模式"常驻。
- [ ] api 模式后端关闭：出现"服务暂不可用"黄条，不白屏、不静默显示假数据。
- [ ] proxy `/api → 127.0.0.1:8000` 无 rewrite。

## §C 认证与权限（TASK-203）

- [ ] 9 个演示账号 api 模式真实 `/auth/login` 登录成功。
- [ ] `getInitialState` 走 `/auth/me`，permissions 驱动菜单/按钮。
- [ ] `access.ts` 无 `role === 'xxx'` 硬编码分支（grep 验证）。
- [ ] 权限矩阵与 `codex_frontend_spec/02` 逐条一致；抽查：buyer 成本=***、auditor 全只读、admin 无审批按钮。
- [ ] 若新增菜单权限码：02 规格已更新 + 后端 ROLE_PERMISSIONS 已发放 + 有测试（TASK-205）。
- [ ] 刷新页面登录态与权限保持。

## §D 各 service 接线（TASK-204）

- [ ] 四条核心流程 api 模式真实走通：风险→事件→生成方案(异步 jobId 轮询)→审批通过→任务生成→审计可查。
- [ ] 决策生成走 202+jobId 轮询，不是同步假返回。
- [ ] 数据导入 upload→preflight→confirm→execute→进度 真实对接。
- [ ] 仪表盘 KPI/topRisks/myTasks/pendingApprovals 来自后端。
- [ ] 每个 service mock 分支仍可独立运行。
- [ ] 缺口 A/B 已按处置执行且不谎报成功；onboarding(C)/report(D) 保留 mock 且注释说明。

## §E 总指令 §2.4 硬验收

- [ ] `npm run build` 零 error。
- [ ] 后端起着时 4 条核心流程真实数据走通；后端关掉切 mock 仍可演示且有黄条。
- [ ] 9 账号真实登录，菜单/按钮/字段权限与 02 矩阵一致（后端 permissions 驱动）。
- [ ] 刷新页面业务数据不丢（已在数据库）。

## §F 提交物（总指令"提交物要求"）

- [ ] ①变更文件清单 + 每个文件一句话说明。
- [ ] ②新增/对接端点清单表（方法/路径/权限码/请求响应示例）。
- [ ] ③测试运行结果原文（前端 build + 若动后端的 pytest）。
- [ ] ④已知限制与 TODO 列表（含缺口 A/B、遗留事项 1 归属后端）。
- [ ] 不得声称完成未实现功能。

## 回归验证（Claude 复核，来自变更控制"Codex 产出未经回归验证不算完成"）

- [ ] 独立复跑 `npm run build`；抽查 access.ts grep；实测两模式切换；核对 workflowStore diff 为空；4 条流程 api 模式实走一遍。
