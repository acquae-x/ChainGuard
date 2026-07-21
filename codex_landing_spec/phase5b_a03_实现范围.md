# Phase 5B 收尾批 · A03「实时风险解释」实现范围（动工前规格，2026-07-19）

上游规格：`10_Phase5_总规格.md` §Phase 5B 收尾批 + §结合审计表最后一行
（"A03/A04/C02 风险解释/影响范围/节点卡 → Risk 列表、Incident/Detail 四表、Dashboard 卡片区扩展"）。
本文只界定 A03，A04（影响范围）与 C02/C03（节点健康）不在本批。

---

## 0. 动工前的现状勘察结论（必须先读，它改变了 A03 的形状）

| 勘察项 | 结论 | 证据 |
|---|---|---|
| Web 侧 `risks` 表的写入来源 | **只有 seed 硬编码两条**（risk-1 苏州芯片封测厂 / risk-2 MCU-A9），全仓无任何实体驱动的风险生成 | `grep -rn "Risk(" src/webapi/` 仅命中 `models.py:96`、`seed.py:53-54` |
| 是否存在风险扫描/重算作业 | **不存在** | `grep -rn "risk_scan\|scan_risks\|generate_risk\|refresh_risks\|rescan"` 全仓零命中 |
| C1 与 risk 的关系 | C1 是**读**方：`TenantContextBuilder._resolve_material` / `_event_delay` / `_resolve_affected_supplier` 从 `risk.details` 反查实体，不产 risk | `src/webapi/context_builder.py:324-380` |
| 风险指数计算能力 | 引擎侧已完备：`calculate_inventory_risk` 产出四维分项 + 指数 + 预警等级 + explanation | `src/inventory_monitor.py:18-119` |
| 风险详情页 | **不存在**。`/risk/list` 只有列表 + 两个抽屉（高级筛选、创建事件），无详情路由 | `config/routes.ts:17-25`，`src/pages/Risk/List.tsx` |
| 后端风险详情端点 | 存在但只是 `serialize(Risk)` 裸返，无解释、无证据 | `src/webapi/routers/business.py:134-137` |

**推论**：11 万条企业数据灌入后，`/risk/list` 看到的仍是那两条 demo 风险。
若只做"解释层"，A03 会变成"给硬编码风险编一段真话"——违背本批目标本身。
因此 A03 的范围**必须内含最小风险重算**（已与产品方确认，选项 A）。

---

## 1. 实现范围

### 1.1 后端：风险重算（新增，但零新算法）

新模块 `src/webapi/risk_recompute.py`。

- 入口 `recompute_inventory_risks(db, tenant_id, *, now=None) -> RecomputeResult`。
- 逐物料（`materials` 表，租户内）执行：
  1. 复用 `TenantContextBuilder` 抽出的**物料级**取数路径拿到 inventory / orders / suppliers；
  2. 调用**现有** `src.inventory_monitor.calculate_inventory_risk(inventory, risk_weights, thresholds)`；
  3. `should_trigger_response` 为真 → upsert 一条 `Risk`（type=`库存`，object_type=`物料`），
     `details` 写入四维分项、当前值、阈值、来源实体键与 `updated_at`。
- **红线自查**：不新写评分公式、不改权重/阈值 YAML、不动 `run_demo`、不动 orchestrator。
  唯一新增的是"把已有引擎函数接到租户实体上"这一层胶水。
- 阈值/权重解析**复用 C1 同一条路径**（`TenantContextBuilder._decision_configuration`），
  保证"解释里说的阈值"与"方案生成时用的阈值"是同一个值——这是第 2 条要求（与决策链路衔接）的技术兑现方式。

**C1 需要的最小重构**（这是本批唯一触碰已验收模块的地方，必须做小）：
`TenantContextBuilder` 现有取数逻辑是 incident-keyed（`build(incident_id)`）。
抽出 `_inventory` / `_orders` / `_suppliers` / `_decision_configuration` 为 material-keyed 的
`build_material_snapshot(material_id) -> MaterialSnapshot`，`build(incident_id)` 改为调用它。
**行为不变**，用 `tests/test_phase5b_c1_tenant_decision.py` 全绿锁定"C1 无回归"。

