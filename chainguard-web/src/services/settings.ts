// 系统设置服务（Phase 2 §2.2 双模式）。api 模式对接 /settings/* 与 /audit-logs，mock 走内置数据。
import { auditLogs, departments, roles, tenant, users } from './mockData';
import { workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiDelete, apiGet, apiPatch, apiPost } from '../utils/request';

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
