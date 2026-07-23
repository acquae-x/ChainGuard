import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

// 回归防线：本页曾 onFinish={() => message.success('审批流已保存')}，弹提示但从不落库。
const getApprovalChain = vi.fn();
const saveApprovalChain = vi.fn();
vi.mock('@/services/settings', () => ({
  getApprovalChain: () => getApprovalChain(),
  saveApprovalChain: (values: any) => saveApprovalChain(values),
}));

import ApprovalSettings from './Approval';

const chain = {
  levels: {
    low: { approver: 'scm_lead', countersign: [] },
    medium: { approver: 'scm_lead', countersign: [] },
    high: { approver: 'boss', countersign: ['finance'] },
  },
  financeCountersign: true,
  version: 3,
  source: 'expert',
  configured: true,
};

describe('审批流配置', () => {
  it('展示后端已保存的审批链与版本号', async () => {
    getApprovalChain.mockResolvedValue(chain);
    render(<ApprovalSettings />);
    expect(await screen.findByText('当前版本 v3')).toBeInTheDocument();
    // 高风险描述由真实配置推导，而不是写死的文案
    expect(await screen.findByText('老板/总经理 审批 + 财务人员 会签')).toBeInTheDocument();
  });

  it('点击保存会真的调用后端写接口', async () => {
    getApprovalChain.mockResolvedValue(chain);
    saveApprovalChain.mockResolvedValue({ ...chain, version: 4 });
    render(<ApprovalSettings />);
    await screen.findByText('当前版本 v3');

    // antd 会在两个中文字之间插入空格，可访问名是「保 存」
    await userEvent.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => expect(saveApprovalChain).toHaveBeenCalledTimes(1));
    const payload = saveApprovalChain.mock.calls[0][0];
    expect(payload.levels.high.approver).toBe('boss');
    expect(payload.levels.high.countersign).toEqual(['finance']);
  });
});
