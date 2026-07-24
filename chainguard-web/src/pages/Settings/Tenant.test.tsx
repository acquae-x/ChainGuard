import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

const getTenant = vi.fn();
const saveTenant = vi.fn();
const setInitialState = vi.fn();
vi.mock('@/services/settings', () => ({
  getTenant: () => getTenant(),
  saveTenant: (values: any) => saveTenant(values),
}));
vi.mock('@umijs/max', () => ({
  useModel: () => ({ initialState: { tenant }, setInitialState }),
}));

import TenantSettings from './Tenant';

const tenant = {
  id: 'tenant-demo', name: '华东精密制造有限公司', industry: '电子制造', scale: '200-1000',
  status: 'active' as const, plan: 'trial' as const, trialEndAt: '2026-08-08',
  demoDataFlag: true, timezone: 'Asia/Shanghai',
};

describe('企业信息', () => {
  it('展示时区口径，并将保存操作真实提交到租户设置接口', async () => {
    getTenant.mockResolvedValue(tenant);
    saveTenant.mockResolvedValue(tenant);
    render(<TenantSettings />);

    await waitFor(() => expect(getTenant).toHaveBeenCalledTimes(1));
    expect(screen.getByText(/今日、本周、本月/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => expect(saveTenant).toHaveBeenCalledWith(expect.objectContaining({ timezone: 'Asia/Shanghai' })));
  });
});
