# Phase 5B 收尾批 · C02/C03「节点健康视图」实现范围（动工前规格，2026-07-20）

上游规格：
- `10_Phase5_总规格.md` §Phase 5B 收尾批（"C02/C03 节点健康视图"）+ §117 第 5 条
  （"Dashboard 角色分卡：工作台为全角色共用单页，节点健康卡按角色显示，用现有 access 权限码判断，**不新增权限码**"）
- `08_Streamlit功能全量对照.md` C02 行（"工作台 KPI 已有；节点健康图缺 → 5B，依赖 C2 数据"）与 C03 行（"一线节点明细 node_detail → 5B，一线角色工作台"）
- `09_功能融入设计_用户视角.md` §5（"工作台加供应链节点健康卡；一线角色工作台显示'我的节点'明细"）

前置：C2（实体表）、C1（context builder）、A03（风险解释/重算）、A04（影响范围）**均已验收完成**。
本批**不回退、不重写**上述任何模块，只在其之上加"节点健康"这一视角。

---

## 0. 动工前的现状勘察结论（它决定了 C02/C03 的形状）

| 勘察项 | 结论 | 证据 |
|---|---|---|
| Streamlit 原版节点明细 | `render_node_detail` 读的是 `scan_supply_chain(data_source).all_nodes`，其"节点"其实是**演示事件**（event_id/event_type），不是供应链实体 | `app.py:1585-1624` |
| 原版能否直接搬 | **不能**。它的数据源是演示场景包，不是租户 C2 实体；照搬即违反本批第 1 条 | 同上 |
| 现有工作台节点类 KPI | buyer「负责供应商异常数 1」、warehouse「本仓预警 SKU 4」、sales「受影响订单 3」、planner「物料缺口 SKU 1」**全是写死的演示字面量** | `chainguard-web/src/pages/Dashboard/dashboardConfig.ts:13-17` |
| KPI 真实化机制 | 已有 `KPI_SOURCE` 映射把可计数 KPI 覆盖为 `/dashboard/kpis` 真值，但**上述四个节点类 key 不在映射内**，因此永远显示假数字 | `Dashboard/index.tsx:46-50` |
| 已有的按物料健康计算 | `calculate_inventory_risk` + `measure_material` 已能对**单个物料**产出 红色预警/黄色预警/正常 三档，阈值经 `TenantContextBuilder` 与 C1 决策链路同源 | `risk_recompute.py:72-116`、`risk_explanation.py:197-200` |
| 供应商/仓库/订单是否有评分模型 | **没有**。`config/thresholds.yaml` 只有 `inventory_warning` 一组阈值，无供应商可靠性阈值、无交期阈值 | `config/thresholds.yaml` |
| 仓库主数据 | **不存在独立仓库表**，仓库只是 `inventory.warehouse_id / warehouse_name` 两列（A04 已登记同一限制） | `models.py:459-460` |
| 一线角色的职责权限码 | 已齐备且互不重叠：`data:inventory:manage`(warehouse)、`data:supplier:manage`(buyer)、`data:material:manage`(planner)、`data:order:manage`+`data:customer:manage`(sales) | `seed.py:36-40` |
| 字段脱敏路径 | `decision_detail.mask_for_requester` 已覆盖财务词根与客户等级键名（A04 补的 `is_tier_key`） | `decision_detail.py:72-108` |

**推论一**：Streamlit 的 `render_node_detail` 不是可迁移资产，只是**交互形态**的参考（一张按角色脱敏的节点状态明细表）。
数据来源必须整个换成 C2 实体，本批不引用 `scan_supply_chain`、不进 `data_source`。

**推论二**：只有**物料节点**的健康是"算出来的"，且必须复用既有引擎。
供应商 / 仓库 / 订单**没有评分模型**，本批**也不新写**——给它们编一套评分就是新算法，越界（同 A04 §2 的"不计算影响程度"口径）。
它们的健康只能由两种东西得出：**(a) 实体行上的事实判据**（状态字段命中中断词表、承诺交期已过、可用量低于安全库存），
**(b) 从物料节点传播**（"我供的料/我存的料/我要的料出问题了"）。二者都必须在响应里逐条标明来源，不得含糊成一个分数。

**推论三**：`dashboardConfig.ts` 那四个写死的节点类 KPI 是**伪造的节点结论**，与 A04 里的
「客户等级 A」「预计延误 2 天」性质相同，必须一并接真数据或删除，否则界面仍在展示编造数字。

