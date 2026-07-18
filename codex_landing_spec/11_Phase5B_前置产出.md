# Phase 5B 前置产出四件套（评审方主笔，2026-07-17 v2）

5B 动工的前提文档。四节分别为：①引擎输入契约 ②实体表设计与迁移 ③租户隔离设计 ④基准压测方案。依据：`data/*.json` 演示数据、`data_loader.load_demo_context`、`ScenarioLoader.load_context`（黄金参照）、`RestErpConnector.fetch_context`（现有 REST 字段适配）、`src/enterprise_ingest.py`/`src/streaming_import.py`（现有 CSV 原表导入）和 `scripts/erp_sync.py`（现有拉事件→推演→回写编排）。

边界说明：现有 `scripts/erp_sync.py` 本身没有“表→实体”持久化映射；v2 不再把不存在的映射写成可复用资产。5B 应复用 `RestErpConnector` 已有字段别名与规范化行为，并让 CSV 导入和 ERP 同步共同消费一份 `config/erp_mapping.yaml`，禁止另写第二套字段口径。本文件仍是纯规格，不代表 5B 已实现。

---

## ① 引擎 Context Schema（正式契约）

引擎入口消费的 `context` 为五段；Web builder 额外附加 `derived_metrics` 和 `data_quality`。**契约原则：字段名与单位一字不差沿用现状；builder 只许适配到这个形状，不许修改引擎内部。黄金参照同时输出的兼容别名必须双写，不能只保留其中一个。** 2026-07-17 对真实 `ScenarioLoader` 运行取样确认：五段键为 `inventory/orders/suppliers/transport_options/events`，运输枚举为 `air/truck/rail/sea`。

### inventory（单物料聚合，dict）

| 字段 | 类型 | 单位 | 必填 | 来源（5B builder） |
|---|---|---|---|---|
| material_id / material_name | str | — | ✔ | materials 表 |
| current_stock | float | 件 | ✔ | SUM(inventory.on_hand_qty) WHERE material |
| hourly_consumption | float | 件/时 | ✔ | materials.daily_consumption / 24（须>0，=0 时 builder 报 CG 业务错，禁止除零） |
| safety_stock | float | 件 | ✔ | SUM(inventory.safety_stock_qty) |
| in_transit_qty | float | 件 | ✔ | SUM(inventory.in_transit_qty) |
| planned_arrival_hours | float | 时 | ✔ | 事件前计划到达（无采购在途时 0） |
| estimated_arrival_hours | float | 时 | ✔ | planned + 事件 delay_hours |
| critical_order_demand | float | 件 | ✔ | SUM(A 级客户未交订单行数量) |
| external_risk_score | float | 0–100 | ✔ | 事件 risk_score（来自关联风险 score） |

### orders（list[dict]，按物料过滤）

| 字段 | 类型/单位 | 契约 |
|---|---|---|
| order_id、customer_name | str | 订单号；客户显示名由 sales_orders → customers 关联取得 |
| priority | 'A'/'B'/'C' | 由 customers.customer_level 映射 |
| required_material | str | 当前事件物料 |
| demand、demand_qty | float/件 | **同值兼容别名，必须双写**；黄金参照和部分引擎路径仍读取 `demand` |
| delivery_hours、due_hours | float/时 | **同值兼容别名，必须双写**；由 promised_delivery_at−UTC now 换算，过期取 0；`agents.py`/`game_model.py` 优先读取 `delivery_hours` |
| penalty_cost、gross_profit | float/元 | 订单头财务值；缺失时按客户级默认系数估算，具体路径写入 `data_quality.estimated_fields` |

禁止在每条订单行重复复制整张订单的 `gross_profit`/`penalty_cost` 后再求和；builder 以订单头值计一次，订单行只负责物料需求数量。

### suppliers（list[dict]，按可供该物料过滤）

