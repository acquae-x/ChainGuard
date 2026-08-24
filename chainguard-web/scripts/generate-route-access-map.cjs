const fs = require('fs');
const path = require('path');

const roles = ['admin', 'boss', 'scm_lead', 'buyer', 'warehouse', 'sales', 'finance', 'planner', 'auditor'];
const all = [...roles];
const decision = roles.filter((role) => role !== 'warehouse');
const task = roles.filter((role) => role !== 'admin');
const caseReport = roles.filter((role) => role !== 'warehouse');
const rows = [
  ['登录', '/user/login', '公开', all], ['注册', '/user/register', '公开', all], ['加入企业', '/user/join', '公开', all], ['找回密码', '/user/reset', '公开', all],
  ['初始化向导', '/onboarding', '登录用户', all], ['工作台', '/dashboard', '登录用户', all],
  ['风险总览', '/risk/overview', 'canRisk', all], ['风险列表', '/risk/list', 'canRisk', all], ['监控规则', '/risk/rules', 'canRisk', all],
  ['事件列表', '/incident/list', 'canIncident', all], ['我发起的事件', '/incident/mine', 'canIncident', all], ['事件详情', '/incident/:id', 'canIncident', all],
  ['方案生成/对比', '/decision/generate/:incidentId', 'canDecision', decision], ['方案列表', '/decision/list', 'canDecision', decision], ['审批中心', '/decision/approval', 'canDecision；按钮另校验 canApproval', decision],
  ['我的任务', '/task/mine', 'canTask', task], ['全部任务', '/task/all', 'canTask', task], ['超时看板', '/task/overdue', 'canTask', task],
  ['物料', '/data/material', 'canDataMaterial', ['admin', 'scm_lead', 'planner', 'auditor']], ['供应商', '/data/supplier', 'canDataSupplier', ['admin', 'scm_lead', 'buyer', 'auditor']],
  ['客户', '/data/customer', 'canDataCustomer', ['admin', 'scm_lead', 'sales', 'auditor']], ['订单', '/data/order', 'canDataOrder', ['admin', 'scm_lead', 'sales', 'auditor']],
  ['库存', '/data/inventory', 'canDataInventory', ['admin', 'scm_lead', 'warehouse', 'auditor']],
  ['数据导入', '/data/import', 'canData；写操作 canImport', ['admin', 'scm_lead', 'buyer', 'warehouse', 'sales', 'planner', 'auditor']],
  ['案例库', '/case/list', 'canCase', caseReport], ['经验卡片', '/case/experience', 'canCase', caseReport],
  ['经营看板', '/report/executive', 'canReport', caseReport], ['运营看板', '/report/operation', 'canReport', caseReport], ['应急效果', '/report/response', 'canReport', caseReport],
  ['企业信息', '/settings/tenant', 'canSettingsAdmin', ['admin']], ['用户管理', '/settings/users', 'canSettingsAdmin', ['admin']], ['角色权限', '/settings/roles', 'canSettingsAdmin', ['admin']], ['数据权限', '/settings/scopes', 'canSettingsAdmin', ['admin']],
  ['审批流', '/settings/approval', 'canApprovalConfig', ['admin', 'scm_lead']], ['风险阈值', '/settings/thresholds', 'canApprovalConfig', ['admin', 'scm_lead']], ['自定义字段', '/settings/fields', 'canSettingsAdmin', ['admin']],
  ['审计日志', '/settings/audit', 'canAudit', ['admin', 'boss', 'auditor']], ['向导重入', '/settings/onboarding', 'canSettingsAdmin', ['admin']], ['系统集成（P3 占位）', '/settings/integration', 'canSettingsAdmin', ['admin']],
  ['无权限', '/403', '公开结果页', all], ['服务异常', '/500', '公开结果页', all], ['页面不存在', '*', '公开结果页', all]
];

const yes = (allowed, role) => allowed.includes(role) ? '✅' : '—';
const header = ['页面', '路由', '访问控制', ...roles];
const lines = [
  '# ChainGuard 路由访问矩阵', '',
  '> 由 `scripts/generate-route-access-map.cjs` 生成。菜单级裁决遵循 03 文档，按钮、字段和只读限制由 `src/access.ts` 与 `SensitiveField` 二次控制。', '',
  `| ${header.join(' | ')} |`, `|${header.map(() => '---').join('|')}|`,
  ...rows.map(([name, route, access, allowed]) => `| ${name} | \`${route}\` | ${access} | ${roles.map((role) => yes(allowed, role)).join(' | ')} |`),
  '', '## 补充规则', '',
  '- `auditor` 对所有可达业务页只读，操作按钮由 `readonly` / `canTaskWrite` / `canModifyDecision` 隐藏。',
  '- `admin` 可配置租户、用户、角色和数据，但 `canApproval=false`，不出现审批按钮。',
  '- `buyer` 无 `field:cost:view`、`field:supplierPrice:view`，成本与供应商价格显示为 `***`。',
  '- 数据管理按二级对象权限裁剪；表中的 `✅` 表示该角色至少可访问该路由，导入写操作仍需 `canImport`。',
  '- 未授权路由由 React Router 权限守卫拦截到 403，隐藏路由（事件详情、方案生成）仍执行相同访问控制。', ''
];

const output = path.join(__dirname, '..', 'docs', 'route-access-map.md');
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, lines.join('\n'), 'utf8');
console.log(`generated ${output}`);
