// 工作台服务（Phase 2 §2.2 双模式）。api 模式对接 /dashboard/*，mock 走 workflowStore。
import { workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiGet } from '../utils/request';

export type AutomationStats = {
  totalDecisions: number;
  autoApproved: number;
  escalated: number;
  automationRate: number;
  escalationRate: number;
  escalationReasons: Record<string, number>;
  escalationRules: Array<{ code: string; description: string }>;
};

const EMPTY_AUTOMATION_STATS: AutomationStats = {
  totalDecisions: 0,
  autoApproved: 0,
  escalated: 0,
  automationRate: 0,
  escalationRate: 0,
  escalationReasons: {},
  escalationRules: [],
};

export async function getKpis() {
  return pick(
    () => apiGet('/dashboard/kpis'),
    async () => ({}),
  );
}

export async function getAutomationStats() {
  return pick(
    () => apiGet<AutomationStats>('/dashboard/automation'),
    async () => EMPTY_AUTOMATION_STATS,
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
// C02/C03 节点健康。mock 模式**如实返回不可用**：workflowStore 的演示数据之间没有
// 物料/库存/供应商/订单的真实外键，编一份"节点健康"就是伪造结论。
const NODE_HEALTH_UNAVAILABLE = {
  available: false,
  code: 'CG-C033',
  message: '节点健康基于租户真实业务实体计算，仅在 api 模式（连接真实后端）下可用；当前为演示数据模式。',
  scope: null,
  summary: null,
  byType: [],
  nodes: [],
  filtered: null,
  filters: null,
  dataFreshness: null,
  limitations: [
    {
      code: 'CG-C033',
      message: '演示数据之间不存在真实实体外键，因此不提供节点健康结论。',
    },
  ],
};

export type NodeHealthQuery = {
  nodeType?: string;
  health?: string;
  keyword?: string;
  current?: number;
  pageSize?: number;
};

export async function getNodeHealth(params: NodeHealthQuery = {}) {
  return pick(
    () => apiGet('/dashboard/node-health', params as Record<string, unknown>),
    async () => NODE_HEALTH_UNAVAILABLE,
  );
}

export async function getMyNodes(params: NodeHealthQuery = {}) {
  return pick(
    () => apiGet('/dashboard/my-nodes', params as Record<string, unknown>),
    async () => NODE_HEALTH_UNAVAILABLE,
  );
}

export async function getDashboardAudit() {
  return pick(
    () => apiGet('/dashboard/audit'),
    async () => workflowStore.listAuditLogs().slice(0, 6),
  );
}