supplier_id、supplier_name、material_id、status（受影响状态文案）、available_qty（件，**直存字段 available_emergency_qty**）、lead_time_hours（时）、delay_hours（时，受事件影响的供应商=事件延误，其余 0）、cost_multiplier（倍率，**直存字段 emergency_cost_multiplier，缺失取 1**——经核对 ScenarioLoader 黄金参照，非推导值）、reliability_score（0–100，suppliers 表直存，**缺失取 0 与黄金参照一致**并记 estimated）、region、supplier_rank（排序用）。仅取 qualified=1 的供应商，按 supplier_rank 升序。

### transport_options（list[dict]，租户级配置）

mode（**air/truck/rail/sea**，`truck` 为 canonical code；外部输入若写 `road` 只允许在适配边界转成 `truck`）、name、available（bool，事件可置否——如台风关港）、estimated_hours、cost_multiplier（倍率，黄金参照与引擎成本评分直接消费）、cost_level（高/中/中低/低）、risk_note。来源：tenant_configs.transport_options，缺省值逐字段复制 `ScenarioLoader.TRANSPORT_OPTIONS`；不得在引擎内部增加 `road` 分支。

### events（list[dict]）

event_id、event_type、type（同值别名，黄金参照双写）、title、severity、event_status、location、affected_supplier、affected_material、affected_route、delay_hours、estimated_delay_hours（同值别名）、external_risk_score、weather_risk、description。5B 由 Web 事件（incident）+ 关联风险映射：event_type 取 incident.type，severity 取 incident.level，delay_hours/risk_score 取自风险 details（缺失走降级规则）。

### derived_metrics（Web builder 加法字段，不入业务实体表）

`ScenarioLoader.load_context()` 当前不返回本段；它是 Web builder 为就绪度、展示和持久化追加的兼容扩展，不是“黄金参照已有字段”。计算式：inventory_support_hours = current_stock/hourly_consumption；arrival_delay_hours = estimated−planned；safety_stock_gap = max(safety_stock−current_stock, 0)。引擎消费五段时忽略该加法字段。

### Builder 契约与数据充分性三级判定（量化）

新模块 `src/webapi/context_builder.py`：`build_incident_context(db, tenant_id, incident_id) -> tuple[dict, DataQuality]`；配 pydantic 模型 `EngineContext` 校验（webapi 侧，不侵入引擎）；聚合一律在 SQL 完成（对齐 ScenarioLoader 模式，引擎输入 O(单物料关联数) 恒小）。新入口复用 `DecisionOrchestrator.run_scenario`，**orchestrator 内部零改动**。

**判定规则（依据引擎实测行为划线：引擎对空 suppliers/空 orders 有显式兜底——agents.py:84 出"人工寻源"方案、agents.py:362/game_model.py:357 空订单零影响——故此两项为降级而非阻断）：**

| 级别 | 条件（逐条可判定） | 行为 |
|---|---|---|
| **阻断**（不生成方案，返回对应错误码） | ①CG-2511 事件关联风险中解析不出 materials 表中存在的 material_id；②CG-2512 该物料 daily_consumption 缺失或 ≤0（支撑时长除零）；③CG-2513 inventory 表该物料 0 行记录（注意：有记录且 on_hand_qty=0 是合法业务状态，不阻断） | 前端"生成方案"处显示具体缺项与"去补数据"链接 |
| **降级**（生成方案，结果标记数据质量） | ①可供该物料的供应商 0 家（引擎产出"人工寻源"方案）；②关联订单 0 单（客户影响=0）；③safety_stock 全部未设置（=0 视为未设置并提示，风险指数含义受限）；④penalty_cost/gross_profit 缺失走客户级默认系数（estimated）；⑤**中/低风险**事件 delay_hours 无法解析取默认 24h（estimated）；⑥reliability_score 缺失取 0（与黄金参照一致，estimated） | context 附带并持久化 `data_quality` 对象（见下），推演页与方案卡显示"⚠ 基于不完整数据"黄条与明细 |
| **阻断补充** | CG-2514 **高风险**事件缺预计延误：前端表单层高风险事件"预计延误"必填兜底；API 直调或存量数据缺失时 builder 阻断并要求补填 | 同阻断级行为 |
| **完整** | 以上均不触发 | 正常 |

