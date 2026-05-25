# ChainGuard 企业真实数据导入 Schema 示例

本文件用于说明 ChainGuard 未来从企业 ERP/WMS/TMS 导入真实数据时，建议准备的核心数据表和字段。

初赛阶段，系统默认使用模拟数据和 Mock Agent，不接入真实 API，不读取真实企业系统。真实落地阶段，可将以下数据从 ERP、WMS、TMS、供应商协同平台、客户订单系统或历史应急台账中导出，再用于库存风险权重、预警阈值和评分模型校准。

当前系统已预留 `src/parameter_calibration.py`，用于后续承接企业历史数据拟合、参数回放和规则校准。

## 1. 库存数据 inventory

来源建议：WMS、ERP 库存模块。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| material_id | string | 物料或 SKU 编号 |
| material_name | string | 物料名称 |
| current_stock | number | 当前可用库存数量 |
| safety_stock | number | 安全库存数量 |
| hourly_consumption | number | 小时级平均消耗量 |
| warehouse_location | string | 仓库或库位 |
| updated_at | datetime | 库存快照更新时间 |

用途：

- 计算库存可支撑小时数。
- 判断安全库存缺口。
- 校准 `shortage_urgency` 和库存预警阈值。

## 2. 订单数据 orders

来源建议：ERP 销售订单、CRM、客户服务系统。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_id | string | 客户订单编号 |
| customer_id | string | 客户编号 |
| customer_priority | string | 客户优先级，例如 key_account、standard |
| material_id | string | 需求物料编号 |
| demand_qty | number | 订单需求数量 |
| due_time | datetime | 承诺交付时间 |
| penalty_cost | number | 延期罚金或违约成本 |
| gross_profit | number | 订单毛利 |
| service_level_agreement | string | 服务等级协议或履约承诺 |

用途：

- 识别关键客户和高价值订单。
- 计算订单交付紧迫度。
- 校准 `order_importance`、服务水平权重和延期损失模型。

## 3. 供应商数据 suppliers

来源建议：ERP 采购模块、SRM、供应商协同平台。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| supplier_id | string | 供应商编号 |
| supplier_name | string | 供应商名称 |
| material_id | string | 可供应物料编号 |
| lead_time_hours | number | 标准交付周期，单位小时 |
| available_qty | number | 当前可应急供应数量 |
| reliability_score | number | 历史可靠性评分，建议 0 到 100 |
| emergency_cost_multiplier | number | 应急采购成本倍率 |
| region | string | 供应商所在区域 |

用途：

- 评估备用供应商可行性。
- 估算应急采购成本与到货时间。
- 校准供应商可靠性、可行性评分和成本权重。

## 4. 在途物流数据 shipments

来源建议：TMS、承运商平台、物流跟踪系统。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| shipment_id | string | 在途运输单编号 |
| supplier_id | string | 对应供应商编号 |
| material_id | string | 运输物料编号 |
| qty | number | 在途数量 |
| planned_arrival_time | datetime | 原计划到达时间 |
| estimated_arrival_time | datetime | 当前预计到达时间 |
| transport_mode | string | 运输方式，例如 sea、air、truck、rail |
| route | string | 运输路线或关键节点 |
| current_status | string | 当前状态，例如 in_transit、delayed、blocked |

用途：

- 计算在途延误小时数。
- 判断替代运输路线是否必要。
- 校准 `transit_delay`、物流风险和时效评分。

## 5. 突发事件数据 disruption_events

来源建议：企业事件台账、TMS 异常事件、外部风险订阅数据导出。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| event_id | string | 事件编号 |
| event_type | string | 事件类型，例如 typhoon、port_shutdown、strike |
| location | string | 事件发生位置 |
| affected_supplier | string | 受影响供应商 |
| affected_route | string | 受影响路线 |
| delay_hours | number | 预计延误小时数 |
| external_risk_score | number | 外部风险评分，建议 0 到 100 |
| event_start_time | datetime | 事件开始时间 |
| description | string | 事件说明 |

用途：

- 识别外部事件对供应链节点的影响。
- 量化港口、区域、路线级风险。
- 校准 `external_event` 权重和事件触发阈值。

## 6. 历史应急结果 historical_decisions

来源建议：应急决策台账、复盘报告、订单履约结果、财务成本记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| case_id | string | 历史案例编号 |
| scenario | string | 场景描述 |
| selected_strategy | string | 当时选择的策略 |
| actual_delay_hours | number | 最终实际延期小时数 |
| actual_cost | number | 实际应急成本 |
| lost_orders | number | 丢失订单数量 |
| production_downtime_hours | number | 生产停线小时数 |
| customer_complaints | number | 客户投诉数量 |
| final_success_label | string | 最终结果标签，例如 success、partial_success、failed |

用途：

- 回放历史决策，评估方案评分模型是否合理。
- 识别低分但成功、高分但失败的异常案例。
- 校准决策评分权重、辩论触发条件和经验学习阈值。

## 校准方式说明

导入真实数据后，可以围绕以下目标进行参数校准：

- 库存风险权重：校准缺货紧迫性、订单重要性、在途延误、外部事件的相对影响。
- 预警阈值：按物料、客户等级、供应商可靠性调整黄灯/红灯阈值。
- 评分模型：基于历史应急结果调整时效、成本、风险降低、可行性和服务水平权重。
- 经验学习：将失败或低分案例沉淀为规则样本，用于后续 Agent 决策解释和仲裁优化。

## 当前阶段边界

- 初赛阶段使用模拟数据，不接企业真实系统。
- 当前配置参数是专家经验参数，不是真实企业历史数据拟合结果。
- `parameter_calibration.py` 是后续拟合入口，当前只保留接口和流程说明。
- 真正落地前需要完成数据脱敏、字段对齐、时间口径统一和历史案例标注。
