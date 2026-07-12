// 工作台服务（Phase 2 §2.2 双模式）。api 模式对接 /dashboard/*，mock 走 workflowStore。
import { workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiGet } from '../utils/request';

export async function getKpis() {
  return pick(
    () => apiGet('/dashboard/kpis'),
    async () => ({}),
  );
}
export async function getTopRisks() {
  return pick(
    () => apiGet('/dashboard/top-risks'),
    async () => workflowStore.listRisks(),
  );
}
export async function getMyTasks() {
  return pick(
    () => apiGet('/dashboard/my-tasks'),
    async () => workflowStore.listTasks(),
  );
}
export async function getPendingApprovals() {
  return pick(
    () => apiGet('/dashboard/pending-approvals'),
    async () => workflowStore.listApprovals().filter((item) => item.status === 'pending'),
  );
}
export async function getDashboardAudit() {
  return pick(
    () => apiGet('/dashboard/audit'),
    async () => workflowStore.listAuditLogs().slice(0, 6),
  );
}
