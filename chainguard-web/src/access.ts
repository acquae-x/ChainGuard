// 前端权限出口（对应 Phase 2 §2.3 + codex_frontend_spec/02 能力矩阵）。
// 唯一数据来源：后端 /auth/me 返回的 currentUser.permissions（权限码）。
// 本文件不得出现 role === 'xxx' 的硬编码角色判断——菜单/按钮/字段一律消费权限码。
const has = (permissions: string[], code: string) => permissions.includes(code);
const any = (permissions: string[], codes: string[]) => codes.some((code) => permissions.includes(code));

// 各能力对应的权限码集合（与后端 seed.py ROLE_PERMISSIONS 对齐）
const DECISION_VIEW = ['decision:view', 'decision:view:purchase', 'decision:view:sales', 'decision:view:finance', 'decision:view:production'];
const DECISION_MODIFY = ['decision:modify', 'decision:modify:purchase', 'decision:modify:production'];
const RISK_MANAGE = ['risk:manage', 'risk:manage:own', 'risk:manage:warehouse', 'risk:manage:order', 'risk:manage:material'];
const DATA_ACCESS = ['data:manage', 'data:view', 'data:supplier:manage', 'data:inventory:manage', 'data:customer:manage', 'data:order:manage', 'data:material:manage', 'data:import', 'data:import:own', 'data:import:inventory', 'data:import:order', 'data:import:material'];
const DATA_IMPORT = ['data:import', 'data:import:own', 'data:import:inventory', 'data:import:order', 'data:import:material'];
const REPORT_VIEW = ['report:executive', 'report:operation', 'report:purchase', 'report:order', 'report:cost', 'report:planner', 'report:view'];
const TASK_ANY = ['task:view', 'task:execute', 'task:manage'];

export default function access(initialState: { currentUser?: API.User } | undefined) {
  const user = initialState?.currentUser;
  const permissions = user?.permissions || [];
  const readonly = has(permissions, 'readonly');

  const canApproveLow = has(permissions, 'approval:low');
  const canApproveMedium = has(permissions, 'approval:medium');
  const canApproveHigh = has(permissions, 'approval:high');
  const canSubmitHigh = has(permissions, 'approval:submit_high');
  const canCountersign = has(permissions, 'approval:countersign');

  return {
    canDashboard: has(permissions, 'dashboard:view'),
    canRisk: has(permissions, 'risk:view'),
    canManageRisk: any(permissions, RISK_MANAGE) && !readonly,
    canIncident: has(permissions, 'incident:view'),
    canCreateIncident: has(permissions, 'risk:event:create'),
    canManageIncident: has(permissions, 'risk:event:create') && !readonly,
    canDecision: any(permissions, DECISION_VIEW),
    canModifyDecision: any(permissions, DECISION_MODIFY) && !readonly,
    canApproval: canApproveLow || canApproveMedium || canApproveHigh || canSubmitHigh || canCountersign,
    canApproveLow,
    canApproveMedium,
    canApproveHigh,
    canSubmitHigh,
    canCountersign,
    canTask: any(permissions, TASK_ANY),
    canTaskWrite: has(permissions, 'task:execute') && !readonly,
    canTaskManage: has(permissions, 'task:manage') && !readonly,
    canData: any(permissions, DATA_ACCESS),
    canDataMaterial: any(permissions, ['data:manage', 'data:material:manage', 'data:view']),
    canDataSupplier: any(permissions, ['data:manage', 'data:supplier:manage', 'data:view']),
    canDataCustomer: any(permissions, ['data:manage', 'data:customer:manage', 'data:view']),
    canDataOrder: any(permissions, ['data:manage', 'data:order:manage', 'data:view']),
    canDataInventory: any(permissions, ['data:manage', 'data:inventory:manage', 'data:view']),
    canImport: any(permissions, DATA_IMPORT) && !readonly,
    // 数据导出与审计导出分开控制：auditor 仅可导出审计日志（02 文档能力矩阵「导出数据 auditor=✅(审计)」）
    canExport: any(permissions, ['data:export', 'audit:export']),
    canExportData: has(permissions, 'data:export'),
    canExportAudit: has(permissions, 'audit:export'),
    canCase: has(permissions, 'case:view'),
    canReport: any(permissions, REPORT_VIEW),
    // 三张报表各有独立后端权限（report:executive / report:operation / report:view），
    // 菜单必须逐页收敛，否则用户会看到点进去就 403 的入口。settings:manage 在后端可越权查看，这里对齐。
    canReportExecutive: any(permissions, ['report:executive', 'settings:manage']),
    canReportOperation: any(permissions, ['report:operation', 'settings:manage']),
    canReportResponse: any(permissions, REPORT_VIEW),
    // 系统设置菜单：具备系统配置 / 审批流配置 / 审计查看任一即可见
    canSettings: any(permissions, ['settings:manage', 'settings:approval', 'audit:view']),
    canSettingsAdmin: has(permissions, 'settings:manage'),
    canApprovalConfig: any(permissions, ['settings:manage', 'settings:approval']),
    canAudit: has(permissions, 'audit:view'),
    readonly,
    isAdmin: has(permissions, 'settings:manage') && has(permissions, 'user:manage'),
  };
}
