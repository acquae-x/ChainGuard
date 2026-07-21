# Phase 5B 收尾批 · A04「影响范围完整版」实现范围（动工前规格，2026-07-19）

上游规格：`10_Phase5_总规格.md` §Phase 5B 收尾批 + §结合审计表最后一行
（"A03/A04/C02 风险解释/影响范围/节点卡 → Risk 列表、Incident/Detail 四表、Dashboard 卡片区扩展"），
以及 `08_Streamlit功能全量对照.md` A04 行（"影响范围 Phase 4 尽力版，完整版 → 5B"）。

前置：A03（`phase5b_a03_实现范围.md` / `phase5b_a03_交付材料.md`）**已验收完成**。
本批**不回退、不重写 A03**，只在其之上加"影响范围"这一维；C02/C03（节点健康）仍不在本批。

---

## 0. 动工前的现状勘察结论（它决定了 A04 的形状）

| 勘察项 | 结论 | 证据 |
|---|---|---|
| 现有影响范围端点 | `GET /incidents/{id}/impact` 存在，但实现是**对 `DataRecord` 做子串文本匹配** | `src/webapi/routers/business.py:221-236` |
| 匹配方式 | 把风险的 `object_name` 与 `details` 里所有字符串值当作关键词，去 `DataRecord.name + payload` 里找子串 | 同上 `terms` / `matches` |
| 数据源 | `DataRecord`（Phase 2 遗留的通用 KV 记录表），**不是 C2 实体表** | `models.py:349-353` |
| 前端影响范围页签 | 四张表，其中**客户等级硬编码 `"A"`**、**预计延误硬编码 `"2 天"`**、**替代供应商数按 `status === '停产'` 三元式硬编码 1/0** | `chainguard-web/src/pages/Incident/Detail.tsx:43-48` |
| 风险侧影响范围 | **不存在**。A03 抽屉有 evidence（解释证据），但没有"这条风险波及了谁" | `risk_explanation.py` 无影响范围段 |
| C2 实体外键 | 齐备且带 tenant_id 复合外键：inventory→material、supplier_materials→(supplier,material)、sales_order_lines→(order,material)、sales_orders→customer | `models.py:392-467` |
| 仓库主数据 | **不存在独立仓库表**。仓库只是 `inventory.warehouse_id / warehouse_name` 两列 | `models.py:459-460` |
| 任务与事件的关系 | `Task.incident_id` 真实外键列，审批通过后 `_create_execution_tasks` 落库 | `models.py:166`、`business.py:31-40` |

**推论一**：现有 impact 是**猜测关系**——"风险详情里出现过的任意字符串，在任意资料行文本里出现过"
就算受影响。这既会漏（实体表里的真实外键关系它看不到），也会误报（"上海"能匹配到一切含"上海"的行）。
按本批第 3 条要求（禁止猜测关系），它必须被替换，而不是保留。

**推论二**：前端那三处硬编码字面量（`"A"` / `"2 天"` / `1`）是**伪造影响结论**，
无论后端怎么改都必须一并清掉——否则界面仍在展示编造数据。

**推论三**：仓库没有主数据表。A04 的"仓库"分组只能是**从库存行聚合出的仓库**，
这一点必须在响应与界面上显式声明，不能假装系统有仓库实体。

---

## 1. 实现范围

### 1.1 后端：影响范围引擎（新模块 `src/webapi/impact_scope.py`）

**零新算法**：本模块不评分、不加权、不排序打分，只做**图遍历 + 去重 + 分组**。
所有"关系"必须是 C2 里**真实存在的外键**，不做任何字符串模糊匹配。

#### 1.1.1 起点（seeds）解析

| 场景 | 起点来源 |
|---|---|
| 风险影响范围 | `risk.details.material_id`（A03 重算风险必写）→ 物料；`risk.details.supplier_id` → 供应商 |
| 事件影响范围 | `incident.source_risk_ids` → 逐条风险，按上一行取物料/供应商并集 |

解析一律复用 A03/C1 已有路径（`TenantContextBuilder._resolve_material` 同款键名集合），
**不新发明键名**。起点解析不到 → 见 §1.3 降级。

#### 1.1.2 遍历关系（两跳，沿真实外键，全部带 tenant_id）

