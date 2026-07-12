export type DashboardSection = 'riskList' | 'supplierAlerts' | 'taskList' | 'supplierRisk' | 'inventoryRisk' | 'orderRisk' | 'customerTasks' | 'approvalList' | 'costTrend' | 'materialRisk' | 'onboarding' | 'auditFeed' | 'riskDistribution' | 'highRiskTop5' | 'responseTrend';
export type DashboardKpi = { key: string; title: string; value: number | string; trend: string; sensitive?: 'cost' | 'profit' };
export type DashboardConfig = { kpis: DashboardKpi[]; second: DashboardSection[]; third: DashboardSection[]; readonly?: boolean };

const scmLead: DashboardConfig = {
  kpis: [{ key: 'risk', title: '活跃风险', value: 8, trend: '较昨日 +1' }, { key: 'approval', title: '待审批', value: 1, trend: '较昨日 +1' }, { key: 'incident', title: '进行中事件', value: 1, trend: '较昨日 +1' }, { key: 'overdue', title: '超时任务', value: 0, trend: '较昨日持平' }],
  second: ['riskList'], third: ['supplierAlerts']
};

export const dashboardConfig: Record<API.RoleCode, DashboardConfig> = {
  boss: { kpis: [{ key: 'high', title: '今日高风险事件数', value: 1, trend: '较昨日持平' }, { key: 'approval', title: '待我审批', value: 1, trend: '等待 1.2 小时' }, { key: 'loss', title: '预计损失敞口', value: '¥860,000', trend: '高风险暴露', sensitive: 'cost' }, { key: 'saving', title: '应急节省累计', value: '¥732,000', trend: '本月累计', sensitive: 'profit' }], second: ['riskDistribution', 'highRiskTop5'], third: ['responseTrend'] },
  scm_lead: scmLead,
  buyer: { kpis: [{ key: 'mine', title: '我的任务', value: 8, trend: '待处理' }, { key: 'late', title: '逾期任务', value: 1, trend: '需优先处理' }, { key: 'supplier', title: '负责供应商异常数', value: 1, trend: '较昨日 +1' }, { key: 'arrival', title: '待到货延误', value: 0, trend: '较昨日持平' }], second: ['taskList'], third: ['supplierRisk'] },
  warehouse: { kpis: [{ key: 'sku', title: '本仓预警 SKU', value: 4, trend: '较昨日 +1' }, { key: 'transfer', title: '待执行调拨', value: 2, trend: '今日处理' }, { key: 'io', title: '今日出入库', value: 36, trend: '正常' }, { key: 'stocktake', title: '盘点差异', value: 1, trend: '待确认' }], second: ['inventoryRisk'], third: ['taskList'] },
  sales: { kpis: [{ key: 'order', title: '受影响订单', value: 3, trend: '高等级客户 1 个' }, { key: 'customer', title: '待沟通客户', value: 2, trend: '今日完成' }, { key: 'vip', title: '高等级客户风险', value: 1, trend: '需主动沟通' }, { key: 'task', title: '我的任务', value: 2, trend: '待处理' }], second: ['orderRisk'], third: ['customerTasks'] },
  finance: { kpis: [{ key: 'countersign', title: '待会签', value: 1, trend: '高风险并行会签' }, { key: 'cost', title: '本月应急成本', value: '¥128,000', trend: '低于预算', sensitive: 'cost' }, { key: 'saving', title: '成本节省', value: '¥732,000', trend: '本月累计', sensitive: 'profit' }, { key: 'budget', title: '超预算方案数', value: 0, trend: '较昨日持平' }], second: ['approvalList'], third: ['costTrend'] },
  planner: { kpis: [{ key: 'gap', title: '物料缺口 SKU', value: 1, trend: 'MCU-A9' }, { key: 'work', title: '受影响工单', value: 2, trend: '需调整' }, { key: 'plan', title: '待调整计划', value: 1, trend: '今日完成' }, { key: 'task', title: '我的任务', value: 2, trend: '待处理' }], second: ['materialRisk'], third: ['taskList'] },
  admin: { kpis: [{ key: 'member', title: '成员数', value: 9, trend: '演示租户' }, { key: 'onboarding', title: '未完成初始化项', value: 2, trend: '待完善' }, { key: 'import', title: '本周导入批次', value: 3, trend: '含示例数据' }, { key: 'failed', title: '失败任务', value: 0, trend: '较昨日持平' }], second: ['onboarding'], third: ['auditFeed'] },
  auditor: { ...scmLead, readonly: true }
};
