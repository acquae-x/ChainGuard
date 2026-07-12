# TASK-203 认证接入与 access.ts 权限改造

对应总指令 Phase 2 §2.3。规格来源：`codex_landing_spec/00` > `codex_frontend_spec/02`。级别 C（前端）。
**依赖 TASK-201（request）、TASK-202（dataMode）。承重点见 ADR §5。**

## 背景与目标

登录页对接真实 `/auth/login`；`getInitialState` 调 `/auth/me`；`access.ts` 删除所有前端硬编码 role→权限推导，改为纯消费后端返回的 `permissions`。

## 涉及文件

- 改 `chainguard-web/src/services/user.ts`（login/currentUser/logout/refresh：api 模式走真实端点，mock 模式保留现逻辑）
- 改 `chainguard-web/src/app.tsx`（`getInitialState` 调 `/auth/me` 拿 user+permissions+tenant）
- 改 `chainguard-web/src/access.ts`（去 role 硬编码）
- 可能改 `codex_frontend_spec/02`（若需新增菜单权限码，先改规格）
- 配合后端 `ChainGuard/src/webapi/.../ROLE_PERMISSIONS`（若权限码缺发放，提 backend 子任务，见下）

## 实现要求

1. **认证**：
   - `login` api 模式 → `POST /auth/login`（account+password）→ 存 JWT 到 cookie（前端可读 + `SameSite=Lax`，HttpOnly 由后端 Set-Cookie 时预留）。mock 模式保留 Demo@1234 逻辑。
   - `currentUser` / `getInitialState` api 模式 → `GET /auth/me` 返回 `{user, permissions, tenant}`。
   - token 过期 → 尝试 `POST /auth/refresh`；失败再跳登录。
2. **access.ts 改造（关键，按 ADR §5 顺序执行）**：
   - 先把现有硬编码 role 门禁逐个映射为权限码：`canTask`→`menu:task:view`、`canTaskManage`→`task:manage`、`canDataLogistics`→`data:logistics:view`、`canCase`→`menu:case:view`、`canReport`→`menu:report:view`、`canSettings`→`settings:view`、`canSettingsAdmin`→`settings:admin`、`canApprovalConfig`→`approval:config`、`canAudit`→`audit:view`、`canData(isAdmin)`→并入 data 权限集。命名以 `codex_frontend_spec/02` 现有码为准，不足才新增。
   - **核对**：把这些码与 02 能力矩阵、后端 `ROLE_PERMISSIONS` 三方对齐；缺的先在 02 补规格、再在后端补发放（后端改动另开 `TASK-205-backend-权限码补齐.md` 交 Codex，附 9 角色 × 新码矩阵与测试）。
   - 对齐后，`access.ts` 只保留 `permissions.includes(...)` / `any(...)`，**删除所有 `role === ...` 分支**。
3. 不得用 localStorage/sessionStorage 存业务数据；token 走 cookie。

## 验收标准（对应 §C）

- 9 个演示账号真实登录成功（api 模式），`/auth/me` 驱动菜单与按钮。
- 菜单/按钮/字段权限与 `codex_frontend_spec/02` 矩阵**逐条一致**，重点抽查：buyer 看成本=***、auditor 全只读、admin 无审批按钮。
- `access.ts` 中不再出现 `role === 'xxx'` 硬编码分支（grep 验证）。
- 刷新页面后登录态与权限保持（来自 cookie + /auth/me），业务数据不丢。

## DoD

登录/权限两模式均通；access.ts 纯 permission 消费；若涉及后端权限码补齐，TASK-205 一并交付并回归；9 账号矩阵抽查通过；提交物附 route-access-map 对齐说明。
