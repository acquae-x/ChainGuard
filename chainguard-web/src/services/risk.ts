// 风险服务（Phase 2 §2.2 双模式）。api 模式对接 /risks*，mock 模式走 workflowStore。
import { currentUser } from './user';
import { appendAudit, workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiGet, apiPatch, apiPost } from '../utils/request';

const actor = async () => (await currentUser())?.currentUser;

export async function getRisks(params?: any) {
  return pick(
    () => apiGet('/risks', {
      level: params?.level,
      status: params?.status,
      type: params?.type,
      current: params?.current,
      pageSize: params?.pageSize,
    }),
    async () => {
      const risks = workflowStore.listRisks();
      const range = params?.dateRange as string[] | undefined;
      const matches = (value: unknown, keyword: unknown) => !keyword || String(value || '').toLowerCase().includes(String(keyword).toLowerCase());
      const data = risks.filter((item: any) => {
        if (params?.level && item.level !== params.level) return false;
        if (params?.type && item.type !== params.type) return false;
        if (params?.status && item.status !== params.status) return false;
        if (range?.[0] && new Date(item.foundAt) < new Date(`${range[0]}T00:00:00`)) return false;
        if (range?.[1] && new Date(item.foundAt) > new Date(`${range[1]}T23:59:59`)) return false;
        if (!matches(item.material || item.objectName, params?.material)) return false;
        if (!matches(item.supplier || item.objectName, params?.supplier)) return false;
        if (!matches(item.orderNo || item.objectName, params?.orderNo)) return false;
        if (!matches(item.warehouse || item.objectName, params?.warehouse)) return false;
        return true;
      });
      return { data, total: data.length, success: true };
    },
  );
}

export async function getRiskMatrix() {
  return pick(
    () => apiGet('/risks/matrix'),
    async () => workflowStore.listRisks().map((item, index) => ({ name: item.code, value: [index + 2, Math.round(item.score / 10), item.score], level: item.level })),
  );
}

export async function createIncidentFromRisks(riskIds: string[]) {
  return pick(
    () => apiPost('/incidents', { riskIds }),
    async () => workflowStore.createIncident(riskIds, await actor()),
  );
}

export async function ignoreRisk(riskId: string, reason: string) {
  if (!reason.trim()) throw new Error('忽略风险必须填写理由');
  return pick(
    () => apiPatch(`/risks/${riskId}/status`, { status: 'ignored', reason }),
    async () => workflowStore.ignoreRisk(riskId, reason, await actor()),
  );
}

export async function markRiskWatching(riskId: string) {
  return pick(
    () => apiPatch(`/risks/${riskId}/status`, { status: 'watching' }),
    async () => {
      const risk = workflowStore.listRisks().find((item) => item.id === riskId);
      if (!risk) throw new Error('风险不存在');
      risk.status = 'watching';
      appendAudit('标记观察', 'risk', risk.id, risk.code, { status: 'watching' }, await actor());
      return risk;
    },
  );
}

// 预警规则暂无后端端点，保留 mock（ADR §4 缺口，列 TODO）。
export async function getRules() {
  return { data: [{ id: 'rule-1', name: '安全库存预警线', threshold: '20%', enabled: true }, { id: 'rule-2', name: '交期延误容忍天数', threshold: '3 天', enabled: true }, { id: 'rule-3', name: '单一供应商依赖占比', threshold: '60%', enabled: true }] };
}

export async function updateRule(values: any) {
  return { ok: true, values };
}