---

## 1. 实现范围

### 1.1 节点定义（四类，全部由 C2 实体承载）

| nodeType | 承载表 | 业务键 | 名称来源 | 资料页跳转 |
|---|---|---|---|---|
| `material` 物料节点 | `materials` | `material_id` | `material_name` | `/data/material?id=` |
| `warehouse` 仓库节点 | `inventory` 按 `warehouse_id` 聚合 | `warehouse_id` | `warehouse_name` | **无**（无主数据，`link=null`，不给假链接） |
| `supplier` 供应商节点 | `suppliers` | `supplier_id` | `supplier_name` | `/data/supplier?id=` |
| `order` 订单节点 | `sales_orders`（仅未关闭） | `sales_order_id` | `sales_order_id` + 客户名 | `/data/order?id=` |

节点类型固定顺序 `material / warehouse / supplier / order`；**没有节点的类型仍然出现**且 `total=0` 带 `emptyReason`——
"暂无数据"必须显式，不靠分组消失来暗示（沿用 A04 §1.1.5 口径）。

### 1.2 健康状态（四档）

`critical` 异常 / `warning` 预警 / `healthy` 健康 / `unknown` 数据不足。
**`unknown` 不是第四种健康程度，是"这个节点算不了"**，在概览里单独计数，绝不并入 healthy。

#### 1.2.1 物料节点（唯一由引擎算出的一类）

零新公式：`TenantContextBuilder.build_material_snapshot` → `calculate_inventory_risk` → `measure_material`，
与 A03 解释、C1 决策链路**同一条取数与阈值路径**。

| measurement.warningLevel | health |
|---|---|
| `红色预警` | `critical` |
| `黄色预警` | `warning` |
| `正常` | `healthy` |
| 抛 `ContextBuildError`（CG-2512 日消耗缺失 / CG-2513 无库存记录） | `unknown`，reason 带原始 code 与 message |

`reasons[]` 是 measurement 里**已有数字与已有阈值的直接对照**，不引入任何新阈值：

| reason code | 触发条件 | observed | threshold |
|---|---|---|---|
| `support_hours_below_red` | `supportHours < redSupportHours` | 库存支撑小时数 | `thresholds.redSupportHours` |
| `support_hours_below_yellow` | `supportHours < yellowSupportHours`（且未命中红线） | 同上 | `thresholds.yellowSupportHours` |
| `risk_index_above_trigger` | `riskIndex >= triggerThreshold` | 库存风险指数 | `triggerThreshold` |
| `safety_stock_gap` | `safetyStockGap > 0` | 安全库存缺口 | 0（缺口存在即列出，非阈值判定） |
| `transit_delay` | `transitDelayHours > 0` | 在途延误小时 | 同上 |
| `critical_order_uncovered` | `criticalOrderCoverageRate < 1` | 关键订单覆盖率 | 同上 |

每条 reason 带 `thresholdSource`（`expert_default` / `tenant_config`），取自 `snapshot.configuration["source"]`——
用户看得见"这条判据用的是专家默认值还是本租户校准值"。

#### 1.2.2 仓库节点（事实判据 + 传播）

| health | 判据 |
|---|---|
| `critical` | 存在库存行 `available_qty < safety_stock_qty`（`inventory_below_safety_stock`，与引擎 `safety_stock_gap` 同判据）**或** 该仓存放的物料中存在 `critical` 物料节点（`hosts_critical_material`） |
| `warning` | 该仓存放的物料中存在 `warning` 物料节点（`hosts_warning_material`） |
| `unknown` | 该仓全部库存行的 `available_qty` 与 `safety_stock_qty` 均缺失，且其全部物料节点均为 `unknown`（`insufficient_inventory_fields`） |
| `healthy` | 其余 |

#### 1.2.3 供应商节点（事实判据 + 传播）

中断词表（固定常量，非生成文本）：`{停产, 停供, 中断, 暂停, 受事件影响, 已终止, suspended, stopped, disrupted, terminated}`
——口径与 `context_builder._CLOSED_ORDER_STATUSES` 同类，是**状态词表**不是评分。

| health | 判据 |
|---|---|
| `critical` | `status` 命中中断词表（`supplier_status_disrupted`，reason 里回显 `status` 原值）**或** 该供应商全部 `supplier_materials` 行 `qualified=False`（`no_qualified_material`） |
| `warning` | 供货物料中存在 `critical` 物料节点（`supplies_critical_material`） |
| `unknown` | `status` 为空**且**无任何 `supplier_materials` 记录（`insufficient_supplier_fields`） |
| `healthy` | 其余 |