触发方式：`POST /api/v1/risks/recompute`，同步、单次、权限 `risk:manage`。
不引入调度器作业、不引入后台 job（避免碰 A5 调度器与 5A-2 通知链路）。

#### 1.1.1 风险身份与幂等（重算能反复跑的前提）

- **识别范围**：重算**只管自己产生的风险**。所有重算风险带 `details.origin = "recompute"`，
  无此标记的风险（seed 的 risk-1/risk-2、用户手工建的、未来其他来源的）重算**一律不碰**。
- **业务主键**：`Risk.id = "risk-auto-" + sha1(f"{tenant_id}|inventory|{material_id}")[:16]`。
  主键直查，跨 SQLite/PostgreSQL 一致，不需要 JSON 查询、不需要加列、不需要迁移。
- **`Risk.code` 只在首次创建时生成**（`RISK-{YYYYMMDD}-A{seq}`），后续重算永不改写——
  编号是人要引用的东西，不能每次扫描都换。
- **`found_at` 同理**：只在"首次发现"和"消除后复发"时写入，普通数值更新不刷新发现时间。
- **幂等**：同一份实体数据连续两次 recompute，`risks` 表除 `updated_at` 外**零差异**（B18 锁定）。

#### 1.1.2 状态机（补 §1.1 原缺口）

现有五态：`new` / `watching` / `incident_created` / `resolved` / `ignored`。

**总原则：重算负责改"数值与解释快照"，人工判断过的状态不被机器覆盖。**
`ignored` 与 `incident_created` 是人做出的决定，重扫一遍不能把它抹掉。

| 当前状态 | 本次仍触发阈值 | 本次不再触发 |
|---|---|---|
| （不存在） | 新建，状态 `new` | **不创建**——不产生"无风险"记录 |
| `new` | 更新数值与快照，状态保持 `new` | → `resolved`，写 `details.resolvedAt` 与最后快照 |
| `watching` | 更新数值与快照，**保持 `watching`**（不退回 `new`） | → `resolved`，同上 |
| `incident_created` | 更新数值与快照，**保持状态、保留 `incident_id`** | **不置 `resolved`**，仅更新数值并置 `details.noLongerTriggering = true`；事件生命周期由事件闭环决定，风险扫描无权终结它 |
| `ignored` | **不复活**：静默更新数值快照，**不改状态、不发通知** | 保持 `ignored` |
| `resolved` | **复发**：→ `new`，`found_at` 刷新，`details.recurrenceCount += 1`，记录上次 `resolvedAt` | 保持 `resolved`，**不更新数值**（已消除的风险不再刷新，避免快照漂移） |

**这补上了原文档的硬伤**：`resolved` 状态此前没有任何产生路径，A03 验收用例 B9 / E5
（`CG-A031` 风险已恢复）在原设计下**根本跑不起来**。现在 `resolved` 由"上一轮触发、本轮不再触发"
这一条迁移产生，且落 `details.lastExplanationSnapshot`——那份快照正是 `CG-A031` 场景下
前端展示的内容，也是"不伪造解释"的兑现：风险已消除时展示的是**消除当时算出来的真实数值**，
并明确标注为快照与其时间戳，而不是拿当前数据现编一个已经不成立的解释。

**通知**：本批重算**不触发 D3 通知**（`notify_event("risk_high")` 不接）。
理由：一次全量重扫可能新建大量高风险，直接接通知会造成通知风暴，且会碰已验收的 5A-2 链路。
列入 §7 待确认与已知限制。

#### 1.1.3 seed 去硬编码

目标：`seed.py:53-54` 那两条写死 `score=92` / `score=73` 的 Risk 不再以硬编码形态存在，
演示租户的风险与真人租户走同一条产生路径。

**做法**：seed 改为先落实体行（`materials` MCU-A9 / `inventory` 上海一仓 / `suppliers` 苏州芯片封测厂
/ `customers` + `sales_orders` + `sales_order_lines`），再调用 `recompute_inventory_risks()` 产出风险。
`inc-supplier-shutdown` 的 `source_risk_ids` 改为引用确定性 id
（`risk-auto-{sha1(tenant|inventory|MCU-A9)[:16]}`，seed 可直接算出，不需要查库）。

**但这里有个必须讲清楚的不对称——两条风险只有一条能被"算"出来：**

