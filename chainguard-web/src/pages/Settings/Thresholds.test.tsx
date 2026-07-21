import { describe, expect, it, vi } from 'vitest';
import { App } from 'antd';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const snapshot = {
  recommendationId: 'calibration-1',
  sample: { totalRows: 8, effectiveRows: 8, timeRange: { from: '2026-07-01T00:00:00+00:00', to: '2026-07-08T00:00:00+00:00' }, confidence: { score: 50, note: '达到最小样本。' } },
  comparison: {
    expert: { thresholds: { inventory_warning: { yellow_support_hours: 48, red_support_hours: 24, inventory_risk_trigger: 70 } }, riskWeights: { shortage_urgency: 0.35, order_importance: 0.25, transit_delay: 0.2, external_event: 0.2 } },
    suggested: { thresholds: { inventory_warning: { yellow_support_hours: 36, red_support_hours: 18, inventory_risk_trigger: 55 } }, riskWeights: { shortage_urgency: 0.4, order_importance: 0.2, transit_delay: 0.2, external_event: 0.2 } },
    active: { approved: false },
  },
  calculation: { weightNote: '基于 8 条历史决策的皮尔逊相关归一化建议', trigger: { _note: '基于失败记录 P25 计算。' }, approvalGate: '只有管理员确认后才写入已批准配置。' },
  drift: { driftDetected: true, severity: 'critical', successRateDrop: 0.2, successRate: 0.6, findings: ['相对基线下降 20%。'], notificationCount: 1, recommendedAction: 'review_rollback', thresholds: { warnDrop: 0.05, criticalDrop: 0.15 } },
};

const services = vi.hoisted(() => ({
  getCalibrationGovernance: vi.fn(),
  confirmCalibrationGovernance: vi.fn(),
}));
services.getCalibrationGovernance.mockResolvedValue(snapshot);
services.confirmCalibrationGovernance.mockResolvedValue({ ok: true });
vi.mock('@/services/settings', () => services);

import Thresholds from './Thresholds';

describe('Thresholds calibration governance', () => {
  it('shows comparison, drift reasons and requires explicit confirmation', async () => {
    render(<App><Thresholds /></App>);
    expect(await screen.findByText('数据驱动建议 vs 专家默认值')).toBeInTheDocument();
    expect(screen.getByText('漂移严重超限')).toBeInTheDocument();
    expect(screen.getByText('缺货紧急度')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '人工确认并应用' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认应用' }));
    await waitFor(() => expect(services.confirmCalibrationGovernance).toHaveBeenCalledWith('calibration-1'));
  });
});
