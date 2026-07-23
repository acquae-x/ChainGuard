// 风险服务（Phase 2 §2.2 双模式）。api 模式对接 /risks*，mock 模式走 workflowStore。
import { currentUser } from './user';
import { appendAudit, workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiGet, apiPatch, apiPost, apiPut } from '../utils/request';

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

// A03 实时风险解释：api 模式打后端真实解释；mock 模式保持独立，不共用数据源。
export async function getRiskExplanation(riskId: string) {
  return pick(
    () => apiGet(`/risks/${riskId}/explanation`),
    async () => {
      const risk = workflowStore.listRisks().find((item) => item.id === riskId);
      if (!risk) throw new Error('风险不存在');
      // mock 模式没有结构化实体，如实返回"不可解释"，不在演示态编造驱动因素。
      return {
        available: false,
        code: 'CG-A035',
        message: 'mock 模式没有结构化实体数据，风险解释仅在 api 模式可用。',
        risk: { id: risk.id, code: risk.code, level: risk.level, score: risk.score, rule: risk.rule, status: risk.status, foundAt: risk.foundAt, objectName: risk.objectName, type: risk.type },
        verdict: null,
        drivers: [],
        deltas: null,
        evidence: [],
        provenance: { scope: 'resource_type', batches: [] },
        decisionLink: null,
        limitations: [{ code: 'CG-A035', message: 'mock 模式没有结构化实体数据，风险解释仅在 api 模式可用。' }],
      };
    },
  );
}

// A04 影响范围：这条风险波及了哪些真实业务对象。mock 模式无结构化实体，如实说不可用，
// 不用 mockData 里那批没有外键关系的记录去凑一个"看起来像影响范围"的东西。
export async function getRiskImpactScope(riskId: string) {
  return pick(
    () => apiGet(`/risks/${riskId}/impact-scope`),
    async () => {
      const risk = workflowStore.listRisks().find((item) => item.id === riskId);
      if (!risk) throw new Error('风险不存在');
      return {
        available: false,
        code: 'CG-A046',
        message: 'mock 模式没有结构化实体关系，影响范围仅在 api 模式可用。',
        scopeOf: { kind: 'risk', id: risk.id, code: risk.code, name: risk.objectName },
        seeds: [],
        summary: { total: 0, direct: 0, indirect: 0, byType: {} },
        groups: [],
        traversal: { maxHops: 2, relations: [], note: null },
        limitations: [{ code: 'CG-A046', message: 'mock 模式没有结构化实体关系，影响范围仅在 api 模式可用。' }],
        generatedAt: null,
      };
    },
  );
}

export async function recomputeRisks() {
  return pick(
    () => apiPost('/risks/recompute', {}),
    async () => ({ created: 0, updated: 0, resolved: 0, recurred: 0, unchanged: workflowStore.listRisks().length, skipped: [], skippedCount: 0 }),
  );
}

// 后端 GET/PUT /risk-rules 早已存在（设置页的风险规则卡片一直在用），
// 这里的注释"暂无后端端点"已经过期：监控规则页因此长期显示三条写死的规则，
// 与设置页读到的真实规则对不上；更糟的是 updateRule 是空操作，切换开关会
// 弹出"规则已更新并写入审计"，但既没落库也没有审计记录。
export async function getRules() {
  return pick(
    () => apiGet<{ data: any[] }>('/risk-rules'),
    async () => ({ data: [] }),
  );
}

export async function updateRule(values: any) {
  return pick(
    () => apiPut<any>(`/risk-rules/${values.id}`, values),
    async () => ({ ok: true, values }),
  );
}
