# Phase 2 评审报告（结论：有条件通过）

评审时间：2026-07-11。评审方式：直读磁盘逐文件核对（不经沙盒挂载），交叉比对后端真实路由契约。

## 核验通过项

| 验收项 | 结果 |
|---|---|
| 网络层 request.ts | ✅ 超时 10s、错误信封解析（code/message/traceId）、401 清 token 跳登录、仅幂等 GET/HEAD 指数退避重试 ×2、Bearer 注入、silent 模式，全部符合 §2.1 |
| 双数据源 dataMode.ts | ✅ DATA_MODE 由 umi define 注入；pick() 二选一；降级需显式 fallbackToMock 且仅网络错误触发，无静默降级；成功自动清除降级态 |
| 降级黄条 | ✅ DegradeBanner 存在并挂载 app.tsx，演示/后端不可用两种文案 |
| 认证 | ✅ login→/auth/login 存 token cookie；getInitialState→/auth/me；logout 双清理 |
| access.ts 去硬编码 | ✅ 全部消费后端权限码，无 role === 残留；权限码集合与 seed.py 对齐；发现的两处前后端口径缺口（data:view、admin 菜单）如实列为后端跟进项而非悄悄绕过 |
| 决策异步作业 | ✅ 202+jobId → 1.5s×40 轮询（与后端 60s 超时对齐）→ 拉取方案 |
| 审批动作 | ✅ POST /approvals/{id}/{action} 七个动作一一对应 |
| 导入流水线 | ✅ 原始 File 上传 → preflight → confirm → execute → 轮询，路径与后端一致 |
| 红线 | ✅ workflowStore.ts / mockData.ts / 后端代码未动 |
| 交付诚实度 | ✅ 沙盒无法实机联调的原因如实说明并给出替代（冒烟脚本+验收清单），未谎报联调通过 |

## 需修复项

1. **【必须修】方案重算契约错位**：`Decision/Generate.tsx` 提交 `recalc(id, {supplier, quantity, transport, ratio})`，service 直接作为请求体发送；后端 `PATCH /proposals/{id}` 只读 `body.overrides`，收到的 overrides 恒为空 → 后端走默认 ×1.04，参数全部丢失，审计日志里 `overrides:{}`。页面本地也 ×1.04，巧合一致掩盖了 bug。修法：`decision.ts` 的 recalc 改发 `{ overrides }`，并把 totalCost 等实际值传入；页面改用后端返回值刷新而非本地硬算。
2. **【应修】markRead 未接后端**：交付材料称"后端确无 mark-read 端点"，不符事实——`business.py` 存在 `POST /notifications/{item_id}/read`。api 模式接上，mock 模式保留本地行为。
3. **【应修】预检失败被静默放行**：`data.ts` 第 305 行 preflight 失败被 catch 吞掉后继续 confirm/execute，绕过导入质量闸门。前端改为：preflight 失败 → 中止并展示报告，用户显式选择"仍要导入"才继续。同时列后端跟进项：`confirm` 端点不应从 `failed` 状态放行（当前不校验前置状态）。

## 后端跟进项（Phase 1 遗留 + 本轮新增，进 backlog）

`data:view` 权限码口径（数据管理角色 api 模式读表 403）；admin 是否补发只读码；notifications 已读态服务端持久化（目前刷新即丢）；imports confirm 状态机校验；refresh token 改整套 HttpOnly cookie 方案。

## 用户本机验收步骤（沙盒无法代跑，通过的最后条件）

1. `chainguard-web` 下 `DATA_MODE=api npm run build` 确认零 error。
2. 起后端（alembic upgrade + seed + uvicorn），执行 `ChainGuard/.workspace/acceptance/phase2_smoke.sh`，全绿。
3. `npm run dev` 用 scm_lead/boss 账号真实走通：风险→事件→生成方案→审批→任务；停掉后端刷新页面确认黄条出现且不白屏。
4. 按 `Phase2_验收清单.md` 逐条勾选。

## 结论

架构与实现质量高于 Phase 1，降级设计（显式黄条、opt-in 回退、自动恢复）符合工业级预期。修完第 1 项（契约错位为硬伤）、第 2/3 项，并在本机跑通上述四步后，Phase 2 视为通过，可进 Phase 3。

## 终审补记（2026-07-12，Phase 2 关闭）

需修复项 1–3 已修复；本机验收全部通过：build 零 error、真实链路（登录→风险→事件→异步方案→审批→5 任务→审计→导入→401/404 信封）全绿。首次验收发现的"停后端刷新无黄条"缺陷已修复（登录页渲染 DegradeBanner + 502/503/504 网关错误归入后端不可用），复测通过；冒烟脚本账号/权限/密码硬编码三处已修正。**Phase 2 正式通过。**后端跟进项一节转入 Phase 3 backlog。

### 终审代码复查记录（评审方独立直读磁盘核验）

- recalc 契约：✅ service 已包 `{ overrides }` 并附注释；Generate.tsx 改用后端返回值合并刷新，本地 ×1.04 硬算已删除。
- markRead：✅ api 模式接 `POST /notifications/{id}/read`，mock 保留本地。
- 预检闸门：✅ preflight 失败返回 `preflightBlocked + preflightReport`，仅用户显式 `force` 才越过。
- 登录页黄条：✅ Login.tsx 渲染 DegradeBanner；request.ts 将 502/503/504 归入后端不可用（dev 代理场景正确）。
- 冒烟脚本：✅ 账号 `scm_lead@chainguard.demo`、审计改用 auditor、密码强制读 `$SEED_DEMO_PASSWORD`。
- 抽查 incident/settings/user 服务接线与后端契约一致；向导/短信/注册保留 mock 均有 ADR 缺口标注。

### 新增 backlog（本次复查发现，低严重度，Phase 3 处理）

api 模式下顶部"切换角色（仅演示模式）"菜单仍会显示（后端 tenant-demo 的 demoDataFlag=true），点击后 `switchDemoRole` 写入 `demo-token-*` 造成 mock/api 混合态，下一次 API 调用 401 弹回登录。修法：api 模式隐藏该菜单，或改为对目标演示账号真实调用 /auth/login。
