import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import AutomationStatsCard from './index';

describe('AutomationStatsCard', () => {
  it('renders the rate, human-machine counts, and escalation rules returned by the API', () => {
    render(<AutomationStatsCard stats={{
      totalDecisions: 3,
      autoApproved: 2,
      escalated: 1,
      automationRate: 0.6667,
      escalationRate: 1 / 3,
      escalationReasons: {},
      escalationRules: [
        { code: 'inventory_risk_threshold', description: '库存风险指数大于 80' },
        { code: 'debate_not_converged', description: '多智能体辩论未收敛' },
      ],
    }} />);

    expect(screen.getByText('人机分工')).toBeInTheDocument();
    expect(screen.getByText('自动化率')).toBeInTheDocument();
    expect(screen.getByTestId('automation-rate')).toHaveTextContent('66.7%');
    expect(screen.getByText('自动放行')).toBeInTheDocument();
    expect(screen.getByText('升级人工')).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === '基于 3 条租户决策审计记录统计；命中以下任一规则即升级人工处理。')).toBeInTheDocument();
    expect(screen.getByText('库存风险指数大于 80')).toBeInTheDocument();
    expect(screen.getByText('多智能体辩论未收敛')).toBeInTheDocument();
  });
});
