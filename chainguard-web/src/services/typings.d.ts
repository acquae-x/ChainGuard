declare namespace API {
  type RoleCode = 'admin' | 'boss' | 'scm_lead' | 'buyer' | 'warehouse' | 'sales' | 'finance' | 'planner' | 'auditor';

  type Tenant = {
    id: string;
    name: string;
    industry: string;
    scale: string;
    status: 'initializing' | 'active' | 'expired';
    plan: 'trial' | 'paid';
    trialEndAt: string;
    demoDataFlag?: boolean;
    timezone: string;
  };

  type Department = { id: string; tenantId: string; name: string; parentId?: string };
  type Role = { id: string; tenantId: string; code: RoleCode; name: string; builtin: boolean; permissions: string[] };
  type User = { id: string; tenantId: string; name: string; phone: string; email?: string; deptId: string; roleIds: string[]; roleCode: RoleCode; status: 'active' | 'invited' | 'disabled'; permissions: string[]; dataScope: 'all' | 'dept' | 'custom'; readonly?: boolean; mustChangePassword?: boolean };
  type Invitation = { id: string; tenantId: string; code: string; roleId: string; deptId: string; expireAt: string; maxUses: number; usedCount: number };

  type LoginResult = { token: string; currentUser: User; tenant: Tenant };
  type Risk = { id: string; code: string; level: 'high' | 'medium' | 'low'; type: string; objectType: string; objectName: string; score: number; rule: string; foundAt: string; status: string; supplier?: string; material?: string; orderNo?: string; warehouse?: string; incidentId?: string };
  type Incident = { id: string; code: string; title: string; type: string; level: 'high' | 'medium' | 'low'; status: string; owner: string; createdAt: string; sourceRiskIds: string[]; loss: number; cost: number };
  // 未知业务指标由后端落 null，前端渲染"数据缺失"，禁止伪装成 0
  type HistoryExperience = { matched: boolean; count: number; conclusions: string[]; sources: string[] };
  type Proposal = { id: string; incidentId: string; name: string; tag: 'recommended' | 'alternative' | 'invalid'; totalCost: number | null; leadTimeImpact: number | null; residualRisk: 'high' | 'medium' | 'low' | null; customerImpact: number | null; highValueCustomers: number | null; reason: string; views: Record<string, string>; modified?: boolean; historyExperience?: HistoryExperience };
  type ExperienceCard = { id: string; title: string; scenario: string; recommendedPattern: string; triggerConditions: string[]; status: string; outcome: { state?: string; summary?: string }; metrics: Record<string, number | null>; source: { jobId?: string; incidentId?: string; proposalId?: string } };
  type Approval = { id: string; proposalId: string; incidentId: string; status: string; riskLevel: string; summary: string; costImpact: number | null; submitter: string; waitingHours: number };
  type Task = { id: string; title: string; source: string; incidentId?: string; assignee: string; assigneeName?: string; roleCode: RoleCode; status: string; dueAt: string; priority: string; checklist: { text: string; done: boolean }[] };
  type AuditLog = { id: string; time: string; userId: string; userName: string; roleCode: RoleCode; action: string; targetType: string; targetId: string; targetName: string; detail: Record<string, any>; ip: string };
}
