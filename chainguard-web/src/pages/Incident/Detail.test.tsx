import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// A04 回归：无 task:* 权限的验收角色打开事件「影响范围」时曾整页白屏——
// /tasks 返回 403 让 Promise.all 整体 reject，把已经 200 的影响范围一起拖垮。
// 断言两件事：无任务权限时不请求 /tasks 且影响范围照常渲染；任务请求真的失败时同样不阻断。
const accessMock = { canTask: false, canManageIncident: false };
vi.mock('@umijs/max', () => ({
  useAccess: () => accessMock,
  useParams: () => ({ id: 'inc-a04' }),
  history: { push: vi.fn(), replace: vi.fn(), location: { pathname: '/incident/inc-a04' } },
}));

const getTasksMock = vi.fn();
const getImpactMock = vi.fn();
vi.mock('@/services/task', () => ({ getTasks: (...a: any[]) => getTasksMock(...a) }));
vi.mock('@/services/incident', () => ({
  getIncident: vi.fn(async () => ({
    id: 'inc-a04', code: 'INC-A04', title: '主控芯片断供', level: 'high', status: 'evaluating',
    owner: '张三', createdAt: '2026-07-01', sourceRiskIds: [], loss: 1000, cost: 200,
  })),
  getImpact: (...a: any[]) => getImpactMock(...a),
  getTimeline: vi.fn(async () => []),
  updateIncident: vi.fn(),
  addIncidentNote: vi.fn(),
  closeIncident: vi.fn(),
}));
vi.mock('@/services/decision', () => ({ getProposalsForIncident: vi.fn(async () => []) }));
vi.mock('@/components', () => ({
  ImpactScopePanel: ({ testIdPrefix }: any) => <div data-testid={testIdPrefix}>影响范围面板</div>,
  RiskExplanationDrawer: () => null,
  RiskTag: () => null,
  SensitiveField: ({ value }: any) => <span>{value}</span>,
  StatusTag: () => null,
}));

import IncidentDetailPage from './Detail';

describe('事件详情：任务权限不得阻断影响范围', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    accessMock.canTask = false;
    getImpactMock.mockResolvedValue({ available: true, summary: { total: 5, direct: 3, indirect: 2 } });
  });

  it('无 task:* 权限时不请求 /tasks，影响范围仍然渲染', async () => {
    render(<IncidentDetailPage />);
    await waitFor(() => expect(screen.getByTestId('incident-impact-scope')).toBeInTheDocument());
    expect(getTasksMock).not.toHaveBeenCalled();
    expect(screen.queryByText('任务')).toBeNull();
  });

  it('有权限但 /tasks 失败时降级为空任务，不影响整页渲染', async () => {
    accessMock.canTask = true;
    getTasksMock.mockRejectedValue(Object.assign(new Error('请求失败（403）'), { httpStatus: 403 }));
    render(<IncidentDetailPage />);
    await waitFor(() => expect(screen.getByTestId('incident-impact-scope')).toBeInTheDocument());
    expect(getTasksMock).toHaveBeenCalled();
    expect(screen.getByText('INC-A04 主控芯片断供')).toBeInTheDocument();
  });
});