**不使用 `reliability_score` 判定健康**——配置里没有它的阈值，凭空定一个就是新算法。
该字段仅作为 `metrics` 原值展示，并在已知限制里说明。

#### 1.2.4 订单节点（事实判据 + 传播）

仅统计**未关闭**订单，复用 `context_builder._CLOSED_ORDER_STATUSES`，不新定义状态集。

| health | 判据 |
|---|---|
| `critical` | `promised_delivery_at < now`（`delivery_overdue`，纯事实，**无时间阈值**）**或** 所需物料中存在 `critical` 物料节点（`requires_critical_material`） |
| `warning` | 所需物料中存在 `warning` 物料节点（`requires_warning_material`） |
| `unknown` | 无任何订单行（不知道要什么料）**且** `promised_delivery_at` 为空（`insufficient_order_fields`） |
| `healthy` | 其余 |

**刻意不做"临近交期"预警**：那需要一个"提前多少小时算临近"的阈值，配置里没有，本批不发明。

#### 1.2.5 传播的诚实声明

仓库/供应商/订单的健康**部分来自物料节点传播**。每条传播型 reason 带
`derivedFrom: {nodeType:"material", id:"...", health:"critical"}`，可点击跳到那个物料节点。
响应恒带限制 `CG-C024` 明示：**只有物料节点是引擎计算的，其余三类是事实判据 + 物料传播，不是独立评分模型**。

### 1.3 端点（不新增权限码）

```
GET /api/v1/dashboard/node-health    权限 dashboard:view   管理者概览 + 可筛选节点列表
    query: nodeType=material|warehouse|supplier|order, health=..., keyword=, current=, pageSize=
GET /api/v1/dashboard/my-nodes       权限 dashboard:view   一线「我的节点」明细
```

`dashboard:view` 属 `BASE`，全角色具备；**角色差异不靠新权限码，而靠数据范围**——
`/my-nodes` 的节点类型范围由既有权限码派生（`can_view_data` 同族口径，不新写权限逻辑）：

| 已有权限码 | 纳入的 nodeType |
|---|---|
| `*` / `data:view` / `data:manage` / `settings:manage` | 全部四类（全域数据范围） |
| `data:inventory:manage` 或 `risk:manage:warehouse` | `warehouse` |
| `data:supplier:manage` | `supplier` |
| `data:material:manage` 或 `risk:manage:material` | `material` |
| `data:order:manage` / `data:customer:manage` / `risk:manage:order` | `order` |

一类都不匹配（如 `boss`、`finance`）→ `available=false, code=CG-C031`，明示"当前角色没有直接负责的节点类型，
请在工作台节点健康概览查看全局"，**不返回任何节点**。

### 1.4 数据不足时的降级（禁止伪造）

| code | 场景 | 语义 |
|---|---|---|
| `CG-C021` | 租户四类实体表全空 | `available=false`，概览不返回任何数字，明示"尚未导入业务数据" |
| `CG-C022` | 部分物料因日消耗/库存缺失无法计算 | `available=true`，计入 `unknown` 并披露真实条数与各自原因 |
| `CG-C023` | 仓库为库存行聚合，无独立主数据 | 恒常提示（沿用 A04 `CG-A042` 同一事实） |
| `CG-C024` | 非物料节点的健康含传播成分，非独立评分模型 | 恒常提示 |
| `CG-C025` | 单类节点超 500 上限被截断 | `available=true`，明示已截断及真实总数 |
| `CG-C026` | 已关闭订单被排除 | 明示排除条数 |
| `CG-C027` | 部分库存行没有仓库标识，归不进任何仓库节点 | 明示条数，不静默丢弃（实现时补登记） |
| `CG-C031` | `/my-nodes`：当前角色无对口节点类型 | `available=false` |
| `CG-C032` | `/my-nodes`：角色范围内零节点 | `available=true`，各类型 `total=0` 且带 `emptyReason` |

`available=false` 一律返回 **200**（与 A03/A04 一致），让前端渲染限制说明而非报错弹窗。

### 1.5 租户隔离与脱敏（严格复用，零新机制）

