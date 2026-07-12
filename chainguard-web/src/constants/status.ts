export type RiskLevel = 'high' | 'medium' | 'low';

export const RISK_LEVEL_META: Record<RiskLevel, { text: string; color: string; marker: string; score: string }> = {
  high: { text: '高风险', color: 'red', marker: '▲', score: '高 ▲' },
  medium: { text: '中风险', color: 'orange', marker: '●', score: '中 ●' },
  low: { text: '低风险', color: 'blue', marker: '▼', score: '低 ▼' }
};

export const STATUS_META: Record<string, { text: string; color: string }> = {
  new: { text: '新发现', color: 'red' },
  watching: { text: '观察中', color: 'blue' },
  incident_created: { text: '已建事件', color: 'orange' },
  resolved: { text: '已消除', color: 'green' },
  ignored: { text: '已忽略', color: 'default' },
  evaluating: { text: '评估中', color: 'blue' },
  planning: { text: '方案中', color: 'purple' },
  approving: { text: '审批中', color: 'orange' },
  executing: { text: '执行中', color: 'cyan' },
  reviewing: { text: '复盘中', color: 'purple' },
  closed: { text: '已关闭', color: 'green' },
  approved: { text: '已批准', color: 'green' },
  rejected: { text: '已驳回', color: 'red' },
  recalc_requested: { text: '待重算', color: 'orange' },
  transferred: { text: '已转交', color: 'blue' },
  withdrawn: { text: '已撤回', color: 'default' },
  draft: { text: '草稿', color: 'default' },
  pending: { text: '待处理', color: 'orange' },
  done: { text: '已完成', color: 'green' },
  overdue: { text: '已超时', color: 'red' },
  disabled: { text: '已停用', color: 'default' },
  active: { text: '启用', color: 'green' },
  invited: { text: '已邀请', color: 'blue' }
};

export const SENSITIVE_FIELDS = ['cost', 'profit', 'contract', 'customerLevel', 'supplierPrice'] as const;

export type SensitiveFieldCode = (typeof SENSITIVE_FIELDS)[number];

export const ROLE_LABELS: Record<string, string> = {
  admin: '企业管理员',
  boss: '老板/总经理',
  scm_lead: '供应链负责人',
  buyer: '采购人员',
  warehouse: '仓库人员',
  sales: '销售/客服',
  finance: '财务人员',
  planner: '生产计划人员',
  auditor: '只读审计'
};
