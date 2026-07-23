import { approvals as seedApprovals, auditLogs as seedAuditLogs, incident as seedIncident, inventories, materials, orders, proposals as seedProposals, risks as seedRisks, suppliers, tasks as seedTasks } from './mockData';

type Actor = Pick<API.User, 'id' | 'name' | 'roleCode'>;
type ApprovalHistory = { action: string; reason?: string; createdAt: string; actor: string };
type ApprovalRecord = API.Approval & { ccRoleCodes?: API.RoleCode[]; transferredTo?: string; countersigned?: boolean; experienceSaved?: boolean; history?: ApprovalHistory[] };
type ExperienceCard = { id: string; title: string; trigger: string; action: string; constraint: string; outcome: string; status: string; approvalId?: string };

const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const defaultActor: Actor = { id: 'u-scm_lead', name: '供应链负责人', roleCode: 'scm_lead' };
let sequence = 1;

const state = {
  risks: copy(seedRisks),
  incidents: [copy(seedIncident)],
  proposals: copy(seedProposals),
  approvals: (copy(seedApprovals) as ApprovalRecord[]).map((item) => ({ ...item, ccRoleCodes: item.riskLevel === 'high' ? ['finance'] : [] })) as ApprovalRecord[],
  tasks: copy(seedTasks),
  auditLogs: copy(seedAuditLogs),
  experiences: [{ id: 'EXP-019', title: '核心芯片供应商停产 72 小时应急', trigger: '核心供应商停产', action: '双供应商加急+首批空运', constraint: 'A 级客户延误不超过 3 天', outcome: '净收益 73.2 万', status: 'verified' }] as ExperienceCard[],
  // 方案草稿（对接后端时替换为 POST /decisions/:id/draft）
  drafts: {} as Record<string, { proposalId?: string; savedAt: string }>
};

const now = () => new Date().toLocaleString('zh-CN', { hour12: false });
const actorOf = (actor?: Actor) => actor || defaultActor;

export function appendAudit(action: string, targetType: string, targetId: string, targetName: string, detail: Record<string, unknown> = {}, actor?: Actor) {
  const current = actorOf(actor);
  const log: API.AuditLog = {
    id: `audit-${Date.now()}-${sequence++}`,
    time: now(),
    userId: current.id,
    userName: current.name,
    roleCode: current.roleCode,
    action,
    targetType,
    targetId,
    targetName,
    detail,
    ip: '127.0.0.1'
  };
  state.auditLogs.unshift(log);
  return log;
}

