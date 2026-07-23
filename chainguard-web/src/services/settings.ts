// 系统设置服务（Phase 2 §2.2 双模式）。api 模式对接 /settings/* 与 /audit-logs，mock 走内置数据。
import { auditLogs, departments, roles, tenant, users } from './mockData';
import { workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from '../utils/request';

export async function getUsers() {
  return pick(
    () => apiGet('/settings/users'),
    async () => ({ data: users, total: users.length, success: true }),
  );
}

export async function createUser(values: any) {
  return pick(
    () => apiPost('/settings/users', values),
    async () => ({ ok: true, values }),
  );
}

export async function resetUserPassword(id: string) {
  return pick(() => apiPost(`/settings/users/${id}/reset-password`, {}), async () => ({ ok: true, temporaryPassword: 'Cg!temporary-demo', mustChangePassword: true }));
}

export async function getRoles() {
  return pick(
    () => apiGet('/settings/roles'),
    async () => roles,
  );
}

export async function saveRole(values: any) {
  return pick(
    () => (values?.id ? apiPatch(`/settings/roles/${values.id}`, values) : apiPost('/settings/roles', values)),
    async () => ({ ok: true, values }),
  );
}

export async function getDepartments() {
  return pick(
    async () => {
      const res = await apiGet<any>('/settings/departments');
      return Array.isArray(res) ? res : res.data || [];
    },
    async () => departments,
  );
}

export async function getTenant() {
  return pick(
    () => apiGet('/settings/tenant'),
    async () => tenant,
  );
}

export async function getAuditLogs() {
  return pick(
    () => apiGet('/audit-logs'),
    async () => {
      const data = workflowStore.listAuditLogs();
      return { data, total: data.length, success: true };
    },
  );
}

export async function getFieldSchema(objectType: string) {
  return pick(
    () => apiGet('/settings/custom-fields', { objectType }),
    async () => [{ name: 'qualityScore', label: '质量评分', type: 'number', required: false, riskFactor: '供应稳定性', objectType }],
  );
}

export async function saveField(values: any) {
  return pick(
    () => apiPost('/settings/custom-fields', values),
    async () => ({ ok: true, values }),
  );
}

// 自定义字段停用：api 模式走 DELETE /settings/custom-fields/{id}（软停用），mock 返回本地。
export async function disableField(id: string) {
  return pick(
    () => apiDelete(`/settings/custom-fields/${id}`),
    async () => ({ ok: true, id }),
  );
}

// 校准治理：API 模式只消费后端既有校准/漂移引擎的编排结果；mock 保留可读样例。
export async function getCalibrationGovernance() {
  return pick(
    () => apiGet('/settings/calibration-governance'),
    async () => ({
      recommendationId: 'mock-calibration',
      sample: { totalRows: 0, effectiveRows: 0, timeRange: { from: null, to: null }, confidence: { level: 'insufficient', score: 20, note: '演示模式没有真实历史结果。' } },
      comparison: { expert: { thresholds: { inventory_warning: { yellow_support_hours: 48, red_support_hours: 24, inventory_risk_trigger: 70 } }, riskWeights: { shortage_urgency: 0.35, order_importance: 0.25, transit_delay: 0.2, external_event: 0.2 } }, suggested: { thresholds: { inventory_warning: { yellow_support_hours: 48, red_support_hours: 24, inventory_risk_trigger: 70 } }, riskWeights: { shortage_urgency: 0.35, order_importance: 0.25, transit_delay: 0.2, external_event: 0.2 } }, active: { approved: false } },
      calculation: { weightMethod: 'pearson_correlation', weightNote: '样本不足，返回专家默认权重。', trigger: { value: 70, _note: '样本不足，使用专家默认阈值。' }, summary: [], approvalGate: '演示建议不会影响决策。' },
      drift: { severity: 'ok', driftDetected: false, findings: ['暂无真实结果样本。'], notificationCount: 0, thresholds: { warn_drop: 0.05, critical_drop: 0.15 } },
    }),
  );
}

export async function confirmCalibrationGovernance(recommendationId: string) {
  return pick(
    () => apiPost('/settings/calibration-governance/confirm', { values: { recommendationId } }),
    async () => ({ ok: false }),
  );
}

export type ErpIntegrationConfig = {
  configured: boolean;
  baseUrl: string;
  credentialConfigured: boolean;
  credentialMasked?: string;
  /** 密文仍是旧密钥派生方案，重新保存一次凭证即可升级（后端 needs_rewrap）。 */
  credentialNeedsRewrap?: boolean;
  connectionParams: { timeoutSeconds?: number; pageSize?: number };
  lastTestStatus: 'not_tested' | 'available' | 'unavailable';
  lastTestAt?: string | null;
  lastTestError?: string | null;
  availableResources: Array<{ resource: string; recordCount: number }>;
};

/** 凭证静态加密的部署级状态。后端只回状态与派生方式，不含任何密钥材料。 */
export type EncryptionStatus = {
  library_available: boolean;
  key_configured: boolean;
  active: boolean;
  algorithm: string;
  key_derivation: 'fernet-key' | 'scrypt';
  rotation_keys: number;
  note: string;
};

export async function getEncryptionStatus() {
  return apiGet<EncryptionStatus>('/settings/encryption');
}

export async function getErpIntegration() {
  return apiGet<ErpIntegrationConfig>('/settings/integrations/erp');
}

export async function saveErpIntegration(values: { baseUrl: string; apiKey?: string; connectionParams?: Record<string, unknown> }) {
  return apiPatch<ErpIntegrationConfig>('/settings/integrations/erp', { values });
}

export async function testSavedErpIntegration() {
  return apiPost<ErpIntegrationConfig & { ok: boolean }>('/settings/integrations/erp/test', {});
}

export async function syncSavedErpIntegration(types: string[]) {
  return apiPost<any>('/settings/integrations/erp/sync', { values: { types } }, { timeoutMs: 5 * 60 * 1000 });
}

export async function getErpSyncHistory() {
  const payload = await apiGet<{ data: any[] }>('/imports');
  return (payload.data || []).filter((item) => item.importType === 'erp');
}

// ERP 字段映射（Phase 5B 收尾批）。spec 是唯一映射源的完整结构，编辑器只重建 fields/converts/required。
export type ErpMappingRow = {
  sourceField: string;
  targetField: string;
  kind: 'field' | 'convert';
  convertType?: string | null;
  sourceUnit?: string | null;
  targetUnit?: string | null;
  required: boolean;
  businessKey: boolean;
  sensitive: boolean;
};

export type ErpMappingResource = {
  resourceType: string;
  label: string;
  sourceTable: string;
  targetTable: string;
  aggregation: string;
  unknownColumns: 'extra' | 'reject';
  forbiddenColumns: string[];
  requiredSources: string[];
  businessKeys: string[];
  rows: ErpMappingRow[];
  targetColumns: Array<{ name: string; type: string; nullable: boolean }>;
};

export type ErpMappingView = {
  source: 'file' | 'tenant';
  version: number | null;
  updatedAt: string | null;
  updatedBy: string | null;
  filePath: string;
  usable: boolean;
  degraded: boolean;
  degradeReason: string | null;
  errors: string[];
  warnings: string[];
  resources: ErpMappingResource[];
  spec: Record<string, any>;
  conversionTypes: string[];
  sensitiveColumns: string[];
};

export async function getErpMapping() {
  return apiGet<ErpMappingView>('/settings/integrations/erp/mapping');
}

export async function validateErpMapping(spec: Record<string, any>) {
  return apiPost<{ valid: boolean; errors: string[]; warnings: string[] }>(
    '/settings/integrations/erp/mapping:validate',
    { values: { spec } },
  );
}

export async function saveErpMapping(spec: Record<string, any>) {
  return apiPut<ErpMappingView>('/settings/integrations/erp/mapping', { values: { spec } });
}

export async function resetErpMapping() {
  return apiPost<ErpMappingView>('/settings/integrations/erp/mapping:reset', {});
}

export async function getErpMappingSourceFields(resource: string) {
  return apiGet<{ resource: string; sampledRows: number; fields: Array<{ name: string; sample: string | null; mapped: boolean; sensitive: boolean }> }>(
    '/settings/integrations/erp/mapping/source-fields',
    { resource },
  );
}

// ---------------------------------------------------------------- 审批链配置
// 审批链配置：此前该页只弹成功提示、不落库，现改为真实持久化。

export type ApprovalChainLevel = { approver: string; countersign: string[] };

export type ApprovalChain = {
  levels: Record<'low' | 'medium' | 'high', ApprovalChainLevel>;
  financeCountersign: boolean;
  version: number;
  source: string;
  configured: boolean;
};

export async function getApprovalChain() {
  return apiGet<ApprovalChain>('/settings/approval-chain');
}

export async function saveApprovalChain(values: Omit<ApprovalChain, 'version' | 'source' | 'configured'>) {
  return apiPut<ApprovalChain>('/settings/approval-chain', values);
}

// ---------------------------------------------------------------- 数据范围
// 注意 enforced 字段：后端目前只存不过滤，页面必须据此显示"待生效"，不得暗示已经在隔离数据。

export type DataScopeRow = { code: string; name: string; scope: string; userCount: number };

export type DataScopeView = {
  roles: DataScopeRow[];
  version: number;
  configured: boolean;
  enforced: boolean;
};

export async function getDataScopes() {
  return apiGet<DataScopeView>('/settings/data-scopes');
}

export async function saveDataScopes(roles: Record<string, string>) {
  return apiPut<DataScopeView>('/settings/data-scopes', { roles });
}

// ---------------------------------------------------------------- 风险规则

export type RiskRule = { id: string; name: string; threshold: string; enabled: boolean };

export async function getRiskRules() {
  return apiGet<{ data: RiskRule[] }>('/risk-rules');
}

export async function updateRiskRule(id: string, values: Partial<RiskRule>) {
  return apiPut<RiskRule>(`/risk-rules/${id}`, values);
}
