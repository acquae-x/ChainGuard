import type { RiskLevel } from '@/constants/status';

export const roleNames: Record<API.RoleCode, string> = {
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

const basePermissions = ['dashboard:view', 'risk:view', 'incident:view'];
const permissionMap: Record<API.RoleCode, string[]> = {
  admin: ['settings:manage', 'data:manage', 'data:import', 'data:export', 'audit:view', 'user:manage', 'role:manage'],
  boss: ['risk:event:create', 'decision:view', 'approval:low', 'approval:medium', 'approval:high', 'task:view', 'case:view', 'report:executive', 'field:cost:view', 'field:profit:view', 'field:contract:view', 'field:customerLevel:view', 'field:supplierPrice:view', 'data:export', 'audit:view'],
  scm_lead: ['risk:event:create', 'risk:manage', 'decision:view', 'decision:modify', 'approval:low', 'approval:medium', 'approval:submit_high', 'task:execute', 'data:manage', 'data:import', 'data:export', 'case:view', 'report:operation', 'settings:approval', 'field:cost:view', 'field:profit:view', 'field:contract:view', 'field:customerLevel:view', 'field:supplierPrice:view'],
  buyer: ['risk:event:create', 'risk:manage:own', 'decision:view:purchase', 'decision:modify:purchase', 'task:execute', 'data:supplier:manage', 'data:import:own', 'case:view', 'report:purchase'],
  warehouse: ['risk:event:create', 'risk:manage:warehouse', 'task:execute', 'data:inventory:manage', 'data:import:inventory'],
  sales: ['risk:event:create', 'risk:manage:order', 'decision:view:sales', 'task:execute', 'data:customer:manage', 'data:order:manage', 'data:import:order', 'case:view', 'report:order', 'field:customerLevel:view', 'field:contract:view'],
  finance: ['decision:view:finance', 'approval:countersign', 'task:execute', 'report:cost', 'field:cost:view', 'field:profit:view', 'field:customerLevel:view', 'field:contract:view', 'data:export'],
  planner: ['risk:event:create', 'risk:manage:material', 'decision:view:production', 'decision:modify:production', 'task:execute', 'data:material:manage', 'data:import:material', 'case:view', 'report:planner'],
  auditor: ['readonly', 'decision:view', 'task:view', 'case:view', 'report:view', 'audit:view', 'audit:export', 'data:view']
};

export const tenant: API.Tenant = {
  id: 'tenant-demo',
  name: '华东精密制造有限公司',
  industry: '电子制造',
  scale: '200-1000',
  status: 'active',
  plan: 'trial',
  trialEndAt: '2026-08-08',
  demoDataFlag: true
};

export const roles: API.Role[] = (Object.keys(roleNames) as API.RoleCode[]).map((code) => ({
  id: `role-${code}`,
  tenantId: tenant.id,
  code,
  name: roleNames[code],
  builtin: true,
  permissions: [...basePermissions, ...permissionMap[code]]
}));

export const departments: API.Department[] = ['采购部', '仓储部', '销售部', '财务部', '生产部'].map((name, index) => ({
  id: `dept-${index + 1}`,
  tenantId: tenant.id,
  name
}));

export const users: API.User[] = (Object.keys(roleNames) as API.RoleCode[]).map((code, index) => ({
  id: `u-${code}`,
  tenantId: tenant.id,
  name: roleNames[code],
  phone: `1380000000${index + 1}`,
  email: `${code}@chainguard.demo`,
  deptId: departments[index % departments.length].id,
  roleIds: [`role-${code}`],
  roleCode: code,
  status: 'active',
  dataScope: ['admin', 'boss', 'scm_lead', 'finance', 'auditor'].includes(code) ? 'all' : 'custom',
  readonly: code === 'auditor',
  permissions: roles.find((item) => item.code === code)?.permissions || []
}));

export const risks: API.Risk[] = [
  { id: 'risk-1', code: 'RISK-20260709-001', level: 'high', type: '供应', objectType: '供应商', objectName: '苏州芯片封测厂', score: 92, rule: '核心供应商停产', foundAt: '2026-07-09 09:12', status: 'new', supplier: '苏州芯片封测厂', material: 'MCU-A9' },
  { id: 'risk-2', code: 'RISK-20260709-002', level: 'medium', type: '库存', objectType: '物料', objectName: 'MCU-A9', score: 73, rule: '安全库存低于 20%', foundAt: '2026-07-09 10:21', status: 'watching', warehouse: '上海一仓', material: 'MCU-A9' },
  { id: 'risk-3', code: 'RISK-20260709-003', level: 'medium', type: '需求', objectType: '订单', objectName: 'SO-88019', score: 68, rule: '高等级客户交期临近', foundAt: '2026-07-09 11:04', status: 'incident_created', orderNo: 'SO-88019', incidentId: 'inc-supplier-shutdown' },
  { id: 'risk-4', code: 'RISK-20260709-004', level: 'low', type: '物流', objectType: '物流', objectName: '沪深干线', score: 42, rule: '预计延误 1 天', foundAt: '2026-07-08 15:30', status: 'resolved' }
];

export const incident: API.Incident = {
  id: 'inc-supplier-shutdown',
  code: 'INC-20260709-001',
  title: '苏州芯片封测厂突发停产影响 MCU-A9 供应',
  type: 'supplier_shutdown',
  level: 'high',
  status: 'approving',
  owner: '供应链负责人',
  createdAt: '2026-07-09 09:30',
  sourceRiskIds: ['risk-1', 'risk-2'],
  loss: 860000,
  cost: 128000
};

export const proposals: API.Proposal[] = [
  { id: 'prop-1', incidentId: incident.id, name: '双供应商加急补货', tag: 'recommended', totalCost: 128000, leadTimeImpact: 2, residualRisk: 'low', customerImpact: 3, highValueCustomers: 1, reason: '总成本可控，交期影响最小，历史案例 EXP-019 支持该组合。', views: { 采购: '向宁波备选供应商追加 60%，原供应商保留 40%。', 物流: '关键批次改走空运加急。', 财务: '成本增加 12.8 万，低于会签阈值上浮线。', 销售: '仅 3 个订单需主动沟通。', 生产: 'A 线切换安全库存优先。' } },
  { id: 'prop-2', incidentId: incident.id, name: '全量替代供应商切换', tag: 'alternative', totalCost: 196000, leadTimeImpact: 1, residualRisk: 'medium', customerImpact: 2, highValueCustomers: 1, reason: '交期最短，但供应商质量验证不足，剩余风险偏高。', views: { 采购: '全量切给宁波供应商。', 物流: '一次性空运。', 财务: '成本增加 19.6 万。', 销售: '重点客户交期可守住。', 生产: '需安排额外质检窗口。' } },
  { id: 'prop-3', incidentId: incident.id, name: '等待原供应商恢复', tag: 'invalid', totalCost: 32000, leadTimeImpact: 7, residualRisk: 'high', customerImpact: 11, highValueCustomers: 4, reason: '违反高等级客户最长延误 3 天约束，不建议执行。', views: { 采购: '不新增采购。', 物流: '保持原路线。', 财务: '短期现金支出低。', 销售: '客户违约风险高。', 生产: 'B 线停线概率高。' } }
];

export const approvals: API.Approval[] = [
  { id: 'ap-1', proposalId: 'prop-1', incidentId: incident.id, status: 'pending', riskLevel: 'high', summary: '双供应商加急补货，预计延误 2 天', costImpact: 128000, submitter: '供应链负责人', waitingHours: 1.2 }
];

export const tasks: API.Task[] = [
  { id: 'task-1', title: '确认宁波备选供应商 60% 产能', source: incident.code, incidentId: incident.id, assignee: '采购人员', roleCode: 'buyer', status: 'pending', dueAt: '2026-07-09 18:00', priority: '高', checklist: [{ text: '确认报价', done: true }, { text: '锁定交期', done: false }] },
  { id: 'task-2', title: '安排首批物料空运', source: incident.code, incidentId: incident.id, assignee: '供应链负责人', roleCode: 'scm_lead', status: 'executing', dueAt: '2026-07-10 10:00', priority: '高', checklist: [{ text: '确认航班', done: false }] },
  { id: 'task-3', title: '通知高等级客户交期变更', source: incident.code, incidentId: incident.id, assignee: '销售/客服', roleCode: 'sales', status: 'pending', dueAt: '2026-07-09 20:00', priority: '中', checklist: [{ text: '发送沟通邮件', done: false }] }
];

export const auditLogs: API.AuditLog[] = [
  { id: 'audit-1', time: '2026-07-09 09:12', userId: 'system', userName: '系统', roleCode: 'admin', action: '发现风险', targetType: 'risk', targetId: 'risk-1', targetName: '苏州芯片封测厂停产', detail: { level: 'high' }, ip: '127.0.0.1' },
  { id: 'audit-2', time: '2026-07-09 09:30', userId: 'u-scm_lead', userName: '供应链负责人', roleCode: 'scm_lead', action: '创建事件', targetType: 'incident', targetId: incident.id, targetName: incident.title, detail: { from: 'risk-1,risk-2' }, ip: '10.0.0.12' },
  { id: 'audit-3', time: '2026-07-09 09:36', userId: 'u-scm_lead', userName: '供应链负责人', roleCode: 'scm_lead', action: '生成方案', targetType: 'proposal', targetId: 'prop-1', targetName: '双供应商加急补货', detail: { count: 3 }, ip: '10.0.0.12' }
];

export const materials = [
  { id: 'mat-1', name: 'MCU-A9', category: '芯片', stock: 1200, safety: 3000, cost: 18.5 },
  { id: 'mat-2', name: 'PCB-X2', category: '板材', stock: 8600, safety: 4000, cost: 6.2 }
];

export const suppliers = [
  { id: 'sup-1', name: '苏州芯片封测厂', status: '停产', leadTime: 8, supplierPrice: 18.5 },
  { id: 'sup-2', name: '宁波微电科技', status: '可替代', leadTime: 3, supplierPrice: 21.2 }
];

export const customers = [
  { id: 'cus-1', name: '长三角机器人集团', customerLevel: 'A', contract: '年度框架合同', owner: '销售/客服' }
];

export const orders = [
  { id: 'ord-1', orderNo: 'SO-88019', customer: '长三角机器人集团', dueAt: '2026-07-13', amount: 420000, profit: 76000, status: 'pending' }
];

export const inventories = [
  { id: 'inv-1', warehouse: '上海一仓', material: 'MCU-A9', quantity: 1200, supportHours: 36, status: 'new' }
];

export const toRiskLevel = (level: string): RiskLevel => (['high', 'medium', 'low'].includes(level) ? (level as RiskLevel) : 'low');