export const workflowStore = {
  listRisks: () => state.risks,
  listIncidents: () => state.incidents,
  listApprovals: () => state.approvals,
  listTasks: () => state.tasks,
  listAuditLogs: () => state.auditLogs,
  listExperiences: () => state.experiences,
  getIncident: (id: string) => state.incidents.find((item) => item.id === id),
  getApproval: (id: string) => state.approvals.find((item) => item.id === id),
  getProposal: (id: string) => state.proposals.find((item) => item.id === id),
  getProposals: (incidentId?: string) => incidentId ? state.proposals.filter((item) => item.incidentId === incidentId) : state.proposals,

  createIncident(riskIds: string[], actor?: Actor) {
    const sourceRisks = state.risks.filter((item) => riskIds.includes(item.id));
    const leadRisk = sourceRisks[0] || state.risks[0];
    const id = `inc-${Date.now()}-${sequence++}`;
    const current = actorOf(actor);
    const incident: API.Incident = {
      id,
      code: `INC-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${String(sequence).padStart(3, '0')}`,
      title: `${leadRisk.objectName}异常影响${leadRisk.material || leadRisk.objectName}`,
      type: 'supplier_shutdown',
      level: sourceRisks.some((item) => item.level === 'high') ? 'high' : leadRisk.level,
      status: 'evaluating',
      owner: current.name,
      createdAt: now(),
      sourceRiskIds: riskIds,
      loss: 860000,
      cost: 0
    };
    state.incidents.unshift(incident);
    sourceRisks.forEach((risk) => { risk.status = 'incident_created'; (risk as API.Risk & { incidentId?: string }).incidentId = id; });
    appendAudit('创建事件', 'incident', id, incident.title, { riskIds }, current);
    return incident;
  },

  ignoreRisk(riskId: string, reason: string, actor?: Actor) {
    const risk = state.risks.find((item) => item.id === riskId);
    if (!risk) throw new Error('风险不存在');
    risk.status = 'ignored';
    appendAudit('忽略风险', 'risk', risk.id, risk.code, { reason }, actor);
    return risk;
  },

  updateIncident(id: string, patch: Partial<API.Incident>, actor?: Actor) {
    const incident = state.incidents.find((item) => item.id === id);
    if (!incident) throw new Error('事件不存在');
    const before = { level: incident.level, status: incident.status };
    Object.assign(incident, patch);
    appendAudit('更新事件', 'incident', id, incident.title, { before, after: patch }, actor);
    return incident;
  },

  addIncidentNote(id: string, note: string, actor?: Actor) {
    const incident = state.incidents.find((item) => item.id === id);
    if (!incident) throw new Error('事件不存在');
    appendAudit('添加备注', 'incident', id, incident.title, { note }, actor);
  },

  closeIncident(id: string, actor?: Actor) {
    const incident = state.incidents.find((item) => item.id === id);
    if (!incident) throw new Error('事件不存在');
    incident.status = 'reviewing';
    appendAudit('关闭事件', 'incident', id, incident.title, { status: 'reviewing' }, actor);
    return incident;
  },

  ensureProposals(incidentId: string, actor?: Actor) {
    const existing = state.proposals.filter((item) => item.incidentId === incidentId);
    if (existing.length) return existing;
    const generated = copy(seedProposals).map((proposal, index) => ({
      ...proposal,
      id: `prop-${Date.now()}-${index + 1}`,
      incidentId
    }));
    state.proposals.push(...generated);
    const incident = state.incidents.find((item) => item.id === incidentId);
    if (incident) incident.status = 'planning';
    appendAudit('生成方案', 'incident', incidentId, incident?.title || incidentId, { proposalCount: generated.length }, actor);
    return generated;
  },

  updateProposal(proposalId: string, overrides: Record<string, unknown>, actor?: Actor) {
    const proposal = state.proposals.find((item) => item.id === proposalId);
    if (!proposal) throw new Error('方案不存在');
    proposal.modified = true;
    // P0-2：成本缺失（null）时不可凭空推 4% 浮动
    proposal.totalCost = proposal.totalCost === null || proposal.totalCost === undefined ? null : Math.round(proposal.totalCost * 1.04);
    appendAudit('重算方案', 'proposal', proposalId, proposal.name, { overrides }, actor);
    return proposal;
  },

  submitApproval(proposalId: string, actor?: Actor) {
    const proposal = state.proposals.find((item) => item.id === proposalId);
    if (!proposal) throw new Error('方案不存在');
    const incident = state.incidents.find((item) => item.id === proposal.incidentId);
    if (!incident) throw new Error('事件不存在');
    const approval: ApprovalRecord = {
      id: `ap-${Date.now()}-${sequence++}`,
      proposalId,
      incidentId: incident.id,
      status: 'pending',
      riskLevel: incident.level,
      summary: proposal.name,
      costImpact: proposal.totalCost,
      submitter: actorOf(actor).name,
      waitingHours: 0,
      ccRoleCodes: incident.level === 'high' ? ['finance'] : []
    };
    state.approvals.unshift(approval);
    incident.status = 'approving';
    appendAudit('提交审批', 'approval', approval.id, proposal.name, { incidentId: incident.id, riskLevel: incident.level }, actor);
    return approval;
  },

  updateApproval(id: string, action: 'approve' | 'reject' | 'recalc' | 'transfer' | 'submit' | 'withdraw' | 'countersign' | 'ratify_approve' | 'ratify_object', values: Record<string, unknown> = {}, actor?: Actor) {
    const approval = state.approvals.find((item) => item.id === id);
    if (!approval) throw new Error('审批单不存在');
    const incident = state.incidents.find((item) => item.id === approval.incidentId);
    const proposal = state.proposals.find((item) => item.id === approval.proposalId);
    if (action === 'approve') {
      approval.status = 'approved';
      if (incident) incident.status = 'executing';
      const roles: Array<[API.RoleCode, string, string]> = [
        ['buyer', '锁定替代供应商订单', '确认报价、锁定交期'],
        ['scm_lead', '安排关键物料加急运输', '确认航班、跟踪到货'],
        ['sales', '通知受影响高等级客户', '发送沟通邮件'],
        ['warehouse', '调整安全库存与调拨', '冻结库存、完成调拨'],
        ['planner', '调整生产排程', '更新工单、确认产能']
      ];
      roles.forEach(([roleCode, title, checklist], index) => state.tasks.unshift({
        id: `task-${Date.now()}-${index + 1}`,
        title,
        source: incident?.code || approval.incidentId,
        incidentId: approval.incidentId,
        assignee: roleCode === 'buyer' ? '采购人员' : roleCode === 'sales' ? '销售/客服' : roleCode === 'warehouse' ? '仓库人员' : roleCode === 'planner' ? '生产计划人员' : '供应链负责人',
        roleCode,
        status: 'pending',
        dueAt: '2026-07-12 18:00',
        priority: '高',
        checklist: checklist.split('、').map((text) => ({ text, done: false }))
      }));
    }
    if (action === 'reject') { approval.status = 'rejected'; if (incident) incident.status = 'planning'; }
    if (action === 'recalc') { approval.status = 'recalc_requested'; if (incident) incident.status = 'planning'; }
    if (action === 'transfer') { approval.status = 'transferred'; approval.transferredTo = String(values.assignee || ''); }
    if (action === 'submit') approval.status = 'pending';
    if (action === 'withdraw') { approval.status = 'withdrawn'; if (incident) incident.status = 'planning'; }
    if (action === 'countersign') approval.countersigned = true;
    if (action === 'ratify_approve' || action === 'ratify_object') {
      approval.history = [...(approval.history || []), {
        action,
        reason: typeof values.reason === 'string' ? values.reason : undefined,
        createdAt: now(),
        actor: actorOf(actor).name,
      }];
    }
    appendAudit(`审批${action}`, 'approval', id, proposal?.name || approval.summary, { ...values, incidentId: approval.incidentId }, actor);
    return approval;
  },

  saveExperience(approvalId: string, reason?: string, actor?: Actor) {
    const approval = state.approvals.find((item) => item.id === approvalId);
    const proposal = approval && state.proposals.find((item) => item.id === approval.proposalId);
    if (!approval || !proposal) return;
    const card: ExperienceCard = { id: `EXP-${Date.now()}`, title: proposal.name, trigger: approval.riskLevel === 'high' ? '高风险中断事件' : '供应链风险事件', action: proposal.name, constraint: reason || '审批意见沉淀', outcome: approval.status === 'approved' ? '方案已批准执行' : '方案已退回优化', status: 'pending', approvalId };
    state.experiences.unshift(card);
    approval.experienceSaved = true;
    appendAudit('存为经验', 'experience', card.id, card.title, { approvalId }, actor);
  },

  saveDraft(incidentId: string, proposalId?: string, actor?: Actor) {
    state.drafts[incidentId] = { proposalId, savedAt: now() };
    appendAudit('保存草稿', 'incident', incidentId, state.incidents.find((item) => item.id === incidentId)?.title || incidentId, { proposalId }, actor);
    return state.drafts[incidentId];
  },

  getDraft(incidentId: string) {
    return state.drafts[incidentId];
  },

  // A04：影响范围由实体间真实外键算出，mock 数据集没有这些关系。
  // 与其把四张互不相干的演示表并排摆出来假装是"影响范围"，不如如实说 mock 模式不支持。
  getImpact(id: string) {
    const message = 'mock 模式没有结构化实体关系，影响范围仅在 api 模式可用。';
    return {
      available: false,
      code: 'CG-A046',
      message,
      scopeOf: { kind: 'incident', id, code: id, name: '' },
      seeds: [],
      summary: { total: 0, direct: 0, indirect: 0, byType: {} },
      groups: [],
      traversal: { maxHops: 2, relations: [], note: null },
      limitations: [{ code: 'CG-A046', message }],
      generatedAt: null
    };
  }
};
