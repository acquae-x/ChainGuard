// 应急事件服务（双模式）。api 模式对接 /incidents*，mock 走 workflowStore。
import { currentUser } from './user';
import { workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiGet, apiPatch } from '../utils/request';

const actor = async () => (await currentUser())?.currentUser;

export async function getIncidents() {
  return pick(
    () => apiGet('/incidents'),
    async () => {
      const data = workflowStore.listIncidents();
      return { data, total: data.length, success: true };
    },
  );
}

export async function getIncident(id: string) {
  return pick(
    () => apiGet(`/incidents/${id}`),
    async () => workflowStore.getIncident(id),
  );
}

export async function getImpact(id: string) {
  return pick(
    () => apiGet(`/incidents/${id}/impact`),
    async () => workflowStore.getImpact(id),
  );
}

export async function getTimeline(id: string) {
  return pick(
    () => apiGet(`/incidents/${id}/timeline`),
    async () => workflowStore.listAuditLogs().filter((item) => item.targetId === id || item.detail.incidentId === id),
  );
}

export async function updateIncident(id: string, values: Partial<API.Incident>) {
  return pick(
    () => apiPatch(`/incidents/${id}`, values),
    async () => workflowStore.updateIncident(id, values, await actor()),
  );
}

// 事件备注暂无独立后端端点，保留 mock。
export async function addIncidentNote(id: string, note: string) {
  workflowStore.addIncidentNote(id, note, await actor());
  return { ok: true };
}

export async function closeIncident(id: string) {
  return pick(
    () => apiPatch(`/incidents/${id}`, { status: 'closed' }),
    async () => workflowStore.closeIncident(id, await actor()),
  );
}