```
起点物料 M
 ├─ 直接 ─ inventory        WHERE tenant_id, material_id = M          关系 material_inventory
 ├─ 直接 ─ 仓库（由上面 inventory 行的 warehouse_id 聚合去重）        关系 inventory_warehouse
 ├─ 直接 ─ supplier         VIA supplier_materials(tenant_id, material_id = M)  关系 supplies_material
 ├─ 直接 ─ sales_order      VIA sales_order_lines(tenant_id, material_id = M)   关系 order_consumes_material
 └─ 间接 ─ customer         VIA sales_orders.customer_id（上一行订单的客户）    关系 order_customer
 └─ 间接 ─ material（同供应商的其他物料）
                            VIA supplier_materials(supplier ∈ 上面供应商集)     关系 shared_supplier

起点供应商 S（外部录入型风险才有）
 └─ 直接 ─ supplier S 自身                                            关系 seed_supplier
 └─ 直接 ─ material         VIA supplier_materials(tenant_id, supplier_id = S) 关系 supplied_by_seed_supplier
    （这些物料再按上面物料分支展开，但其展开结果一律记为 indirect）

起点事件 I
 └─ 直接 ─ task             WHERE tenant_id, incident_id = I          关系 incident_task
```

风险侧的任务：仅当 `risk.incident_id` 非空时，按同一条 `Task.incident_id` 取，记为 indirect。

**跳数上限硬编码为 2**，不做可配置深度——第三跳（客户的其他订单）的因果关系已经很弱，
在 11 万条企业数据下只会制造噪音。这条写进已知限制。

#### 1.1.3 去重与 degree 归属

- 去重键：`(entityType, businessId)`，全局唯一。
- 同一实体既被直接命中又被间接命中 → **direct 胜出**（degree 只降不升）。
- 起点物料本身出现在"同供应商的其他物料"里时，按起点处理，不重复计数。
- 订单只纳入**未关闭**的（复用 `context_builder._CLOSED_ORDER_STATUSES`，不新定义状态集）；
  被排除的数量落 `limitations`，不静默丢弃。

#### 1.1.4 每条影响记录的结构

```jsonc
{
  "entityType": "supplier",
  "id": "SUP-A03-01",
  "name": "苏州芯片封测厂",
  "degree": "direct",                       // direct | indirect
  "relation": {
    "code": "supplies_material",
    "label": "为受影响物料供货",
    "via": "supplier_materials",            // 承载关系的真实表名
    "path": ["material:MCU-A9", "supplier_materials", "supplier:SUP-A03-01"]
  },
  "status": { "label": "停产", "value": "stopped" },   // 该实体当前业务状态，无则 null
  "fields": { "region": "江苏", "reliabilityScore": 0.62, "supplierPrice": 12.5 },
  "source": { "table": "suppliers", "resourceType": "supplier",
              "batch": { "importJobId": "...", "fileName": "...", "finishedAt": "...",
                         "source": "csv_import", "scope": "resource_type" } },
  "updatedAt": "2026-07-18T09:12:00+00:00",  // 实体行真实 updated_at
  "link": "/data/supplier?id=SUP-A03-01"
}
```

`source.batch` 复用 A03 `RiskExplainer._provenance` 的**同一条**批次解析逻辑并抽为公共函数
（`impact_scope.latest_batches(db, tenant_id, resources)`），A03 改为调用它，
**行为与响应结构均不变**——保证两处"数据来源"口径一致，这是本批第 5 条要求的技术兑现。
其 `scope` 仍是 `resource_type`（非行级血缘），限制沿用 A03 §2。

#### 1.1.5 响应契约

```jsonc
{
  "available": true,
  "code": null,
  "scopeOf": { "kind": "risk" | "incident", "id": "...", "code": "...", "name": "..." },
  "seeds": [ { "entityType": "material", "id": "MCU-A9", "name": "...", "from": "risk.details.material_id" } ],
  "summary": { "total": 14, "direct": 9, "indirect": 5,
               "byType": { "material": 3, "inventory": 2, "warehouse": 2,
                           "supplier": 2, "order": 3, "customer": 2 } },
  "groups": [
    { "entityType": "material", "label": "物料", "total": 3, "direct": 1, "indirect": 2,
      "items": [ ... ] },
    ...
  ],
  "traversal": { "maxHops": 2, "relations": ["material_inventory", "supplies_material", ...] },
  "limitations": [ { "code": "CG-A042", "message": "..." } ],
  "generatedAt": "..."
}
```