- 每一条 `select()` 都带 `tenant_id == self.tenant_id`；四类节点的取数入口没有任何不带租户过滤的分支。
- 出口统一过 `decision_detail.mask_for_requester(payload, ctx.permissions)`——与 A03/A04/decision-detail 同一条路径。
  涉及 `orderAmount` / `grossProfit` / `penaltyCost` / `supplierPrice` / `unitPrice` / `customerLevel`。
- 不新增权限码；不新增路由（挂在既有 `/dashboard/*` 命名空间下）。

### 1.6 前端（C 级改动，规格来源 `codex_frontend_spec/`）

| 落点 | 改动 |
|---|---|
| **新** `NodeHealthPanel` 组件 | 概览三色计数（健康/预警/异常）+ `unknown` 单列 + 类型/状态筛选器 + 节点表（名称/类型/状态/异常原因/数据更新时间/跳转）；空类型显式 `emptyReason`；`available=false` 只渲染限制说明 |
| `src/pages/Dashboard/index.tsx` | 新增 `nodeHealth`（管理者概览）与 `myNodes`（一线明细）两个 section |
| `src/pages/Dashboard/dashboardConfig.ts` | buyer/warehouse/sales/planner 加 `myNodes` section；boss/scm_lead/admin/auditor 加 `nodeHealth`；**删除四个写死的节点类 KPI 字面量**（`supplier`/`sku`/`order`/`gap`），改由面板给真实计数 |
| `src/services/dashboard.ts` | 新增 `getNodeHealth(params)` / `getMyNodes()`，双模式；mock 模式如实返回不可用，不编造节点 |
| 窄屏 | 面板在 ≥375px 下可读（沿用 5A 预期管理条款） |

**不新增路由**，跳转目标是既有 `/data/*` 资料页与既有风险/事件页。

---

## 2. 数据来源与真实性边界

| 字段 | 来自 | 是否可能是估算 |
|---|---|---|
| 节点 id / 名称 | 对应 C2 实体表列 | 否，行级真实 |
| 物料节点健康 | `calculate_inventory_risk` 引擎结果 | 否（但其输入可能含 C1 已声明的估算项，见 `dataQuality`） |
| 仓库/供应商/订单健康 | 实体行事实判据 + 物料节点传播 | 否，但**不是独立评分模型**（`CG-C024`） |
| 异常原因的观测值与阈值 | measurement 数值 + `thresholds.yaml`/租户获批配置 | 否，且标注 `thresholdSource` |
| 数据更新时间 | 实体行 `updated_at`（仓库取其库存行最大值） | 否，行级真实 |
| 数据来源批次 | `impact_scope.latest_batches()`（A03/A04 同一函数） | **是资源类型级，不是行级血缘** |

**本批不计算任何"节点评分/健康分数"**。四档状态是分类结论，不是数字；
硬要给一个 0-100 的节点健康分，就必须新写一套加权公式——那是新算法，越界。这条写进已知限制。

---

## 3. 验收清单

### 3.1 后端 pytest（新增 `tests/test_phase5b_c02_c03_node_health.py`）