**data_quality 对象**（随 decision_details 持久化）：`{level: "full"|"degraded", blocking: [], degraded: ["no_suppliers", ...], estimated_fields: ["orders[2].penalty_cost", "event.delay_hours", ...]}`。

**决策就绪度接口**：`GET /api/v1/incidents/{id}/decision-readiness` 返回逐段体检结果（物料识别 ✓/✗、消耗速率 ✓/✗、库存记录 n 行、供应商 n 家、订单 n 单、安全库存已设/未设、预计延误 来源/默认）。前端事件详情与方案生成页在"生成方案"按钮旁展示就绪度卡——用户在点击前就知道会得到完整/降级/阻断，而不是点完才报错。就绪度规则与 builder 判定共用同一实现（单一事实源，禁止两套逻辑）。

---

## ② 实体表设计与迁移

### 同一 revision 的新表范围（8 张）

首个 C2 Alembic revision 同时创建 **7 张业务表 + 1 张 tenant_configs**。已有 `experience_cards` 直接复用，不重复建表；`data_records` 保留作为只读迁移源。所有新表均含 `id`（内部主键）、`tenant_id`、`extra` JSON、`created_at`、`updated_at`，并对 `tenant_id` 建索引。

| 表 | 核心字段 | 租户内业务唯一键 / 关联 |
|---|---|---|
| materials | material_id、material_name、category、unit、daily_consumption、unit_cost、is_critical | UNIQUE(tenant_id, material_id) |
| suppliers | supplier_id、supplier_name、region、status、reliability_score | UNIQUE(tenant_id, supplier_id) |
| supplier_materials | supplier_material_id、supplier_id、material_id、qualified、supplier_rank、available_emergency_qty、lead_time_hours、emergency_cost_multiplier、supplier_price | UNIQUE(tenant_id, supplier_id, material_id)；tenant-aware FK 到 suppliers/materials |
| customers | customer_id、customer_name、customer_level、region、contract、owner | UNIQUE(tenant_id, customer_id) |
| sales_orders | sales_order_id、customer_id、order_status、promised_delivery_at、order_amount、gross_profit、penalty_cost | UNIQUE(tenant_id, sales_order_id)；tenant-aware FK 到 customers |
| sales_order_lines | sales_order_line_id、sales_order_id、line_no、material_id、ordered_qty、unit_price | UNIQUE(tenant_id, sales_order_id, line_no)；tenant-aware FK 到 sales_orders/materials |
| inventory | inventory_id、material_id、warehouse_id、warehouse_name、on_hand_qty、available_qty、safety_stock_qty、in_transit_qty、planned_arrival_at、estimated_arrival_at | UNIQUE(tenant_id, inventory_id)；tenant-aware FK 到 materials；同物料允许多仓 |
| tenant_configs | config_type、payload、version、source、is_active、approved_by、approved_at | UNIQUE(tenant_id, config_type, version)；同一 tenant/config_type 只能有一个 active 版本（仓储层事务校验，PostgreSQL 用 partial unique index） |

所有跨业务表关联必须包含 `tenant_id`，禁止只用裸 `material_id/customer_id/supplier_id` 做跨租户 FK。SQLite/PostgreSQL 两端 migration test 都要开启并验证外键。`gross_profit`/`penalty_cost` 按企业 CSV 与黄金参照保留在 `sales_orders` 订单头；不得放进 `sales_order_lines` 后按行重复累计。

`planned_arrival_at/estimated_arrival_at` 的来源是企业 `shipments.csv`：导入时按物料汇总在途数量，并选择最近一笔未完成在途的计划/预计到达时间写入库存聚合字段；没有在途时为空，builder 输出 hours=0 并在 data_quality 标记来源缺失。所有时间以 UTC 入库，API 展示时再转租户时区。