| seed 风险 | 能否由现有引擎推导 | 原因 |
|---|---|---|
| `risk-2`（库存 / MCU-A9 / 安全库存低于 20%） | **能** | 正是 `calculate_inventory_risk` 的定义域，分数由实体数据算出，不再写死 |
| `risk-1`（供应 / 苏州芯片封测厂 / 核心供应商停产） | **不能** | 引擎里没有供应商风险评分。"供应商停产"是**外部输入**，不是内部数据能算出来的结论——没有任何库存/订单数字能推出"这家厂停产了"，只能由人或 ERP/新闻告知 |

强行让 `risk-1` 也变成"算出来的"，就必须新写一套供应商风险评分公式——那是新算法，
碰"不重写现有评分算法"的约束，也超出 A03 的范围。

**所以 `risk-1` 的正确处置是标注来源，而不是伪造计算**：
它保留为 seed 落库，但 `details.origin = "external_event"`，
并补齐可追溯字段（告知渠道、录入人、录入时间、关联供应商实体 id）。
这样它在 A03 里的表现是诚实的：

- 风险解释区**不展示"由某某指标算出等级"**（因为确实不是算出来的）；
- 改为展示：来源=外部事件录入、录入时间与录入人、关联到的真实供应商实体、
  以及**它驱动了什么**——即该供应商供货的物料当前库存敞口（这部分是真算的，走 §1.2 同一套 drivers/evidence）;
- `origin != "recompute"` 的风险不参与 §1.1.2 的状态机，重算不碰它。

这比"给它编一个分数"更符合本批"不得使用硬编码 demo 话术"的目标：
**去硬编码的正确终点是"标明它从哪来"，不是"假装它是算出来的"。**

同一处置适用于所有用户手工创建的风险与未来的 ERP 事件风险。

**影响面核查**（已实测）：`grep -rn "risk-1\|risk-2\|RISK-20260709"` 全仓命中仅
`src/webapi/seed.py` 与 `chainguard-web/src/services/mockData.ts`，
**没有任何 pytest / E2E 断言依赖这两条的 id 或分数**，改动安全。
`mockData.ts` 是 mock 模式的前端数据，与 api 模式无关，本批不动（保持 mock/api 双模式各自自洽）。

### 1.2 后端：风险解释（A03 主体）

新模块 `src/webapi/risk_explanation.py`，新端点：

```
GET /api/v1/risks/{risk_id}/explanation      权限 risk:view（不新增权限码）
```

响应结构（`available=false` 时也返回 200，让前端渲染"限制说明"而非报错弹窗）：

```jsonc
{
  "available": true,
  "risk": { "id", "code", "level", "score", "rule", "status", "foundAt" },
  "verdict": {                       // 为什么现在是这个等级
    "warningLevel": "红色预警",
    "riskIndex": 78.4,
    "triggerThreshold": 70,          // 与 C1 同源
    "thresholdSource": "tenant_config" | "expert_default",
    "shouldTriggerResponse": true,
    "narrative": [ ... ]             // 直接取引擎 explanation[]，非 LLM、非模板话术
  },
  "drivers": [                       // 由哪些数据触发：四维分项，权重×分项=贡献
    { "key": "shortage_urgency", "label": "缺货紧迫度",
      "score": 91.2, "weight": 0.4, "contribution": 36.5,
      "currentValue": 31.2, "unit": "hour", "metric": "支撑小时数",
      "threshold": { "yellow": 72, "red": 24 }, "comparison": "below_red" },
    ...
  ],
  "deltas": {                        // 变化/异常原因
    "previousScore": 64.1, "previousAt": "...", "change": +14.3,
    "changedDrivers": [ { "key": "transit_delay", "from": 12.0, "to": 48.0 } ]
  },
  "evidence": [                      // 可追溯来源
    { "entity": "material",  "id": "MCU-A9", "name": "...",
      "fields": { "daily_consumption": 480 },
      "updatedAt": "...", "link": "/data/material?id=MCU-A9" },
    { "entity": "inventory", "id": "INV-0031", "warehouse": "上海一仓",
      "fields": { "on_hand_qty": 15000, "safety_stock_qty": 24000 },
      "updatedAt": "...", "link": "/data/inventory?id=INV-0031" },
    { "entity": "supplier",  ... }, { "entity": "order", ... }
  ],
  "provenance": {                    // 导入批次（见 §2 已知限制）
    "scope": "resource_type",        // 明确不是行级血缘
    "batches": [ { "resourceType": "inventory", "importJobId": "...",
                   "fileName": "...", "finishedAt": "...", "source": "csv_import" | "erp_sync" } ]
  },
  "decisionLink": {                  // 与决策链路衔接
    "contextKeys": ["inventory.current_stock", "inventory.safety_stock",
                    "derived_metrics.critical_order_exposure", "suppliers[]"],
    "readiness": { "ready": true, "level": "degraded", "degraded": ["missing_safety_stock"] },
    "incidentId": null,
    "canCreateIncident": true
  },
  "limitations": []                  // 降级/缺数据说明，永远存在这个字段
}
```

