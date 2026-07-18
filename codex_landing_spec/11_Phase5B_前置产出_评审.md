# Phase 5B 前置产出 v1 规格评审

评审日期：2026-07-17。范围仅为 `11_Phase5B_前置产出.md` 的前置规格；未创建迁移、实体表、context builder 或其他 5B 实现。

## 结论

**暂不通过。** 文档方向符合 `10_Phase5_总规格.md` 的四项前置产出，但有阻断性的契约来源和字段定义歧义。修订为 v2 并完成下面的机器核对后，才可签发此闸门。

| 优先级 | 问题 | 磁盘核验 | 必须修订 |
|---|---|---|---|
| P0 | 运输方式枚举不一致 | v1 写 `air/road/rail/sea`；黄金参照 `src/scenario_loader.py` 使用 `air/truck/rail/sea`，且路线阻断判断明确匹配 `truck` | 明确 canonical code 为 `truck`，或规定 builder 在边界处把 `road` 映射为 `truck`；不得改变引擎内部枚举 |
| P0 | “复用 erp_sync.py”的映射来源不精确 | 存在 `scripts/erp_sync.py`，但它只通过 `RestErpConnector` 拉取事件、运行决策并回写；其中没有表→实体映射。现有 CSV 导入路径另在 `src/enterprise_ingest.py`、`src/streaming_import.py` | 将“复用”改为确切模块与函数级映射来源，并列出输入表、目标实体表和拒绝未知列的策略；不能声称复用了脚本中不存在的映射 |
| P0 | Context 正式契约遗漏引擎实际消费的别名/字段 | `ScenarioLoader._load_orders()` 同时输出 `delivery_hours`/`due_hours` 与 `demand`/`demand_qty`；`game_model.py`、`agents.py` 优先读取前者。运输黄金参照还输出 `cost_multiplier` | v2 逐项定义 canonical 与兼容别名、写入方向和弃用规则；`transport_options` 补 `cost_multiplier`，防止真实成本评分悄然退化 |
| P0 | 七表清单与租户配置、既有经验卡迁移范围脱节 | v1 ③依赖 `tenant_configs`，但②的迁移清单只有七表；已有 `experience_cards` 已带 `tenant_id`，`data_records` 仍由现网 API 读写 | 明确首个 Alembic revision 包含的表、`tenant_configs` 的唯一约束/版本语义、`experience_cards` 的复用或迁移边界，以及切换期 API 的唯一读写源 |
| P1 | ERP 财务字段来源未对齐 | 企业 CSV 的 `gross_profit`/`penalty_cost` 位于 `sales_orders.csv`，而 v1 将两者列在 `sales_order_lines`；黄金参照也从 `sales_orders` 读取 | 修正实体字段归属，或明确行级分摊公式、精度和审计字段；不得把订单头金额复制到每一行 |
| P1 | “黄金参照”范围尚不精确 | `ScenarioLoader.load_context()` 不返回 `derived_metrics`，并把 `planned_arrival_hours` 固定为 0；v1 却将二者写为普遍入口契约 | 定义这些为新 builder 的派生输出，或补一层适配器；同时规定到货计划的真实来源、缺失时的降级标记和时区口径 |
| P1 | 迁移与隔离验收不可执行 | v1 未列出 composite FK/唯一约束、数据迁移幂等键、重跑策略，以及跨租户检索/读写/导入的最小断言集 | 为每张表列出主键、`(tenant_id, business_key)` 唯一约束、跨租户 FK 策略和 up/down 数据保留规则；补 11 万行映射核对、双租户负向测试与 1 万/5 万行压测命令/判定格式 |

## 已核对的可保留设计

- `hourly_consumption = daily_consumption / 24`、供应商按 `qualified=1` 与 `supplier_rank` 排序、可靠性缺失降为 `0`，均与 `ScenarioLoader` 行为一致。
- 高风险事件缺少延误应阻断、订单或供应商为空可降级，符合引擎现有的兜底行为，方向正确。
- `WeightManager.MIN_SAMPLES = 5`、经验卡按 `tenant_id` 隔离的目标，以及 1 万/5 万行、4 并发、2 GiB、p95 ≤ 30 秒的容量口径，均可作为 v2 基线保留。

## 评审闸门

5B 的第二道闸门当前为 **未通过**。完成上述 v2 修订并以实际机器输出验证字段映射和前端列覆盖后，才可重新评审；在此之前不得开始 C2 实体表第一批。

---

## 2026-07-17 v2 复审

评审对象已更新为 `11_Phase5B_前置产出.md` v2。以下结论覆盖上面的 v1 闸门状态，但保留 v1 记录用于追溯。

| v1 问题 | v2 关闭证据 |
|---|---|
| road/truck 枚举 | canonical code 固定为 `truck`，外部 `road` 只在适配边界转换；真实 ScenarioLoader 运行输出为 air/truck/rail/sea |
| erp_sync 映射来源 | 明确 `scripts/erp_sync.py` 仅负责编排，复用 RestErpConnector 规范化；CSV/ERP 共同消费单一 `config/erp_mapping.yaml` |
| Context 别名/字段遗漏 | orders 双写 delivery_hours/due_hours、demand/demand_qty；transport_options 补 cost_multiplier |
| 七表与 tenant_configs 脱节 | 固定为同一 revision 的 7 业务表 + tenant_configs 共 8 表；experience_cards 复用，data_records 只读迁移源 |
| 财务字段归属 | gross_profit/penalty_cost 移到 sales_orders 订单头，禁止按订单行重复累计 |
| derived_metrics/到货口径 | 标明 derived_metrics 为 Web builder 加法字段；到货字段由 shipments 聚合进 inventory，UTC 入库并有缺失降级 |
| 迁移/隔离/压测不可执行 | 补 tenant-aware FK、幂等/回滚测试、双租户负向断言、固定 benchmark 命令和 JSON 判定字段 |

### 实际机器核实

- 黄金参照：实际调用 ScenarioLoader 加载 `EVT-000128`，退出码 0；字段集合和兼容别名已逐项写入 v2。
- 产品界面：实际启动全新隔离库和真 API 模式前后端，以企业管理员登录，逐页核实物料/供应商/客户/订单/库存表头。五张截图保存在 `output/playwright/phase5b-spec-ui-20260717/`；页面为空数据态，不提前宣称 11 万行灌入已通过。

### 复审结论

**v2 规格评审通过，Phase 5B 第二道闸门关闭。** 5A Windows 验收此前也已关闭，因此项目现在具备开始 5B C2 第一批的条件；本次工作本身仍未创建任何 5B 实体、迁移或业务实现。