### 产品界面列→实体/派生字段映射（2026-07-17 真 API 页面核实）

使用全新隔离库、`uvicorn:8000 + Umi(api):8001` 登录产品界面，逐页读取实际 ProTable 表头。`质量评分` 是当前 DynamicField 扩展列，`操作` 是 UI 行为列，二者不是核心实体字段。

| 产品页 | 实测可见列 | 5B 数据来源 |
|---|---|---|
| 物料管理 | 物料编号、物料名称、分类、库存、安全库存、成本、质量评分、操作 | materials 基本字段；库存/安全库存按 inventory 聚合；成本=unit_cost；质量评分=扩展字段 |
| 供应商管理 | 供应商编号、供应商、状态、交期、采购价、质量评分、操作 | suppliers 基本字段；交期/采购价取该物料或默认主供关系的 supplier_materials；多物料时详情必须展示关系明细，不得静默任选 |
| 客户管理 | 客户编号、客户名称、客户等级、合同、负责人、质量评分、操作 | customers 直出；质量评分=扩展字段 |
| 订单管理 | 订单号、客户、交付日、金额、利润、状态、质量评分、操作 | sales_orders + customers；金额=order_amount，利润=gross_profit，交付日=promised_delivery_at |
| 库存管理 | 库存编号、仓库、物料、可用数量、可支撑、状态、质量评分、操作 | inventory + materials；可用数量=available_qty；可支撑=available_qty/hourly_consumption；状态由租户阈值派生 |

因此 C2 切换数据源时必须保持上述 UI 契约；不得因为数据库字段改名让现有列变空。物流页按总规格继续维持 mock，不纳入第一批实体切换。

### 数据流三合一与唯一映射源

- 导入向导（csv/xlsx/归一化后的 pdf/图片）→ preflight → execute → `config/erp_mapping.yaml` → 上述实体表；签名重复闸门（D04）在 execute 前查 signature_history。
- ERP 同步继续由 `scripts/erp_sync.py` 编排，复用 `RestErpConnector` 的字段别名/数值规范化；持久化阶段与导入向导调用同一个 mapping adapter 和同一份 yaml。禁止在脚本、router 和 builder 各维护一份映射。
- `src/enterprise_ingest.py`/`src/streaming_import.py` 当前只负责 CSV→原名表的批量导入、索引与对账；5B 可复用批量/对账能力，但不能把它描述成现成实体映射。
- 前端五个资料页 `GET/POST /data/{type}` 切换到实体仓储层；切换后 `data_records` API 停写。读路径不允许实体表/data_records 静默混读，回滚只通过版本回退完成。

`config/erp_mapping.yaml` 至少逐表声明：source table、source key、target table、target key、字段重命名、类型/单位转换、必填字段、未知列处理（默认进入 `extra`，安全敏感列拒绝）、头/行聚合规则。模板和校验器属于 C2 同批交付。

### data_records 存量迁移与可回滚性

Alembic data migration 按 resource_type 分流（material/supplier/customer/order/inventory），以 `(tenant_id, business_key)` upsert，重复执行映射函数不得产生重复行。payload 未映射字段进入对应实体 `extra`；缺业务主键的记录不猜值，写迁移拒绝清单并保留在 data_records。

升级成功后 data_records 保留只读作为审计/回滚源，API 停写；downgrade 只删除 8 张新表，不删除或反写 data_records。迁移测试必须覆盖：空库、重复 business key、缺主键、跨租户同业务键、upgrade→downgrade→upgrade、二次执行映射函数行数不增长。

---

## ③ 租户隔离设计