**`available=false` 的四种情形**（必须显式区分，不得伪造解释）：

| code | 场景 | 前端文案区域 |
|---|---|---|
| `CG-2511` | 风险未关联租户内有效物料 | "该风险无结构化实体来源，无法生成数据解释" |
| `CG-2512` | 物料日消耗量缺失或 ≤0 | "缺少物料日消耗量，无法计算支撑小时数" |
| `CG-2513` | 物料无库存记录 | "该物料尚无库存数据，请先导入库存" |
| `CG-A031` | 风险状态为 `resolved` / `ignored` | "风险已消除/已忽略，展示的是消除时的最后一次解释快照" |

前三个直接复用 C1 已有的 `ContextBuildError` 码，不发明新码。

**脱敏**：`evidence` 与 `deltas` 含 `order_amount`/`gross_profit`/`penalty_cost`/`customer_level`/
`supplier_price`，出口前一律过 `decision_detail.mask_for_requester(payload, ctx.permissions)`
——与 decision-detail、JSON/PDF 导出同一条脱敏路径，不新增权限码（复用
`field:cost:view` / `field:profit:view` / `field:customerLevel:view`）。

**租户隔离**：所有取数走 `TenantContextBuilder`（构造即绑 `tenant_id`）与
`get_tenant_record(db, Risk, id, ctx.tenant_id)`；`provenance` 的 ImportJob 查询同样带
`tenant_id` 过滤。跨租户请求走已有的 404 路径，不泄露存在性。

### 1.3 前端（C 级改动，规格来源 `codex_frontend_spec/`）

| 落点 | 改动 |
|---|---|
| `/risk/list` | 「风险指数」列旁加"解释"链接；行操作区加「风险解释」按钮（`access.canViewRisk`，即 BASE 权限即可） |
| **新** `RiskExplanationDrawer` 组件 | 抽屉，四段式：① 结论条（等级徽标 + 指数 + 阈值对比 + 触发规则）→ ② 驱动因素表（分项/权重/贡献/当前值 vs 阈值，横向条形）→ ③ 证据来源列表（实体卡片，可点击跳 `/data/*` 对应资料页并高亮该行）→ ④ 数据来源与限制（导入批次 + `limitations` + 配置来源徽标"数据驱动/专家默认"） |
| `/risk/overview` | 顶部加「重新扫描风险」按钮（`access.canManageRisk`），调 `POST /risks/recompute`，完成后 toast 显示新增/更新/消除条数 |
| `src/services/risk.ts` | 新增 `getRiskExplanation(riskId)`、`recomputeRisks()`，双模式（api / mock），mock 走 `workflowStore` |
| `src/pages/Incident/Detail.tsx` | 来源风险区每条加"查看风险解释"入口，复用同一抽屉 |
| 窄屏 | 抽屉在 ≥375px 下可读（沿用 5A 预期管理条款） |

**不新增路由**——抽屉挂在既有页面，符合结合审计表"无路由变更"的口径。

---

## 2. 数据来源与"真实性"边界

