// 报表服务。api 模式对接 /reports/*，mock 模式走内置演练数据。
// 口径提醒：后端对"不可测量"的指标返回 null（而非 0），页面必须显示"数据缺失"而不是 0。
import { pick } from './dataMode';
import { apiGet } from '../utils/request';

export type ReportWindow = { months: number; since: string };

export type ExecutiveReport = {
  window: ReportWindow;
  netBenefit: number | null;
  avoidedLoss: number | null;
  emergencyCost: number | null;
  riskCount: number;
  avgResponseHours: number | null;
  series: { month: string; avoidedLoss: number; emergencyCost: number }[];
  topRiskSuppliers: { name: string; score: number }[];
};

export type OperationReport = {
  window: ReportWindow;
  funnel: { stage: string; count: number }[];
  overdueRate: number | null;
  overdueByRole: { roleCode: string; total: number; overdue: number; rate: number | null }[];
  riskTypeDistribution: { type: string; count: number }[];
  riskLevelDistribution: { level: string; count: number }[];
};

export type ResponseReport = {
  window: ReportWindow;
  events: {
    id: string;
    code: string;
    title: string;
    level: string;
    status: string;
    createdAt: string;
    responseHours: number | null;
    estimatedCost: number | null;
    actualCost: number | null;
    costDiff: number | null;
    proposalCount: number;
    experienceCards: number;
  }[];
  avgResponseHours: number | null;
  experienceCardTotal: number;
};

const MOCK_WINDOW: ReportWindow = { months: 6, since: '2026-01-20T00:00:00+00:00' };

export async function getExecutiveReport(months = 6) {
  return pick<ExecutiveReport>(
    () => apiGet('/reports/executive', { months }),
    async () => ({
      window: MOCK_WINDOW,
      netBenefit: 732000,
      avoidedLoss: 860000,
      emergencyCost: 128000,
      riskCount: 18,
      avgResponseHours: 5.2,
      series: [
        { month: '2026-02', avoidedLoss: 42000, emergencyCost: 12000 },
        { month: '2026-03', avoidedLoss: 58000, emergencyCost: 14000 },
        { month: '2026-04', avoidedLoss: 51000, emergencyCost: 9000 },
        { month: '2026-05', avoidedLoss: 76000, emergencyCost: 18000 },
        { month: '2026-06', avoidedLoss: 83000, emergencyCost: 16000 },
        { month: '2026-07', avoidedLoss: 86000, emergencyCost: 12800 },
      ],
      topRiskSuppliers: [
        { name: '苏州芯片封测厂', score: 92 },
        { name: '东莞电机', score: 78 },
        { name: '无锡精密', score: 66 },
        { name: '宁波微电', score: 53 },
      ],
    }),
  );
}

export async function getOperationReport(months = 6) {
  return pick<OperationReport>(
    () => apiGet('/reports/operation', { months }),
    async () => ({
      window: MOCK_WINDOW,
      funnel: [
        { stage: '发现风险', count: 18 },
        { stage: '建事件', count: 8 },
        { stage: '出方案', count: 5 },
        { stage: '批准', count: 4 },
        { stage: '执行完成', count: 3 },
      ],
      overdueRate: 0.08,
      overdueByRole: [
        { roleCode: 'scm_lead', total: 6, overdue: 1, rate: 0.1667 },
        { roleCode: 'purchaser', total: 5, overdue: 0, rate: 0 },
      ],
      riskTypeDistribution: [
        { type: '供应中断', count: 7 },
        { type: '物流中断', count: 5 },
        { type: '需求波动', count: 6 },
      ],
      riskLevelDistribution: [
        { level: 'high', count: 5 },
        { level: 'medium', count: 8 },
        { level: 'low', count: 5 },
      ],
    }),
  );
}

export async function getResponseReport(months = 6) {
  return pick<ResponseReport>(
    () => apiGet('/reports/response', { months }),
    async () => ({
      window: MOCK_WINDOW,
      events: [
        {
          id: 'inc-supplier-shutdown',
          code: 'INC-2026-019',
          title: '苏州芯片封测厂停产',
          level: 'high',
          status: 'closed',
          createdAt: '2026-07-10T02:00:00+00:00',
          responseHours: 9.5,
          estimatedCost: 150000,
          actualCost: 128000,
          costDiff: -22000,
          proposalCount: 3,
          experienceCards: 1,
        },
      ],
      avgResponseHours: 9.5,
      experienceCardTotal: 1,
    }),
  );
}
