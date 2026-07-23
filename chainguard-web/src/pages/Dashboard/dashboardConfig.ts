export type DashboardSection = 'riskList' | 'supplierAlerts' | 'taskList' | 'supplierRisk' | 'inventoryRisk' | 'orderRisk' | 'customerTasks' | 'approvalList' | 'costTrend' | 'materialRisk' | 'onboarding' | 'auditFeed' | 'riskDistribution' | 'highRiskTop5' | 'responseTrend' | 'nodeHealth' | 'myNodes';
export type DashboardKpi = { key: string; title: string; value: number | string; trend: string; sensitive?: 'cost' | 'profit' };
export type DashboardConfig = { kpis: DashboardKpi[]; second: DashboardSection[]; third: DashboardSection[]; readonly?: boolean };

// C02/C03：一线四角色原先各有一个写死的节点类 KPI（负责供应商异常数 1 / 本仓预警 SKU 4 /
// 受影响订单 3 / 物料缺口 SKU 1）。它们是**伪造的节点结论**——没有任何真实数据来源，
// 也不在 Dashboard 的 KPI_SOURCE 真值映射内，因此永远显示演示字面量。
// 这里整体删除，节点计数改由 `myNodes` / `nodeHealth` 面板按后端真实计算结果给出。

const scmLead: DashboardConfig = {
  kpis: [{ key: 'risk', title: '活跃风险', value: 8, trend: '较昨日 +1' }, { key: 'approval', title: '待审批', value: 1, trend: '较昨日 +1' }, { key: 'incident', title: '进行中事件', value: 1, trend: '较昨日 +1' }, { key: 'overdue', title: '超时任务', value: 0, trend: '较昨日持平' }],
  second: ['riskList'], third: ['nodeHealth', 'supplierAlerts']
};

export const dashboardConfig: Record<API.RoleCode, DashboardConfig> = {
  // 金额沿用经营看板口径（避免损失 = Σ incident.loss，净收益 = 避免损失 − 应急成本），
  // 不再用 ¥860,000 / ¥732,000 这类演示字面量。
  boss: { kpis: [{ key: 'high', title: '高风险数', value: 0, trend: '当前可见范围' }, { key: 'approval', title: '待我审批', value: 0, trend: '待处理审批单' }, { key: 'loss', title: '避免损失', value: 0, trend: '累计事件损失口径', sensitive: 'cost' }, { key: 'saving', title: '净收益', value: 0, trend: '避免损失 − 应急成本', sensitive: 'profit' }], second: ['riskDistribution', 'highRiskTop5'], third: ['nodeHealth', 'responseTrend'] },
  scm_lead: scmLead,
  buyer: { kpis: [{ key: 'mine', title: '我的任务', value: 0, trend: '待处理' }, { key: 'late', title: '逾期任务', value: 0, trend: '需优先处理' }, { key: 'arrival', title: '待到货延误', value: 0, trend: '预计到货晚于计划' }], second: ['myNodes'], third: ['taskList', 'supplierRisk'] },
  // 仓库/销售/计划三个角色原先的 KPI（待执行调拨 2 / 今日出入库 36 / 盘点差异 1 /
  // 待沟通客户 2 / 高等级客户风险 1 / 受影响工单 2 / 待调整计划 1）在系统里没有任何
  // 对应实体表——没有调拨单、出入库流水、盘点、工单、生产计划。它们和被删掉的四个
  // 节点类 KPI 是同一类伪造结论，这里一并换成真实且受行级数据范围约束的字段。
  warehouse: { kpis: [{ key: 'mine', title: '我的任务', value: 0, trend: '待处理' }, { key: 'late', title: '逾期任务', value: 0, trend: '需优先处理' }, { key: 'risk', title: '可见风险数', value: 0, trend: '按我的数据范围' }], second: ['myNodes'], third: ['inventoryRisk', 'taskList'] },
  sales: { kpis: [{ key: 'task', title: '我的任务', value: 0, trend: '待处理' }, { key: 'late', title: '逾期任务', value: 0, trend: '需优先处理' }, { key: 'risk', title: '可见风险数', value: 0, trend: '按我的数据范围' }], second: ['myNodes'], third: ['orderRisk', 'customerTasks'] },
  finance: { kpis: [{ key: 'countersign', title: '待会签', value: 0, trend: '高风险并行会签' }, { key: 'cost', title: '应急成本', value: 0, trend: '累计事件成本口径', sensitive: 'cost' }, { key: 'saving', title: '净收益', value: 0, trend: '避免损失 − 应急成本', sensitive: 'profit' }], second: ['approvalList'], third: ['costTrend'] },
  planner: { kpis: [{ key: 'task', title: '我的任务', value: 0, trend: '待处理' }, { key: 'late', title: '逾期任务', value: 0, trend: '需优先处理' }, { key: 'risk', title: '可见风险数', value: 0, trend: '按我的数据范围' }], second: ['myNodes'], third: ['materialRisk', 'taskList'] },
  // 这四项全部来自 /dashboard/kpis 的真实计算（见 index.tsx 的 KPI_SOURCE）。
  // 原先写死的 9 / 2 / 3 / 0 既不随租户变化，也和 /onboarding/status 的结论互相矛盾。
  admin: { kpis: [{ key: 'member', title: '成员数', value: 0, trend: '本租户全部账号' }, { key: 'onboarding', title: '未完成初始化项', value: 0, trend: '决策必需但未导入的资料类型' }, { key: 'import', title: '本周导入批次', value: 0, trend: '近 7 天' }, { key: 'failed', title: '失败导入批次', value: 0, trend: '全部历史批次' }], second: ['onboarding'], third: ['nodeHealth', 'auditFeed'] },
  auditor: { ...scmLead, readonly: true }
};