| 解释里的每个数字 | 来自 | 是否可能是估算 |
|---|---|---|
| 风险指数、四维分项 | `src/inventory_monitor.calculate_inventory_risk` 实时重算 | 否 |
| 权重、触发阈值 | `tenant_configs`（已获批）否则 `config/*.yaml` 专家默认；来源在响应里标注 | 否，但来源必须标 |
| 当前库存 / 安全库存 / 在途 | `inventory` 表按物料聚合 | 安全库存缺失时按"日消耗×24"替代，**必落 `limitations`** |
| 支撑小时数 | `current_stock / (daily_consumption/24)` | 否 |
| 在途延误小时 | `estimated_arrival_at - planned_arrival_at` | 无 estimated 时按事件延误推算，**必落 `limitations`** |
| 关键订单敞口 | `sales_orders` + `sales_order_lines` + `customers`（未关闭订单） | 罚金/毛利缺失时按 `estimation_coefficients` 估算，**必落 `limitations`** |
| 供应商备选 | `supplier_materials` + `suppliers`（qualified=true） | 可靠性缺失记 `missing_supplier_reliability` |
| 实体更新时间 | 各实体行 `updated_at` | 否，行级真实 |
| 导入批次 | `import_jobs` 该租户该资源类型最近一次成功记录 | **是资源类型级，不是行级血缘** |

**已知限制（写进交付材料，不掩饰）**：
实体表（`EntityRecord`）没有 `source_import_job_id` 列，本批**不加列、不做迁移**（避免回归已验收的 C2）。
因此 `provenance.batches` 的语义严格定义为"该租户该资源类型最近一次导入/同步批次"，
响应里以 `scope: "resource_type"` 显式声明，前端文案写「最近一次导入批次（非本行血缘）」。
行级血缘若要做，需 EntityRecord 加列 + Alembic 迁移 + C2 回归，建议单列一批。

**`deltas` 的前值来源**：`risks.details.snapshot_history`（重算时追加，保留最近 5 次）。
首次重算无前值时 `deltas: null`，前端显示"首次计算，无对比基线"——不编造变化。

---

## 3. 界面位置汇总

```
/risk/list          风险列表 → 行内「风险解释」→ RiskExplanationDrawer
/risk/overview      风险总览 → 顶部「重新扫描风险」（risk:manage）
/incident/:id       事件详情 → 来源风险区「查看风险解释」→ 同一抽屉
/data/material      证据跳转目标（物料）
/data/inventory     证据跳转目标（库存）
/data/supplier      证据跳转目标（供应商）
/data/order         证据跳转目标（订单）
```

---

## 4. 验收清单

### 4.1 后端 pytest（新增 `tests/test_phase5b_a03_risk_explanation.py`）

