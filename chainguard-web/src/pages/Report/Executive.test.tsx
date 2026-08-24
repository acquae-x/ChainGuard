import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// 回归防线：本页曾把 ¥732,000 / 18 / 5.2 直接写死在 JSX 里，不调用任何服务。
const getExecutiveReport = vi.fn();
vi.mock('@/services/report', () => ({ getExecutiveReport: (months: number) => getExecutiveReport(months) }));
vi.mock('@/runtime', () => ({ useModel: () => ({ initialState: { currentUser: { permissions: ['field:cost:view', 'field:profit:view'] } } }) }));
vi.mock('@/components', () => ({
  KpiCard: ({ title, value }: any) => <div>{title}:{String(value)}</div>,
  SensitiveField: ({ value }: any) => <span>{value}</span>,
}));
vi.mock('echarts-for-react', () => ({ default: () => <div data-testid="chart" /> }));

import Executive from './Executive';

const baseReport = {
  window: { months: 6, since: '2026-01-20T00:00:00+00:00' },
  netBenefit: 800000,
  avoidedLoss: 1000000,
  emergencyCost: 200000,
  riskCount: 2,
  avgResponseHours: 6,
  series: [{ month: '2026-07', avoidedLoss: 1000000, emergencyCost: 200000 }],
  topRiskSuppliers: [{ name: '苏州芯片封测厂', score: 92 }],
};

describe('经营看板', () => {
  it('渲染后端返回的净收益，而不是写死的常量', async () => {
    getExecutiveReport.mockResolvedValue(baseReport);
    render(<Executive />);
    expect(await screen.findByText('¥800,000')).toBeInTheDocument();
    expect(screen.queryByText('¥732,000')).not.toBeInTheDocument();
  });

  it('指标为 null 时显示「数据缺失」而不是 ¥0', async () => {
    getExecutiveReport.mockResolvedValue({
      ...baseReport,
      netBenefit: null,
      avoidedLoss: null,
      emergencyCost: null,
      avgResponseHours: null,
      riskCount: 0,
      series: [],
      topRiskSuppliers: [],
    });
    render(<Executive />);
    expect(await screen.findByText('所选时间范围内没有风险事件，经营指标暂不可测量。')).toBeInTheDocument();
    expect(screen.getAllByText('数据缺失').length).toBeGreaterThan(0);
    expect(screen.queryByText('¥0')).not.toBeInTheDocument();
  });
});
