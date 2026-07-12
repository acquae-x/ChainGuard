// 通知服务（Phase 2 §2.2 双模式）。api 模式对接 /notifications，mock 走 workflowStore。
import { workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiGet, apiPost, apiRequest } from '../utils/request';

export type NotificationKind = 'risk' | 'approval' | 'task';
export type NotificationItem = { id: string; kind: NotificationKind; title: string; target: string; read: boolean };

// 已读标记：后端 Phase 1 未提供 mark-read 端点，前端本地乐观维护（ADR §4 缺口-A，列 TODO）。
const readIds = new Set<string>();

export async function getNotifications() {
  return pick(
    async () => {
      const res = await apiGet<any>('/notifications');
      const list: any[] = Array.isArray(res) ? res : res.data || [];
      const data: NotificationItem[] = list.map((item) => ({
        id: item.id,
        kind: item.kind,
        title: item.title,
        target: item.target,
        read: item.read ?? readIds.has(item.id),
      }));
      return { data, unread: data.filter((item) => !item.read).length };
    },
    async () => {
      const risks: NotificationItem[] = workflowStore.listRisks()
        .filter((item) => item.level === 'high' && ['new', 'watching'].includes(item.status))
        .map((item) => ({ id: `risk:${item.id}`, kind: 'risk', title: `${item.objectName}：${item.rule}`, target: item.incidentId ? `/incident/${item.incidentId}` : '/risk/list', read: readIds.has(`risk:${item.id}`) }));
      const approvals: NotificationItem[] = workflowStore.listApprovals()
        .filter((item) => item.status === 'pending')
        .map((item) => ({ id: `approval:${item.id}`, kind: 'approval', title: `${item.summary}待审批`, target: `/decision/approval/${item.id}`, read: readIds.has(`approval:${item.id}`) }));
      const tasks: NotificationItem[] = workflowStore.listTasks()
        .filter((item) => item.status === 'pending')
        .map((item) => ({ id: `task:${item.id}`, kind: 'task', title: item.title, target: '/task/mine', read: readIds.has(`task:${item.id}`) }));
      const data = [...risks, ...approvals, ...tasks];
      return { data, unread: data.filter((item) => !item.read).length };
    },
  );
}

// 标记已读：api 模式接后端 POST /notifications/{id}/read；mock 模式本地维护。
export async function markRead(id: string) {
  return pick(
    async () => {
      await apiPost(`/notifications/${id}/read`, {});
      readIds.add(id);
      return { ok: true, id };
    },
    async () => {
      readIds.add(id);
      return { ok: true, id };
    },
  );
}

export async function webhookConfig(values?: { enabled?: boolean; url?: string }) {
  return pick(
    async () => values
      ? apiRequest('/notifications/webhook-config', { method: 'PUT', data: values })
      : apiGet('/notifications/webhook-config'),
    async () => ({ enabled: values?.enabled ?? false, url: values?.url || '' }),
  );
}