| # | 用例 | 断言要点 |
|---|---|---|
| B1 | 真实实体重算产出风险 | 灌入物料/库存/订单/供应商 → recompute → risks 表出现该物料风险，score 等于直接调 `calculate_inventory_risk` 的结果（**逐位相等**，证明未另写公式） |
| B2 | 解释四维分项 | `drivers` 四项权重之和 = 1，`sum(contribution)` == `riskIndex`（浮点容差 0.01） |
| B3 | 阈值/当前值对比 | 支撑小时数 < red_support_hours 时 `comparison == "below_red"`；阈值取值与 C1 `_decision_configuration` 返回一致 |
| B4 | 租户配置 vs 专家默认 | 建 approved `thresholds` TenantConfig → `thresholdSource == "tenant_config"`；未获批 → `expert_default` + `fallback_reason` |
| B5 | 证据来源可追溯 | `evidence` 含 material/inventory/supplier/order 四类，每条带真实 `updatedAt` 与业务键 |
| B6 | 数据不足降级 · 无物料 | 风险 details 指向不存在物料 → `available=false, code=CG-2511`，且响应中**不含任何数字** |
| B7 | 数据不足降级 · 无日消耗 | `daily_consumption=None` → `CG-2512` |
| B8 | 数据不足降级 · 无库存 | 无 inventory 行 → `CG-2513` |
| B9 | 风险已恢复 | 风险置 `resolved` → `available=false, code=CG-A031`，返回快照且标注为快照 |
| B10 | 安全库存缺失 | `limitations` 含 `missing_safety_stock`，且解释文案标注该值为替代估算 |
| B11 | **跨租户隔离** | 租户 B 请求租户 A 的 risk_id → 404；A 的物料名/仓库名/数量/updatedAt **不出现在任何响应体**（对整个响应 JSON 做子串断言） |
| B12 | **跨租户重算隔离** | 租户 B 触发 recompute 不产生任何指向租户 A 实体的风险 |
| B13 | 字段脱敏 | buyer（无 `field:cost:view`）请求 → evidence 里 `order_amount`/`penalty_cost`/`supplier_price` 为 `***`；scm_lead 可见真值 |
| B14 | 权限门槛 | 无 `risk:view` → 403；无 `risk:manage` 调 recompute → 403 |
| B15 | **C1 无回归** | `tests/test_phase5b_c1_tenant_decision.py` 全绿（material-keyed 重构后行为不变） |
| B16 | 与决策链路同源 | 同一物料：解释里的 `triggerThreshold` == `/incidents/{id}/decision-readiness` 的 `configuration` 中同一值 |
| B17 | **状态机 · 人工决定不被覆盖** | 风险置 `ignored` → recompute → 仍为 `ignored`（不复活）；置 `incident_created` → recompute → 状态与 `incident_id` 均不变 |
| B18 | **幂等** | 同一实体数据连续两次 recompute，`risks` 表除 `updated_at` 外零差异（逐字段比对，含 `code`、`found_at`） |
| B19 | **resolved 产生路径** | 先造触发态 → recompute 得风险 → 抬高库存使其不再触发 → recompute → 状态变 `resolved`，`details.lastExplanationSnapshot` 存在且为**消除前**的数值 |
| B20 | **复发** | 承 B19，再压低库存 → recompute → 状态回 `new`，`recurrenceCount == 1`，`found_at` 已刷新，`code` **未变** |
| B21 | **不碰非重算风险** | seed 的 `origin=external_event` 风险与手工风险，recompute 前后逐字段零差异 |
| B22 | **resolved 不再刷新** | 已 `resolved` 且仍不触发 → recompute → 快照数值与时间戳均不变（不漂移） |
| B23 | **seed 去硬编码** | 跑完 seed 后，MCU-A9 库存风险的 `score` == 直接调 `calculate_inventory_risk` 的结果；seed 源码中**不存在**字面量分数 |
| B24 | **外部事件风险的解释形态** | `origin=external_event` 的风险请求 explanation → 不返回 `drivers` 中的"等级由指标算出"段，而返回来源标注 + 其驱动的库存敞口，且 `limitations` 说明来源为外部录入 |

### 4.2 前端单测（vitest）

| # | 用例 |
|---|---|
| F1 | `RiskExplanationDrawer` 渲染四段，驱动因素条形宽度按 contribution 归一 |
| F2 | `available=false` 时只渲染限制说明区，不渲染任何指数/阈值数字 |
| F3 | `deltas=null` 渲染"首次计算，无对比基线" |
| F4 | 证据卡片点击触发正确的 `/data/*` 跳转参数 |
| F5 | `provenance.scope=="resource_type"` 时文案含"非本行血缘" |

### 4.3 API 模式 Chromium E2E

新增 `playwright.risk-explanation-api.config.ts` + `e2e/risk-explanation-api-acceptance.spec.ts`
+ `scripts/seed_phase5b_a03_e2e.py`（与 calibration / erp / experience 同构，独立配置避免污染既有验收套件）。

| # | 场景 | 通过标准 |
|---|---|---|
| E1 | 真实数据风险解释 | seed 两租户实体 → 登录租户 A → `/risk/overview` 点「重新扫描风险」→ `/risk/list` 出现由真实物料算出的风险 → 打开解释抽屉，四段可见 |
| E2 | 阈值/当前值对比 | 抽屉中"支撑小时数 31.2h / 红线 24h"等对比可读，数值与 API 响应一致 |
| E3 | 证据来源跳转 | 点库存证据卡 → 跳 `/data/inventory` 且目标行高亮 |
| E4 | 数据不足降级 | 打开指向无库存物料的风险 → 显示 `CG-2513` 限制说明，截图证明页面无任何编造数字 |
| E5 | 风险已恢复 | 已消除风险 → 显示快照标注 |
| E6 | **跨租户隔离** | 登录租户 B → 直接请求租户 A 的 explanation 端点得 404；租户 B 的 `/risk/list` 与解释抽屉中不出现租户 A 的物料名/仓库名/供应商名（页面文本断言） |
| E7 | 脱敏 | 以 buyer 登录 → 解释抽屉金额显示 `***` |
| E8 | **忽略后重扫不复活** | 忽略一条风险 → 点「重新扫描风险」→ 列表中该风险仍为"已忽略"，未回到"新发现" |
| E9 | **外部事件风险** | 打开 seed 的供应商停产风险 → 解释区显示"来源：外部事件录入"及录入时间，**不显示**编造的指标推导 |

