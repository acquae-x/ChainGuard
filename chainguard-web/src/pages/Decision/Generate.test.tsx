import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@umijs/max', () => ({ Access: ({ children }: any) => children, history: {}, useAccess: () => ({ canSubmitHigh: false, canModifyDecision: false, readonly: true }), useParams: () => ({ incidentId: 'inc-1' }) }));
vi.mock('@/services/decision', () => ({ getDraft: vi.fn().mockResolvedValue(undefined), getProposalsForIncident: vi.fn().mockResolvedValue([{ id: 'p-1', name: '应急方案', tag: 'recommended', totalCost: 1, leadTimeImpact: 1, customerImpact: 1, highValueCustomers: 1, residualRisk: 'low', reason: '理由', views: {}, historyExperience: { matched: true, count: 1, conclusions: ['备用供应商 + 关键订单空运'], sources: ['inc-older-mat-1'] } }]), generateProposals: vi.fn(), recalc: vi.fn(), saveDraft: vi.fn(), submitForApproval: vi.fn(), getDecisionReadiness: vi.fn().mockResolvedValue({ ready: true, level: 'complete', blocking: [], degraded: [] }) }));
vi.mock('@/services/incident', () => ({ getIncident: vi.fn().mockResolvedValue({ code: 'INC-1', title: '事件', level: 'high', owner: '负责人', loss: 1, status: 'deciding' }) }));
vi.mock('@/components', () => ({ AgentProgress: () => null, DecisionTrace: () => null, EmptyGuide: () => null, RiskTag: () => null, SensitiveField: ({ value }: any) => value, StatusTag: () => null }));

import DecisionGenerate from './Generate';

describe('DecisionGenerate history experience', () => {
  it('shows a tenant-scoped history experience badge and source on proposal cards', async () => {
    render(<DecisionGenerate />);
    await screen.findByText('引用历史经验（1）');
    expect(screen.getByText('关键结论：备用供应商 + 关键订单空运')).toBeInTheDocument();
    expect(screen.getByText('来源：inc-older-mat-1')).toBeInTheDocument();
  });
});
