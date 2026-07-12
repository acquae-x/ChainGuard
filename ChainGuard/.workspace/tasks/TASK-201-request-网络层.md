# TASK-201 前端统一网络层 request.ts

对应总指令 Phase 2 §2.1。规格来源：`codex_landing_spec/00`。级别 C（前端）。

## 背景与目标

前端 `services/*.ts` 目前全走内存 mock，无真实 HTTP 层。需新增基于 `@umijs/max` 自带 `request` 的统一封装，供后续 service api 模式调用。**禁止引入 axios。**

## 涉及文件

- 新增 `chainguard-web/src/utils/request.ts`
- 改 `chainguard-web/config/config.ts`（proxy 已存在，确认 `/api → http://127.0.0.1:8000` 不做 rewrite；后端已带 `/api/v1` 前缀）

## 实现要求

1. 导出统一 `apiRequest(url, options)`，`baseURL='/api/v1'`，超时 10s。
2. **错误信封解析**：非 2xx 时读后端 `{code, message, traceId}`，用 antd `message.error(message)` 提示；把 code/traceId 透传给调用方（抛结构化 error，含 `code`、`traceId`、`httpStatus`）。
3. **401**：清除 token cookie → `history.push('/user/login')`；不弹重复报错。
4. **网络错误 / 无响应**：提示"服务暂不可用"，并触发 §TASK-202 的全局降级标志（调用其暴露的 `markBackendDown()`）。
5. **重试仅限幂等 GET**：最多 2 次，指数退避（如 300ms、900ms）；POST/PATCH/DELETE 绝不自动重试。
6. **认证头**：每请求自动附 `Authorization: Bearer <token>`（token 从 cookie 读，复用 user.ts 的 cookie 名 `chainguard_demo_token` 或新常量，与 TASK-203 统一）。
7. 请求/响应 camelCase 已由后端保证，前端不做 case 转换；但 service 层负责把响应字段对齐 `API.*` typings。

## 验收标准（对应 acceptance/Phase2_验收清单.md §A）

- `npm run build` 零 error、`npm run dev` 可起。
- 单测或 mock server 验证：401 会跳登录；GET 失败重试 2 次后放弃；POST 失败不重试；错误信封 message 能弹出。
- 不含 axios、不含 redux；不使用 localStorage/sessionStorage 存业务数据。

## DoD

request.ts 合入且被 TASK-204 至少一个 service 实际调用跑通；全量前端 `npm run build` 绿；本文件验收项逐条自查通过并在提交物中列出。
