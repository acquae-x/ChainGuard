// 审批服务（Phase 2 §2.2 双模式）。api 模式对接 /approvals*，mock 走 workflowStore。
import { currentUser } from './user';
import { workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiGet, apiPost } from '../utils/request';

const actor = async () => (await currentUser())?.currentUser;
const doneStatuses = ['approved', 'rejected', 'recalc_requested', 'transferred', 'withdrawn'];

// 由风险等级+成本影响推导审批链提示（后端 detail 不返回 alert，前端补齐）
function buildAlert(riskLevel: 'high' | 'medium' | 'low', costImpact: number) {
  const needsFinance = riskLevel === 'high' || (riskLevel === 'medium' && costImpact > 50000);
  return riskLevel === 'high'
    ? '高风险事件：老板终批，财务并行会签。'
    : riskLevel === 'medium' && needsFinance
      ? '中风险且成本影响超过 ¥50,000：供应链负责人审批后需财务会签。'
      : riskLevel === 'medium'
        ? '中风险事件：供应链负责人审批，老板抄送。'
        : '低风险事件：供应链负责人单人审批。';
}

export async function getApprovals(tab = 'pending') {
  return pick(
    () => apiGet('/approvals', { tab }),
    async () => {
      const user = await currentUser();
      const role = user?.currentUser.roleCode;
      const approvals = workflowStore.listApprovals();
      const data = tab === 'done'
        ? approvals.filter((item) => doneStatuses.includes(item.status))
        : tab === 'cc'
          ? approvals.filter((item) => item.ccRoleCodes?.includes(role as API.RoleCode))
          : approvals.filter((item) => item.status === 'pending' || item.status === 'submitted');
      return { data, total: data.length, success: true };
    },
  );
}

export async function getApprovalDetail(id: string) {
  return pick(
    async () => {
      const res = await apiGet<any>(`/approvals/${id}`);
      try { res.decisionDetail = await apiGet<any>(`/incidents/${res.approval.incidentId}/decision-detail`); } catch { /* detail unavailable for legacy approval */ }
      const riskLevel = res.approval?.riskLevel as 'high' | 'medium' | 'low';
      return { ...res, alert: res.alert || buildAlert(riskLevel, res.approval?.costImpact || 0) };
    },
    async () => {
      const approval = workflowStore.getApproval(id);
      if (!approval) throw new Error('审批单不存在');
      const proposal = workflowStore.getProposal(approval.proposalId);
      const options = workflowStore.getProposals(approval.incidentId);
      const alternative = options.find((item) => item.tag === 'alternative') || proposal;
      const baseline = options.find((item) => item.tag === 'invalid') || proposal;
      const riskLevel = approval.riskLevel as 'high' | 'medium' | 'low';
      const needsFinance = riskLevel === 'high' || (riskLevel === 'medium' && (approval.costImpact ?? 0) > 50000);
      const alert = buildAlert(riskLevel, approval.costImpact ?? 0);
      const chain = riskLevel === 'high'
        ? ['供应链负责人提交', '老板/总经理终批', `财务${approval.countersigned ? '已会签' : '并行会签'}`]
        : riskLevel === 'medium' && needsFinance
          ? ['供应链负责人审批', `财务${approval.countersigned ? '已会签' : '待会签'}`]
          : riskLevel === 'medium'
            ? ['供应链负责人审批', '老板/总经理抄送']
            : ['供应链负责人审批'];
      return { approval, proposal, alert, chain, comparison: { current: proposal, baseline, alternative } };
    },
  );
}

// 审批动作统一走 POST /approvals/{id}/{action}
type ApprovalAction = 'approve' | 'reject' | 'recalc' | 'transfer' | 'submit' | 'withdraw' | 'countersign' | 'ratify_approve' | 'ratify_object';

async function runAction(id: string, action: ApprovalAction, values?: any) {
  return pick(
    async () => {
      const approval = await apiPost(`/approvals/${id}/${action}`, values || {});
      return { ok: true, id, action, approval };
    },
    async () => {
      const mockAction = action === 'submit' ? 'submit' : action;
      const approval = workflowStore.updateApproval(id, mockAction, values || {}, await actor());
      if (values?.saveExperience) workflowStore.saveExperience(id, values.reason, await actor());
      return { ok: true, id, action, approval };
    },
  );
}

export async function approve(id: string, values?: any) {
  return runAction(id, 'approve', values);
}
export async function submitHighApproval(id: string) {
  return runAction(id, 'submit', {});
}
export async function withdrawApproval(id: string) {
  return runAction(id, 'withdraw', {});
}
export async function countersign(id: string) {
  return runAction(id, 'countersign', {});
}
export async function reject(id: string, values: any) {
  return runAction(id, 'reject', values);
}
export async function recalcRequest(id: string, values: any) {
  return runAction(id, 'recalc', values);
}
export async function transfer(id: string, values: any) {
  return runAction(id, 'transfer', values);
}
export async function ratifyApprove(id: string) { return runAction(id, 'ratify_approve', {}); }
export async function ratifyObject(id: string, values: any) { return runAction(id, 'ratify_object', values); }