### 4.4 交付材料要求（沿用惯例）

- 实际执行的 `pytest tests/ -q` 全量原始输出（不是节选、不是"应该会绿"）
- `DATA_MODE=api npm run build` 零 error 原始输出
- 三份 playwright 原始输出（新配置 + 既有 api-acceptance 回归 + c1 相关）
- E1–E7 逐项截图
- 变更文件清单
- 已知限制章节（至少含 §2 的批次血缘限制、安全库存替代估算、无调度器自动重算）

---

## 5. 红线与影响面自查

| 红线 | 本批是否触碰 | 说明 |
|---|---|---|
| 演示输出必须稳定（70.25） | **否** | 不改 `config/risk_weights.yaml`、`config/thresholds.yaml`、`data/*.json`、`run_demo`。仍会在动工前后各跑一次演示流程比对存档 |
| LLM 绝不改数 | **否** | 解释文本直接取 `calculate_inventory_risk` 返回的 `explanation[]`（代码生成的中文串）+ 结构化字段渲染。**A03 全程不调用 LLM** |
| 测试全绿才能动主干 | 遵守 | 见 §4.4 |

| 已验收模块 | 影响 | 缓解 |
|---|---|---|
| C1 context builder | **有**：抽 material-keyed 取数路径 | 纯重构，行为不变，B15 锁定 |
| C2 实体表 | 无 | 只读，不加列不迁移 |
| OCR / 校准治理 / E-3 / C3 / ERP | 无 | 只读 `tenant_configs`、`import_jobs` |
| orchestrator / 决策算法 | 无 | 不进入 |
| 权限体系 | 无新增权限码 | 复用 `risk:view` / `risk:manage` / `field:*:view` |
| 数据库迁移 | **零迁移** | 新数据全部落 `risks.details` JSON |

---

## 6. 实施顺序

1. C1 material-keyed 重构 + B15 回归绿 ← 先做，最危险
2. `risk_recompute.py`（含 §1.1.1 身份/幂等 + §1.1.2 状态机）+ B1/B2/B12/B17–B22
3. seed 去硬编码（§1.1.3）+ B23
4. `risk_explanation.py` + 端点 + B3–B11/B13/B14/B16/B24
5. 前端 service + Drawer + F1–F5
6. 三处界面挂载
7. E2E seed 脚本 + 配置 + E1–E9
8. 全量回归 + 演示基线比对 + 交付材料

状态机（步骤 2）必须在 seed 去硬编码（步骤 3）之前完成并测绿——
seed 依赖 recompute 产出确定性 id，顺序反了会得到一个测不了的 seed。

---

## 7. 待确认（动工前需产品方点头）

- §2 的批次血缘限制口径（资源类型级）是否可接受为本批终态。
- 「重新扫描风险」为同步单次操作，物料量大时（1 万物料级）可能超时；
  是否接受本批以"分页/限流 + 前端进度提示"兜底，自动化重算留待后续批次。
- §1.1.3 对 `risk-1`（供应商停产）的处置——**标注外部来源而非伪造计算**——是否认可。
  若坚持要它也变成"算出来的"，需新写供应商风险评分公式，属新算法，须单独立项。
- 重算不接 D3 通知（§1.1.2 末），高风险新增时用户不会收到铃铛提醒，是否接受为本批终态。

## 8. 已知限制（预登记进交付材料）

1. 证据批次血缘为**资源类型级**，非行级（实体表无 `source_import_job_id` 列，本批不加列）。
2. 安全库存缺失时以"日消耗×24"替代，落 `limitations` 明示。
3. 无调度器自动重算，风险刷新依赖人工点「重新扫描风险」。
4. 重算只覆盖**库存风险**一类；供应/物流/需求/质量四类风险仍需外部录入，
   在界面上以 `origin=external_event` 标注来源，不伪造推导。
5. 重算不发通知（见 §7）。
6. `chainguard-web/src/services/mockData.ts` 的 mock 风险仍为硬编码，
   仅影响 mock 模式演示，api 模式不受影响；统一 mock/api 数据源属 D3 铃铛同类问题，不在本批。