| # | 用例 | 断言要点 |
|---|---|---|
| N1 | 物料节点健康取自引擎 | 红色预警物料 → `health=critical`，且 `reasons` 含 `support_hours_below_red`，observed/threshold 与 `measure_material` 输出逐值一致 |
| N2 | 三档映射 | 黄色→warning、正常→healthy |
| N3 | 物料算不了 → unknown | 日消耗缺失物料 → `health=unknown`，reason 带 `CG-2512`；**不并入 healthy** |
| N4 | 仓库聚合 | 两仓库存行 → 2 个仓库节点；同仓两行 → 1 个；`link` 为 `null`；`limitations` 含 `CG-C023` |
| N5 | 仓库安全库存判据 | `available_qty < safety_stock_qty` → critical，reason `inventory_below_safety_stock` |
| N6 | 仓库传播 | 存放 critical 物料 → critical，reason 带 `derivedFrom` 指向该物料 |
| N7 | 供应商中断词表 | `status="停产"` → critical，reason 回显原值；`status="可用"` 且无异常物料 → healthy |
| N8 | 供应商传播 | 供货 critical 物料 → warning，reason `supplies_critical_material` |
| N9 | 供应商 unknown | 无 status 无供货记录 → unknown |
| N10 | 订单逾期 | `promised_delivery_at` 已过 → critical，reason `delivery_overdue` |
| N11 | 订单传播 | 订单行含 critical 物料 → critical，reason `requires_critical_material` |
| N12 | 已关闭订单排除 | 已交付订单不出现，`limitations` 含 `CG-C026` 且注明排除条数 |
| N13 | 概览计数 | `summary` 四档计数 = `nodes` 实际分布；`byType` 逐类型计数自洽 |
| N14 | 空类型显式 | 无供应商的租户 → supplier 类型仍出现，`total=0` 且带 `emptyReason` |
| N15 | 空租户降级 | 四类实体全空 → `available=false, code=CG-C021`，响应体**不含任何数字统计** |
| N16 | 筛选 | `nodeType=supplier` 只回供应商；`health=critical` 只回异常；`keyword` 命中名称/id |
| N17 | 跳转 | 每个节点 `link` 指向真实资料页且带正确 id；仓库为 `null` |
| N18 | 传播声明 | 任一非物料节点存在时 `limitations` 恒含 `CG-C024` |
| N19 | **跨租户隔离 · 概览** | 租户 B 的 `/node-health` 不含租户 A 任何实体名（整份 JSON 子串断言） |
| N20 | **跨租户隔离 · 同名同 id** | A、B 存在同 id 物料 → 各自只看到自己的行（按字段值区分） |
| N21 | 脱敏 | 无 `field:cost:view` → `orderAmount`/`penaltyCost`/`supplierPrice` 为 `***`；无 `field:customerLevel:view` → 客户等级脱敏；scm_lead 见真值 |
| N22 | **角色范围 · warehouse** | warehouse 账号 `/my-nodes` 只回 `warehouse` 类型 |
| N23 | **角色范围 · buyer** | buyer 只回 `supplier` |
| N24 | **角色范围 · planner / sales** | planner 只回 `material`；sales 只回 `order` |
| N25 | **角色无对口类型** | boss / finance → `available=false, code=CG-C031`，零节点 |
| N26 | 全域角色 | scm_lead(`data:manage`) / auditor(`data:view`) → 四类齐全 |
| N27 | 角色范围内零节点 | warehouse 账号 + 无库存租户 → `CG-C032`，warehouse 类型 `total=0` |
| N28 | 未登录/无效令牌 | 401，不泄露任何节点 |
| N29 | 截断 | 单类 >500 → `CG-C025` 且注明真实总数 |
| N30 | 数据更新时间真实 | 节点 `updatedAt` == 实体行 `updated_at`；仓库取其库存行最大值 |
| N31 | **零回归** | A03/A04/C1/C2 既有测试文件全绿 |

### 3.2 前端单测（vitest）

| # | 用例 |
|---|---|
| F1 | `NodeHealthPanel` 渲染三色计数与 `unknown` 单列，数字取自响应而非本地推算 |
| F2 | 四类节点按固定顺序渲染，空类型渲染 `emptyReason` 且不渲染空表格 |
| F3 | `available=false` 时只渲染限制说明，**不渲染任何计数与节点行** |
| F4 | 类型/状态筛选器改变时以新参数重新请求 |
| F5 | 节点行跳转参数正确；仓库行不渲染链接 |
| F6 | 异常原因逐条渲染观测值与阈值，传播型显示来源物料 |
| F7 | `limitations` 逐条渲染，含 `CG-C023`/`CG-C024` |
| F8 | `dashboardConfig` 中**不再出现**四个写死的节点类 KPI 字面量 |

### 3.3 API 模式 Chromium E2E

新增 `playwright.node-health-api.config.ts` + `e2e/node-health-api-acceptance.spec.ts`
+ `scripts/seed_phase5b_c02_c03_e2e.py`（两个隔离租户 + 一线四角色账号 + 一个空数据租户），
与 A03/A04 同构、独立端口与独立 DB。

| # | 场景 | 通过标准 |
|---|---|---|
| E1 | 管理者概览 | scm_lead 登录 → 工作台「供应链节点健康」卡：健康/预警/异常/数据不足四个计数可见且与后端一致 |
| E2 | 筛选 | 选「异常」+「供应商」→ 列表只剩异常供应商节点 |
| E3 | 异常原因可读 | 展开物料节点 → 显示「库存支撑 15.0 小时 < 红线 24 小时」及阈值来源 |
| E4 | 跳转 | 点物料节点 → 落在 `/data/material` 且带正确 id 参数 |
| E5 | 一线「我的节点」 | warehouse 登录 → 只见仓库节点；buyer 登录 → 只见供应商节点（同一页面截图对比） |
| E6 | 角色无对口类型 | boss 登录 → 显示 `CG-C031` 说明，页面无节点行 |
| E7 | 空数据降级 | 空租户 → 显示 `CG-C021`，截图证明页面无编造计数 |
| E8 | **跨租户隔离** | 租户 B 页面文本不含租户 A 任何实体名 |
| E9 | 脱敏 | buyer 登录 → 节点明细中金额与客户等级为 `***` |
| E10 | 窄屏 | 375px 下面板可读、不横向溢出 |

