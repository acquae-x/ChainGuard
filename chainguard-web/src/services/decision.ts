// 决策方案服务（双模式）。核心：生成走 202+jobId 异步轮询。
import { currentUser } from './user';
import { workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiGet, apiPatch, apiPost, getToken } from '../utils/request';

const actor = async () => (await currentUser())?.currentUser;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// 生成决策方案：POST :generate → 202 {jobId} → 轮询 GET /jobs/{jobId} → 取方案。
export async function generateProposals(incidentId: string) {
  return pick(
    async () => {
      const started = await apiPost<{ jobId: string; status: string }>(`/incidents/${incidentId}/proposals:generate`, {});
      // 轮询作业状态，最长约 60s（与后端超时对齐）
      for (let i = 0; i < 40; i += 1) {
        const job = await apiGet<{ status: string; error?: string }>(`/jobs/${started.jobId}`, undefined, { silent: true });
        if (job.status === 'succeeded') break;
        if (job.status === 'failed') throw new Error(job.error || '方案生成失败，请重试');
        await sleep(1500);
      }
      const res = await apiGet<{ data: API.Proposal[] }>('/proposals', { incidentId });
      return res.data;
    },
    async () => workflowStore.ensureProposals(incidentId, await actor()),
  );
}

export async function getProposalsForIncident(incidentId: string) {
  return pick(
    async () => (await apiGet<{ data: API.Proposal[] }>('/proposals', { incidentId })).data,
    async () => workflowStore.getProposals(incidentId),
  );
}

export async function recalc(proposalId: string, overrides: any) {
  // 后端 PATCH /proposals/{id} 只读 body.overrides，须包一层 { overrides }（否则参数丢失、审计为空、走默认 ×1.04）。
  return pick(
    () => apiPatch(`/proposals/${proposalId}`, { overrides }),
    async () => workflowStore.updateProposal(proposalId, overrides, await actor()),
  );
}

export async function getExplanation(proposalId: string) {
  return pick(
    () => apiGet(`/proposals/${proposalId}/explanation`),
    async () => ({ proposalId, evidence: ['EXP-019', '安全库存阈值', '高等级客户交付约束'] }),
  );
}

export async function submitForApproval(proposalId: string) {
  return pick(
    () => apiPost(`/proposals/${proposalId}/submit`, {}),
    async () => workflowStore.submitApproval(proposalId, await actor()),
  );
}

export async function getProposals() {
  return pick(
    () => apiGet('/proposals'),
    async () => {
      const data = workflowStore.getProposals();
      return { data, total: data.length, success: true };
    },
  );
}

export async function getExperienceCards() {
  return pick(
    async () => (await apiGet<{ data: API.ExperienceCard[] }>('/experiences')).data,
    async () => [],
  );
}

export async function saveDraft(incidentId: string, proposalId?: string) {
  return pick(
    async () => {
      if (proposalId) return apiPost(`/proposals/${proposalId}/draft`, { incidentId });
      // 无 proposalId 的草稿暂无后端端点，回退 mock 行为
      return workflowStore.saveDraft(incidentId, proposalId, await actor());
    },
    async () => workflowStore.saveDraft(incidentId, proposalId, await actor()),
  );
}

export async function getDraft(incidentId: string) {
  return pick(
    () => apiGet(`/incidents/${incidentId}/draft`),
    async () => workflowStore.getDraft(incidentId),
  );
}

// 决策就绪度：后端在推演前就能判断上下文数据是否齐备（blocking）以及哪些字段是估算的（degraded）。
// 这个信号此前完全没被前端消费，用户可能对着数据不全的事件生成方案而不自知。
export type DecisionReadiness = {
  ready: boolean;
  level: string;
  blocking: { code: string; message: string }[];
  degraded: string[];
  checks?: Record<string, unknown>;
  configuration?: Record<string, unknown>;
};

export async function getDecisionReadiness(incidentId: string) {
  return pick<DecisionReadiness>(
    () => apiGet(`/incidents/${incidentId}/decision-readiness`),
    async () => ({ ready: true, level: 'complete', blocking: [], degraded: [] }),
  );
}

export async function getDecisionDetail(incidentId: string) {
  return pick(() => apiGet(`/incidents/${incidentId}/decision-detail`), async () => ({ proposals: [], conflict: {}, rebuttal: {}, arbitration: {}, constraint_analysis: {} }));
}

export async function exportDecisionDetail(incidentId: string, format: 'json' | 'pdf') {
  const response = await fetch(`/api/v1/incidents/${incidentId}/decision-detail/export?format=${format}`, { headers: { Authorization: `Bearer ${getToken() || ''}` }, credentials: 'include' });
  if (!response.ok) {
    // 透出后端业务错误文案（如 PDF 依赖未安装），由调用方以 message 呈现
    let detailMessage = `导出失败（${response.status}）`;
    try {
      const body = await response.json();
      if (body?.message) detailMessage = body.message;
    } catch { /* 非 JSON 错误体保持默认文案 */ }
    throw new Error(detailMessage);
  }
  const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `decision-${incidentId}.${format}`; link.click(); URL.revokeObjectURL(link.href);
}
