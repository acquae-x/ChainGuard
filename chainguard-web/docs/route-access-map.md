# ChainGuard 路由访问矩阵

> 由 `scripts/generate-route-access-map.cjs` 生成。菜单级裁决遵循 03 文档，按钮、字段和只读限制由 `src/access.ts` 与 `SensitiveField` 二次控制。

| 页面 | 路由 | 访问控制 | admin | boss | scm_lead | buyer | warehouse | sales | finance | planner | auditor |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 登录 | `/user/login` | 公开 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 注册 | `/user/register` | 公开 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 加入企业 | `/user/join` | 公开 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 找回密码 | `/user/reset` | 公开 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 初始化向导 | `/onboarding` | 登录用户 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 工作台 | `/dashboard` | 登录用户 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 风险总览 | `/risk/overview` | canRisk | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 风险列表 | `/risk/list` | canRisk | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 监控规则 | `/risk/rules` | canRisk | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 事件列表 | `/incident/list` | canIncident | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 我发起的事件 | `/incident/mine` | canIncident | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 事件详情 | `/incident/:id` | canIncident | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 方案生成/对比 | `/decision/generate/:incidentId` | canDecision | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| 方案列表 | `/decision/list` | canDecision | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| 审批中心 | `/decision/approval` | canDecision；按钮另校验 canApproval | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| 我的任务 | `/task/mine` | canTask | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 全部任务 | `/task/all` | canTask | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 超时看板 | `/task/overdue` | canTask | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 物料 | `/data/material` | canDataMaterial | ✅ | — | ✅ | — | — | — | — | ✅ | ✅ |
| 供应商 | `/data/supplier` | canDataSupplier | ✅ | — | ✅ | ✅ | — | — | — | — | ✅ |
| 客户 | `/data/customer` | canDataCustomer | ✅ | — | ✅ | — | — | ✅ | — | — | ✅ |
| 订单 | `/data/order` | canDataOrder | ✅ | — | ✅ | — | — | ✅ | — | — | ✅ |
| 库存 | `/data/inventory` | canDataInventory | ✅ | — | ✅ | — | ✅ | — | — | — | ✅ |
| 物流 | `/data/logistics` | canDataLogistics | ✅ | — | ✅ | — | — | — | — | — | — |
| 数据导入 | `/data/import` | canData；写操作 canImport | ✅ | — | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| 案例库 | `/case/list` | canCase | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| 经验卡片 | `/case/experience` | canCase | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| 经营看板 | `/report/executive` | canReport | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| 运营看板 | `/report/operation` | canReport | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| 应急效果 | `/report/response` | canReport | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| 企业信息 | `/settings/tenant` | canSettingsAdmin | ✅ | — | — | — | — | — | — | — | — |
| 用户管理 | `/settings/users` | canSettingsAdmin | ✅ | — | — | — | — | — | — | — | — |
| 角色权限 | `/settings/roles` | canSettingsAdmin | ✅ | — | — | — | — | — | — | — | — |
| 数据权限 | `/settings/scopes` | canSettingsAdmin | ✅ | — | — | — | — | — | — | — | — |
| 审批流 | `/settings/approval` | canApprovalConfig | ✅ | — | ✅ | — | — | — | — | — | — |
| 风险阈值 | `/settings/thresholds` | canApprovalConfig | ✅ | — | ✅ | — | — | — | — | — | — |
| 自定义字段 | `/settings/fields` | canSettingsAdmin | ✅ | — | — | — | — | — | — | — | — |
| 审计日志 | `/settings/audit` | canAudit | ✅ | ✅ | — | — | — | — | — | — | ✅ |
| 向导重入 | `/settings/onboarding` | canSettingsAdmin | ✅ | — | — | — | — | — | — | — | — |
| 系统集成（P3 占位） | `/settings/integration` | canSettingsAdmin | ✅ | — | — | — | — | — | — | — | — |
| 无权限 | `/403` | 公开结果页 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 服务异常 | `/500` | 公开结果页 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 页面不存在 | `*` | 公开结果页 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

## 补充规则

- `auditor` 对所有可达业务页只读，操作按钮由 `readonly` / `canTaskWrite` / `canModifyDecision` 隐藏。
- `admin` 可配置租户、用户、角色和数据，但 `canApproval=false`，不出现审批按钮。
- `buyer` 无 `field:cost:view`、`field:supplierPrice:view`，成本与供应商价格显示为 `***`。
- 数据管理按二级对象权限裁剪；表中的 `✅` 表示该角色至少可访问该路由，导入写操作仍需 `canImport`。
- 未授权路由由 Umi access 拦截到 403，隐藏路由（事件详情、方案生成）仍执行相同访问控制。
