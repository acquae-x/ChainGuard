import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// #6：真实逾期任务按 assigneeName 聚合（非硬编码 [3,1,2]）；无 task:manage 不显示操作列。
vi.mock('@umijs/max', () => ({ useAccess: () => ({ canTaskManage: false }) }));
const getTasksMock = vi.fn();
vi.mock('@/services/task', () => ({ getTasks: (...a: any[]) => getTasksMock(...a), urge: vi.fn() }));
vi.mock('echarts-for-react', () => ({ default: ({ option }: any) => <div data-testid="echart" data-option={JSON.stringify(option)} /> }));

import TaskOverdue from './Overdue';

describe('TaskOverdue 真实聚合', () => {
  it('按负责人姓名聚合，且无 task:manage 时无操作列', async () => {
    getTasksMock.mockResolvedValue({
      data: [
        { id: 't1', title: '补货', assignee: 'u-buyer', assigneeName: '张采购', dueAt: '2026-07-10T00:00:00Z', status: 'overdue' },
        { id: 't2', title: '催单', assignee: 'u-buyer', assigneeName: '张采购', dueAt: '2026-07-11T00:00:00Z', status: 'overdue' },
        { id: 't3', title: '盘点', assignee: 'u-wh', assigneeName: '李仓管', dueAt: '2026-07-09T00:00:00Z', status: 'overdue' },
      ],
      total: 3,
      success: true,
    });
    render(<TaskOverdue />);
    const chart = await screen.findByTestId('echart');
    const option = JSON.parse(chart.getAttribute('data-option') as string);
    const series = option.series[0].data;
    expect(series).not.toEqual([3, 1, 2]);
    const byName = Object.fromEntries(option.xAxis.data.map((n: string, i: number) => [n, series[i]]));
    expect(byName['张采购']).toBe(2);
    expect(byName['李仓管']).toBe(1);
    expect(option.xAxis.data).toContain('张采购');
    expect(option.xAxis.data).not.toContain('u-buyer');
    await waitFor(() => expect(screen.getByText('补货')).toBeInTheDocument());
    expect(screen.queryByText('催办')).toBeNull();
  });
});
