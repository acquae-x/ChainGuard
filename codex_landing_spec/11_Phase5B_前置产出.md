# Phase 5B 前置产出四件套（评审方主笔，2026-07-12 v1）

5B 动工的前提文档。四节分别为：①引擎输入契约 ②实体表设计与迁移 ③租户隔离设计 ④基准压测方案。依据：`data/*.json` 演示数据、`data_loader.load_demo_context`、`scenario_loader.load_context`（黄金参照）、`enterprise_ingest/erp_sync` 既有映射。

---

## ① 引擎 Context Schema（正式契约）

引擎入口消费的 `context` 为五段 + 派生指标。**契约原则：字段名与单位一字不差沿用现状（引擎 460+ 测试依赖它们），builder 只许适配到这个形状，不许改形状。**

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

order_id、customer_name、priority（'A'/'B'/'C'，由 customers.customer_level 映射）、required_material、demand_qty（件）、due_hours（时，由 promised_date−now 换算，过期取 0）、penalty_cost（元）、gross_profit（元）。penalty/profit 缺失时按客户级默认系数估算并在 context 标 `estimated: true`。

### suppliers（list[dict]，按可供该物料过滤）

supplier_id、supplier_name、material_id、status（受影响状态文案）、available_qty（件，**直存字段 available_emergency_qty**）、lead_time_hours（时）、delay_hours（时，受事件影响的供应商=事件延误，其余 0）、cost_multiplier（倍率，**直存字段 emergency_cost_multiplier，缺失取 1**——经核对 ScenarioLoader 黄金参照，非推导值）、reliability_score（0–100，suppliers 表直存，**缺失取 0 与黄金参照一致**并记 estimated）、region、supplier_rank（排序用）。仅取 qualified=1 的供应商，按 supplier_rank 升序。

### transport_options（list[dict]，租户级配置）

mode（air/road/rail/sea）、name、available（bool，事件可置否——如台风关港）、estimated_hours、cost_level（高/中/中低/低）、risk_note。来源：tenant_configs.transport_options，缺省用系统默认四式。

### events（list[dict]）

event_id、event_type、type（同值别名，黄金参照双写）、title、severity、event_status、location、affected_supplier、affected_material、affected_route、delay_hours、estimated_delay_hours（同值别名）、external_risk_score、weather_risk、description。5B 由 Web 事件（incident）+ 关联风险映射：event_type 取 incident.type，severity 取 incident.level，delay_hours/risk_score 取自风险 details（缺失走降级规则）。

### derived_metrics（builder 计算，不入库）

inventory_support_hours = current_stock/hourly_consumption；arrival_delay_hours = estimated−planned；safety_stock_gap = max(safety_stock−current_stock, 0)。

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

### 表清单（7 张，字段对齐 enterprise demo schema 子集，erp_sync 可直落）

1. **materials**：id、tenant_id、material_id（租户内唯一）、material_name、category、unit、daily_consumption、unit_cost、is_critical、created/updated
2. **suppliers**：id、tenant_id、supplier_id、supplier_name、region、status、reliability_score
3. **supplier_materials**：id、tenant_id、supplier_id、material_id、qualified（bool）、supplier_rank、available_emergency_qty、lead_time_hours、emergency_cost_multiplier、supplier_price（前端"采购价"列）——**字段名与 enterprise demo schema 一致，ScenarioLoader/erp_sync 零改造直落**
4. **customers**：id、tenant_id、customer_id、customer_name、customer_level（A/B/C）、region、contract（合同编号，前端列）、owner（负责人，前端列）
5. **sales_orders**：id、tenant_id、sales_order_id、customer_id、order_status、promised_date
6. **sales_order_lines**：id、tenant_id、sales_order_id、material_id、ordered_qty、unit_price、gross_profit、penalty_cost
7. **inventory**：id、tenant_id、material_id、warehouse_name、on_hand_qty、safety_stock_qty、in_transit_qty

全部带 tenant_id 索引 + (tenant_id, 业务主键) 唯一约束 + ForeignKey 声明（吸取 seed 顺序教训，UOW 排序可依赖）。

### 数据流三合一

- 导入向导（csv/xlsx/归一化后的 pdf/图片）→ preflight → execute 落上述实体表（替换现落 data_records 的路径）；签名重复闸门（D04）在 execute 前查 signature_history。
- ERP 同步（erp_sync.py）→ 同一批表；映射配置文件 `config/erp_mapping.yaml`（模板随交付）。
- 前端五个资料页 `GET/POST /data/{type}` 改读写实体表；物流页维持 mock。

### data_records 存量迁移