分组固定顺序：`material / inventory / warehouse / supplier / order / customer / task`；
**没有命中的分组仍然出现**，`total = 0` 且带一条组内 `emptyReason`——
"暂无数据"必须是显式的，不能靠分组消失来暗示。

### 1.2 端点

```
GET /api/v1/risks/{risk_id}/impact-scope       权限 risk:view       新增
GET /api/v1/incidents/{item_id}/impact         权限 incident:view   就地替换实现
```

`/incidents/{id}/impact` **保留路径与权限码**，内部换成本引擎（产品方已确认：就地替换）。
旧的 `DataRecord` 子串匹配实现整体删除——它是"猜测关系"，按本批第 3 条不得保留。
**不新增权限码**，不新增路由（风险侧挂在既有抽屉里）。

### 1.3 数据不足时的降级（禁止伪造）

| code | 场景 | 语义 |
|---|---|---|
| `CG-2511` | 风险/事件未关联租户内有效物料，且无供应商起点 | `available=false`，无法确定影响起点 |
| `CG-A041` | 起点解析成功，但两跳内**零关联实体** | `available=true`，所有分组为空并明示"范围有限：该起点在当前数据下无关联业务对象" |
| `CG-A042` | 仓库来自库存行字段聚合 | 恒常提示：系统无独立仓库主数据，仓库为库存行聚合结果 |
| `CG-A043` | 事件的 `source_risk_ids` 为空或全部失效 | `available=false` |
| `CG-A044` | 单类实体命中数超过 500 上限被截断 | `available=true`，明示已截断及真实总数 |
| `CG-A045` | 已关闭订单被排除 | 明示排除条数 |

`available=false` 一律返回 **200**（与 A03 一致），让前端渲染限制说明而非报错弹窗。

### 1.4 租户隔离与脱敏（严格复用，零新机制）

- 每一条 `select()` 都带 `tenant_id == self.tenant_id`；起点记录经
  `get_tenant_record(db, Risk|Incident, id, ctx.tenant_id)` 取得，跨租户走既有 404 路径，不泄露存在性。
- 出口统一过 `decision_detail.mask_for_requester(payload, ctx.permissions)`——
  与 A03 解释、decision-detail、JSON/PDF 导出同一条脱敏路径。
  涉及 `orderAmount` / `grossProfit` / `penaltyCost` / `supplierPrice` / `unitPrice` / `customerLevel`。
- 不新增权限码，复用 `risk:view` / `incident:view` / `field:*:view`。

### 1.5 前端（C 级改动，规格来源 `codex_frontend_spec/`）

| 落点 | 改动 |
|---|---|
| **新** `ImpactScopePanel` 组件 | 按实体类型分组的可展开面板：组头显示 `标签 + 总数（直接 n / 间接 m）`，展开后是明细表——列为 `名称 / 影响关系 / 当前状态 / 数据来源 / 更新时间 / 跳转`；空组显示 `emptyReason` |
| `src/pages/Incident/Detail.tsx` | 「影响范围」页签整体换成 `ImpactScopePanel`；**删除硬编码的 `"A"` / `"2 天"` / 替代供应商三元式** |
| `src/components/RiskExplanationDrawer` | 新增第五段「影响范围」，复用同一面板；懒加载（抽屉打开才请求） |
| `src/services/risk.ts` | 新增 `getRiskImpactScope(riskId)`，双模式；mock 模式如实返回不可用，不编造关系 |
| `src/services/incident.ts` | `getImpact` 契约随后端更新 |
| 窄屏 | 面板在 ≥375px 下可读（沿用 5A 预期管理条款） |

**不新增路由**，跳转目标是既有 `/data/*` 资料页。

---

## 2. 数据来源与真实性边界

| 影响范围里的每个字段 | 来自 | 是否可能是估算 |
|---|---|---|
| 各类实体的 id / 名称 / 状态 | 对应 C2 实体表列 | 否，行级真实 |
| 影响关系 | C2 真实外键（表名写进 `relation.via`） | 否 |
| 各分组数量 | 去重后的真实计数 | 否 |
| 更新时间 | 实体行 `updated_at` | 否，行级真实 |
| 数据来源批次 | `import_jobs` 该租户该资源类型最近一次成功记录 | **是资源类型级，不是行级血缘**（沿用 A03 限制） |
| 仓库 | `inventory.warehouse_id/warehouse_name` 聚合 | **无独立主数据**，恒落 `CG-A042` |