### 3.4 交付材料要求

实际执行的 pytest 全量原始输出、`DATA_MODE=api npm run build` 原始输出、
playwright 原始输出（新配置 + A03/A04 回归 + 既有 api-acceptance 回归）、E1–E10 逐项截图、
变更文件清单、已知限制章节。

---

## 4. 红线与影响面自查

| 红线 | 本批是否触碰 | 说明 |
|---|---|---|
| 演示输出必须稳定（70.25） | **否** | 不改 `config/*.yaml`、`data/*.json`、风险/评分公式，**不调用 `run_demo`**，不进 orchestrator，不碰 `scan_supply_chain` |
| LLM 绝不改数 | **否** | 全程不调用 LLM；状态标签与原因标签是固定中文常量 |
| 测试全绿才能动主干 | 遵守 | 见 §3.4 |

| 已验收模块 | 影响 | 缓解 |
|---|---|---|
| C1 `context_builder` | **只读复用** `build_material_snapshot` / `_CLOSED_ORDER_STATUSES`，不改代码 | N31 回归 |
| A03 `risk_recompute` / `risk_explanation` | **只读复用** `measure_material`，不改代码 | N31 回归 |
| A04 `impact_scope` | 只调用既有 `latest_batches()`，不改其行为 | N31 回归 |
| C2 实体表 | **只读**，不加列、不迁移 | N31 回归 |
| 决策链路 / orchestrator | 不进入 | — |
| 权限体系 | **无新增权限码**，复用 `dashboard:view` + `data:*:manage` / `risk:manage:*` / `field:*:view` | N22–N26 锁定 |
| 数据库迁移 | **零迁移** | 纯查询模块 |
| Streamlit `app.py` | **不改**，`render_node_detail` 原样保留 | `test_ui_routing.py` 仍绿 |

---

## 5. 实施顺序

1. `node_health.py` 引擎：物料节点（复用引擎）+ N1–N3
2. 仓库/供应商/订单节点（事实判据 + 传播）+ N4–N12
3. 概览聚合、筛选、降级 + N13–N18、N29–N30
4. 隔离与脱敏 + N19–N21
5. 两个端点 + 角色范围派生 + N22–N28
6. 前端 `NodeHealthPanel` + F1–F7
7. Dashboard 挂载 + 清除硬编码 KPI 字面量 + F8
8. E2E seed + 配置 + E1–E10
9. 全量回归 + 界面验收截图 + 交付材料

---

## 6. 已知限制（预登记进交付材料）

1. **只有物料节点是引擎计算的**。供应商/仓库/订单的健康 = 实体行事实判据 + 物料节点传播，
   **不是独立评分模型**；系统没有它们的阈值配置，本批不发明（恒落 `CG-C024`）。
2. **不给节点健康分数**。四档是分类结论不是数字；给 0-100 分需新写加权公式，越界。
3. **不使用 `reliability_score` 判定供应商健康**——配置无其阈值，仅作原值展示。
4. **不做"临近交期"预警**——需要一个"提前多少小时"阈值，配置里没有，本批不发明；只判"已逾期"这一事实。
5. **仓库无独立主数据**，为 `inventory.warehouse_id/name` 聚合结果，恒落 `CG-C023`，`link` 为 `null` 而非假链接。
6. **供应商中断判定依赖状态词表**，词表外的自定义状态词会被判为 `healthy`；词表是固定常量，可核对。
7. **批次血缘为资源类型级，非行级**（沿用 A03 §2 / A04 限制）。
8. **单类 500 条截断**，超出时明示真实总数，未做分页游标。
9. **物流/路线不是节点**：`/data/logistics` 无对应 C2 实体表。
10. **mock 模式没有节点健康**。服务层如实返回不可用，不在演示态编造节点。
11. **不改 Streamlit**：`app.py` 的 `render_node_detail` 原样保留，两者数据源不同、互不影响。