Alembic data migration：按 resource_type 分流（material/supplier/customer/order/inventory），payload 字段按映射表尽力搬运（映射表随迁移脚本交付），搬不动的字段进各表 `extra` JSON 列；迁移后 data_records 保留只读（审计留存），API 停写。回滚路径：downgrade 只删新表不动 data_records。

---

## ③ 租户隔离设计

1. **tenant_configs 表**：tenant_id、config_type（thresholds/risk_weights/transport_options/calibration_state）、payload JSON、version、source（expert/calibrated）、approved_by、approved_at。引擎侧：webapi 读该表组装后以参数传入（load_thresholds 保持全局默认作 fallback，引擎内部不感知租户）。
2. **校准状态机（量化）**：新租户 source=expert（全局默认）。已完结决策（审批通过且事件 closed、结果字段完整）计为 1 个样本；租户样本量 ≥ 5（引擎 `weight_manager.MIN_SAMPLES=5`，沿用不另设）时治理面板解锁"计算校准值"→ 对比展示（数据驱动值 vs 专家默认值、样本量、每参数偏离幅度）→ 人工放行（approved_by 落库）→ source=calibrated。面板须明示："样本 <30 时校准值统计置信有限，建议观察模式"（观察模式=展示对比但继续用 expert 值）。漂移检测（drift_monitor）按租户跑，漂移超过引擎既有阈值时经 D3 通知 admin/scm_lead，并在面板标红待复核。
3. **经验卡**：已有 experience_cards 表（tenant_id 具备）；作业完成写卡带 tenant_id；检索侧 TfidfStore 按租户构建内存索引，键=tenant_id，写卡时失效重建；**测试必须包含跨租户检索隔离断言**（A 租户经验绝不出现在 B 租户推荐里——商业机密级）。
4. **引擎文件态**：data/*.jsonl 审计已由 5A-3 入库；experience_cards.json 仅供 Streamlit 演示路径保留，Web 路径全走 DB。

---

## ④ 基准压测方案

**关键结论先行**：context builder 在 SQL 层聚合（对齐 ScenarioLoader），引擎输入规模 = O(该物料的供应商数+订单数)，与库存总行数解耦——预期瓶颈在 SQL 聚合与实体表索引，而非引擎计算。压测用于证实并给出容量口径，而非探索。

- 数据集（2026-07-12 更新，产品负责人确认）：**首选既有 11 万条企业演示数据**（demo_assets/enterprise 全套 ERP 账，经 erp_sync 或 CSV 导入管线灌入一个演示租户）——同时充当 5B 端到端验收数据集与压测基线；规模不足档位（5 万行 inventory 档）再用 generate_enterprise_demo_data 扩参补造。**"11 万条数据完整灌入演示租户且前端各资料页/风险/决策链路可见可用"本身即 5B 验收场景的第一步。**
- 测项：①build_incident_context 耗时；②run_scenario 全链路（含约束求解/博弈 27 组合/敏感性）p50/p95；③4 并发决策作业下的 p95 与内存峰值（对应线程池容量）；④实体表导入 5 万行的 execute 耗时。
- 门槛：单次决策 p95 ≤ 30s（60s 超时留一倍余量）；4 并发不 OOM（api 容器 2G 限额内）；超标时优先优化 SQL 索引与聚合，其次才考虑调超时/容量文档。
- 产出物：`benchmarks/bench_5b_context.py` + 结果表写入 phase5b 交付材料；容量口径更新 deploy_guide。

---

## 业务决策确认记录（2026-07-12，产品负责人拍板，四件套定稿）

1. **估算系数=按客户级**：违约金 = 订单额 ×（A 20% / B 10% / C 5%），毛利 = 订单额 ×（A 25% / B 20% / C 15%）；系数存 tenant_configs（config_type=estimation_coefficients）租户可调；所有估算值标 estimated。
2. **预计延误**：高风险事件创建/升级时**必填**（表单校验 + builder CG-2514 双层兜底）；中低风险选填，缺省 24h 标 estimated。
3. **经验卡绝对隔离**：无任何跨租户共享机制，测试断言锁死。
4. **压测口径**：1 万/5 万行两档，p95 ≤ 30s，4 并发 2G 内不 OOM。

以上四项 + 两轮机器验证（黄金参照字段核对、前端列覆盖核对）完成，**四件套定稿，5B 具备开工条件**（待 5A 交付评审通过后启动）。

## 前置产出验收与移交

本四件套经用户确认后，5B 可动工。移交给实现方时的开工顺序：先建 7 表迁移与 context_builder（对照①②节逐字段实现）→ 压测脚本跑基线 → 再进入 10 号总规格 5B 节的实施顺序。①节 schema 若与引擎实测行为有出入，以引擎现状为准并回改本文（契约文档必须与代码同步）。