**本批不计算任何"影响程度/损失金额"**。缺口量、延误天数、损失估算属决策链路（C1/orchestrator）职责，
A04 只回答"波及了哪些真实业务对象、经由什么关系"。硬要在影响范围里给出损失数字，
就必须新写一套影响评估公式——那是新算法，越界。这条写进已知限制。

---

## 3. 验收清单

### 3.1 后端 pytest（新增 `tests/test_phase5b_a04_impact_scope.py`）

| # | 用例 | 断言要点 |
|---|---|---|
| B1 | 直接影响完整 | 灌入物料/库存/供应商/订单/客户 → 风险影响范围含 inventory/supplier/order 三类 direct，数量与实体行数一致 |
| B2 | 间接影响 · 客户 | 订单的客户出现在 customer 组且 `degree == "indirect"`，`relation.path` 经由订单 |
| B3 | 间接影响 · 同供应商物料 | 供应商供货的另一物料出现在 material 组且为 indirect，`relation.via == "supplier_materials"` |
| B4 | 去重 | 同一供应商供两种受影响物料 → supplier 组只出现一次，`summary.byType.supplier == 1` |
| B5 | direct 优先于 indirect | 既直接又间接命中的实体 `degree == "direct"` |
| B6 | 仓库聚合 | 两条不同仓库的库存行 → warehouse 组 2 条；同仓库两行 → 1 条；`limitations` 含 `CG-A042` |
| B7 | 任务 | 事件影响范围含 `Task.incident_id` 匹配的任务 |
| B8 | 已关闭订单排除 | 已交付订单不在 order 组，`limitations` 含 `CG-A045` 且注明排除条数 |
| B9 | 空数据降级 · 无起点 | 风险 details 无物料无供应商 → `available=false, code=CG-2511`，响应中**不含任何实体名与数字** |
| B10 | 空数据降级 · 零关联 | 起点物料存在但无任何库存/订单/供应商 → `available=true`，各组 total=0 且带 emptyReason，`limitations` 含 `CG-A041` |
| B11 | 事件无来源风险 | `source_risk_ids=[]` → `CG-A043` |
| B12 | **跨租户隔离 · 风险** | 租户 B 请求租户 A 的 risk impact-scope → 404；A 的物料/仓库/供应商/客户名**不出现在任何响应体**（整份 JSON 子串断言） |
| B13 | **跨租户隔离 · 遍历不越界** | A、B 两租户存在同名同 id 的物料 → A 的影响范围只含 A 的实体行（按 `updated_at`/字段值区分） |
| B14 | 事件端点就地替换 | `/incidents/{id}/impact` 返回新契约（含 `groups`/`summary`），且不再依赖 `DataRecord` |
| B15 | 脱敏 | buyer（无 `field:cost:view`）→ `orderAmount`/`supplierPrice`/`penaltyCost` 为 `***`；无 `field:customerLevel:view` → 客户等级脱敏；scm_lead 见真值 |
| B16 | 权限门槛 | 无 `risk:view` → 403；无 `incident:view` → 403 |
| B17 | **A03 零回归** | `tests/test_phase5b_a03_risk_explanation.py` + `_risk_recompute.py` 全绿；`_provenance` 抽公共函数后响应结构逐字段不变 |
| B18 | **C1/C2 零回归** | `test_phase5b_c1_tenant_decision.py`、`test_phase5b_c2_entities.py` 全绿 |
| B19 | 跳数上限 | 客户的其他订单**不出现**在影响范围（证明未超两跳） |
| B20 | 截断 | 单类 >500 条 → `CG-A044` 且注明真实总数 |
| B21 | 关系可追溯 | 每条 items 的 `relation.via` 都是真实表名，`path` 首元素为起点 |

### 3.2 前端单测（vitest）

| # | 用例 |
|---|---|
| F1 | `ImpactScopePanel` 按固定顺序渲染全部分组，组头显示 `总数（直接 n / 间接 m）` |
| F2 | 空组渲染 `emptyReason`，不渲染空表格 |
| F3 | `available=false` 时只渲染限制说明，不渲染任何分组与数字 |
| F4 | 明细行跳转参数正确（`/data/supplier?id=...`） |
| F5 | `limitations` 逐条渲染，含 `CG-A042` 仓库口径说明 |
| F6 | Incident/Detail 影响范围页签**不再出现**硬编码的 `"2 天"` 与固定客户等级 |