1. **tenant_configs**：随②节首个 revision 创建；config_type 至少支持 thresholds/risk_weights/transport_options/calibration_state/estimation_coefficients。仓储层所有读取必须同时过滤 tenant_id + config_type + is_active；找不到 active 版本才回退全局默认。Web API 把已解析配置作为参数传入现有引擎入口，`load_thresholds` 继续只做全局 fallback，引擎内部不感知租户。
2. **校准状态机（量化）**：新租户 source=expert（全局默认）。已完结决策（审批通过且事件 closed、结果字段完整）计为 1 个样本；租户样本量 ≥ 5（引擎 `weight_manager.MIN_SAMPLES=5`，沿用不另设）时治理面板解锁"计算校准值"→ 对比展示（数据驱动值 vs 专家默认值、样本量、每参数偏离幅度）→ 人工放行（approved_by 落库）→ source=calibrated。面板须明示："样本 <30 时校准值统计置信有限，建议观察模式"（观察模式=展示对比但继续用 expert 值）。漂移检测（drift_monitor）按租户跑，漂移超过引擎既有阈值时经 D3 通知 admin/scm_lead，并在面板标红待复核。
3. **经验卡**：复用已有 experience_cards 表（tenant_id 已具备），不新建第二张表。Web 侧新增 DB card provider，查询条件强制 tenant_id；TfidfStore 的输入由 provider 返回的本租户卡片构造，缓存键必须为 `(tenant_id, card_version)`，本租户写卡只失效本租户索引。Streamlit 继续走文件 provider。**测试必须包含跨租户检索隔离断言**（A 租户经验绝不出现在 B 租户推荐里——商业机密级）。
4. **引擎文件态**：data/*.jsonl 审计已由 5A-3 入库；experience_cards.json 仅供 Streamlit 演示路径保留，Web 路径全走 DB。

### 最小租户隔离负向断言

- A/B 租户可使用相同 material_id、supplier_id、customer_id、sales_order_id，查询结果仍严格分离。
- A 租户不能通过 ID 枚举读取、更新、删除 B 租户实体；统一返回现有 404/权限口径，不暴露对象是否存在。
- A 租户导入批次、signature_history、配置版本、经验卡和 context builder SQL 均不得命中 B 租户数据。
- context builder 的每个 join 条件都包含 tenant_id；测试构造“业务键相同、数值不同”的双租户夹具，断言 context 和推荐不串值。
- TfidfStore 缓存命中、失效、重建三个路径分别做跨租户负向断言。

---

## ④ 基准压测方案

**关键结论先行**：context builder 在 SQL 层聚合（对齐 ScenarioLoader），引擎输入规模 = O(该物料的供应商数+订单数)，与库存总行数解耦——预期瓶颈在 SQL 聚合与实体表索引，而非引擎计算。压测用于证实并给出容量口径，而非探索。

- 数据集（2026-07-12 更新，产品负责人确认）：**首选既有 11 万条企业演示数据**（demo_assets/enterprise 全套 ERP 账，经 CSV 导入管线或 ERP mapping adapter 灌入一个演示租户）——同时充当 5B 端到端验收数据集与压测基线；用 `generate_enterprise_demo_data` 固定 seed 扩参生成 1 万/5 万 inventory 两档。**"11 万条数据完整灌入演示租户且前端各资料页/风险/决策链路可见可用"本身即 5B 验收场景的第一步。**
- 测项：①build_incident_context 耗时；②run_scenario 全链路（含约束求解/博弈 27 组合/敏感性）p50/p95；③4 并发决策作业下的 p95 与内存峰值（对应线程池容量）；④实体表导入 5 万行的 execute 耗时。
- 门槛：单次决策 p95 ≤ 30s（60s 超时留一倍余量）；4 并发不 OOM（api 容器 2G 限额内）；超标时优先优化 SQL 索引与聚合，其次才考虑调超时/容量文档。
- 产出物：`benchmarks/bench_5b_context.py` + 机器可读 JSON + 结果表写入 phase5b 交付材料；容量口径更新 deploy_guide。JSON 固定包含 dataset_seed、inventory_rows、related_orders、related_suppliers、concurrency、warmup_runs、measured_runs、builder_ms(p50/p95)、decision_ms(p50/p95)、import_ms、peak_rss_mb、errors、pass。

实现完成后的固定命令（当前仅定义口径，不声称已运行）：

```powershell
python benchmarks/bench_5b_context.py --inventory-rows 10000 --concurrency 1 --warmup 3 --runs 20 --output output/benchmarks/phase5b-10k.json
python benchmarks/bench_5b_context.py --inventory-rows 50000 --concurrency 4 --warmup 3 --runs 20 --memory-limit-mb 2048 --output output/benchmarks/phase5b-50k-c4.json
```

两个结果文件均须 `pass=true`，且 errors 为空；只贴单次最快值、缺 warmup、缺 p95 或缺峰值内存均不算通过。

---

## v2 机器核对记录（2026-07-17）

### 黄金参照字段核对

实际运行 `ScenarioLoader.list_scenarios(limit=1)` + `load_context(event_id)`，退出码 0。取样事件 `EVT-000128`：

- 五段：inventory、orders、suppliers、transport_options、events；黄金参照不含 derived_metrics。
- orders 同时存在 `delivery_hours/due_hours`、`demand/demand_qty`。
- transport_options 存在 `cost_multiplier`，mode 实值为 `air/truck/rail/sea`。
- suppliers 的 available_qty、cost_multiplier、reliability_score、supplier_rank 等字段与①节一致。

### 产品界面列覆盖核对

实际启动全新隔离 SQLite 库，完成现有 Alembic upgrade + seed，启动 `uvicorn:8000 + Umi(api):8001`，以企业管理员登录后逐页导航并读取真实表头。五页均成功渲染；列头结果已写入②节“产品界面列→实体/派生字段映射”。五张产品页 PNG 与服务日志保存在 `output/playwright/phase5b-spec-ui-20260717/`；核对过程中未写 5B 代码。

核对还确认：当前新 seed 库五页为空数据态，但表头、筛选、导入/导出/新建入口均来自真实 API 模式产品页面，不是读取 TS 配置后冒充界面验证。数据行可见性属于 5B 完成 11 万行灌入后的端到端验收，不在本次纯规格评审中提前宣称通过。

## 业务决策确认记录（2026-07-12 拍板，2026-07-17 v2 沿用）

1. **估算系数=按客户级**：违约金 = 订单额 ×（A 20% / B 10% / C 5%），毛利 = 订单额 ×（A 25% / B 20% / C 15%）；系数存 tenant_configs（config_type=estimation_coefficients）租户可调；所有估算值标 estimated。
2. **预计延误**：高风险事件创建/升级时**必填**（表单校验 + builder CG-2514 双层兜底）；中低风险选填，缺省 24h 标 estimated。
3. **经验卡绝对隔离**：无任何跨租户共享机制，测试断言锁死。
4. **压测口径**：1 万/5 万行两档，p95 ≤ 30s，4 并发 2G 内不 OOM。

以上四项继续有效；两轮机器验证（黄金参照字段核对、产品界面列覆盖核对）已于 2026-07-17 实际完成。v1 评审提出的 transport 枚举、ERP 映射来源、兼容别名、tenant_configs 范围、订单头财务字段、derived_metrics 定位、迁移/隔离断言和压测输出格式均已在 v2 关闭。因此，**Phase 5B 前置产出规格评审通过。**

## 前置产出验收与移交

两道闸门状态：5A Windows 验收已关闭；本 v2 前置规格评审已通过。**这只表示具备开工条件，不表示本轮已经开始或完成 5B 实现。** 移交给实现方时的开工顺序：先建 8 表 revision（7 业务表 + tenant_configs）与共享 mapping adapter，再按总规格执行 C2 导入落表和签名闸门；C2 稳定后才实现 context_builder/C1，随后跑压测基线，再进入 10 号总规格 5B 后续顺序。①节 schema 若与后续新增的引擎回归实测有出入，以引擎现状为准并同步回改本文。