### 3.3 API 模式 Chromium E2E

新增 `playwright.impact-scope-api.config.ts` + `e2e/impact-scope-api-acceptance.spec.ts`
+ `scripts/seed_phase5b_a04_e2e.py`（两个隔离租户 + 只读账号 + 一个零关联物料），与 A03 同构、独立端口与独立 DB。

| # | 场景 | 通过标准 |
|---|---|---|
| E1 | 事件影响范围 · 直接 | 登录租户 A → 事件详情「影响范围」→ 各分组计数可见，展开后明细为真实实体名 |
| E2 | 间接影响可辨识 | 客户行显示 `间接` 徽标与关系「经由订单关联的客户」 |
| E3 | 跳转 | 点供应商行跳转 → 落在 `/data/supplier` 且带正确 id 参数 |
| E4 | 风险侧影响范围 | 风险解释抽屉第五段「影响范围」可展开，与事件侧同构 |
| E5 | 空数据降级 | 零关联物料的风险 → 显示 `CG-A041` 范围有限说明，截图证明页面无编造实体 |
| E6 | **跨租户隔离** | 登录租户 B → 直接请求租户 A 的 impact-scope 得 404；租户 B 页面文本不含租户 A 任何实体名 |
| E7 | 脱敏 | buyer 登录 → 明细中金额与客户等级为 `***` |
| E8 | 权限 | 无 `incident:view` 账号访问事件影响范围 → 403 路径，不渲染分组 |

### 3.4 交付材料要求

实际执行的 pytest 全量原始输出、`DATA_MODE=api npm run build` 原始输出、
playwright 原始输出（新配置 + A03 回归 + 既有 api-acceptance 回归）、E1–E8 逐项截图、
变更文件清单、已知限制章节。

---

## 4. 红线与影响面自查

| 红线 | 本批是否触碰 | 说明 |
|---|---|---|
| 演示输出必须稳定（70.25） | **否** | 不改 `config/*.yaml`、`data/*.json`、风险/评分公式，**不调用 `run_demo`**，不进 orchestrator |
| LLM 绝不改数 | **否** | A04 全程不调用 LLM，无任何自然语言生成；关系标签是固定中文常量 |
| 测试全绿才能动主干 | 遵守 | 见 §3.4 |

| 已验收模块 | 影响 | 缓解 |
|---|---|---|
| **A03 风险解释/重算** | 仅把 `_provenance` 的批次解析抽为公共函数复用 | 纯抽取，响应结构不变，B17 逐字段锁定 |
| C1 context builder | 只读复用起点解析口径，**不改代码** | B18 回归 |
| C2 实体表 | **只读**，不加列、不迁移 | B18 回归 |
| 决策链路 / orchestrator | 不进入 | — |
| 权限体系 | 无新增权限码 | 复用 `risk:view` / `incident:view` / `field:*:view` |
| 数据库迁移 | **零迁移** | 纯查询模块，不落新表新列 |
| `DataRecord` 表 | 不再被 impact 使用，但表与其他用途保留 | 只删 impact 端点内的用法 |

---

## 5. 实施顺序

1. 抽 `latest_batches()` 公共函数，A03 改调用 + B17 回归绿 ← 先做，唯一触碰已验收模块处
2. `impact_scope.py` 遍历引擎 + B1–B8/B19–B21
3. 降级与隔离 + B9–B13
4. 两个端点（新增 + 就地替换）+ B14–B16
5. 前端 `ImpactScopePanel` + F1–F5
6. 两处挂载 + 清除硬编码字面量 + F6
7. E2E seed + 配置 + E1–E8
8. 全量回归 + 界面验收截图 + 交付材料

---

## 6. 已知限制（预登记进交付材料）

1. **两跳上限**，第三跳（客户的其他订单、供应商的其他客户）不纳入。
2. **仓库无独立主数据**，为库存行聚合结果，恒落 `CG-A042`。
3. **批次血缘为资源类型级，非行级**（沿用 A03 §2 限制，实体表无 `source_import_job_id` 列）。
4. **不计算影响程度/损失金额**，只给受影响对象与关系；损失估算属决策链路职责。
5. **单类 500 条截断**，超出时明示真实总数，不做分页游标。
6. **物流/路线未纳入**：`/data/logistics` 无对应 C2 实体表，无法沿真实外键遍历。
7. **mock 模式无影响范围**，服务层如实返回不可用，不在演示态编造关系。
