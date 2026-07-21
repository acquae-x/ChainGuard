import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

// 回归防线：本页曾 onChange={() => message.success('数据范围已更新')}，且暗示行级隔离已生效。
const getDataScopes = vi.fn();
const saveDataScopes = vi.fn();
vi.mock('@/services/settings', () => ({
  getDataScopes: () => getDataScopes(),
  saveDataScopes: (roles: any) => saveDataScopes(roles),
}));

import Scopes from './Scopes';

const view = {
  roles: [
    { code: 'scm_lead', name: '供应链负责人', scope: 'all', userCount: 2 },
    { code: 'buyer', name: '采购人员', scope: 'custom', userCount: 3 },
  ],
  version: 1,
  configured: true,
  enforced: false,
};

describe('数据权限', () => {
  it('后端 enforced=false 时必须明确提示尚未生效，不得暗示已在隔离数据', async () => {
    getDataScopes.mockResolvedValue({ ...view, enforced: false });
    render(<Scopes />);
    expect(await screen.findByText('数据范围配置尚未在查询层生效')).toBeInTheDocument();
    expect(screen.queryByText('数据范围已在查询层生效')).not.toBeInTheDocument();
  });

  it('后端 enforced=true 时说明生效口径，且不再显示待生效警告', async () => {
    getDataScopes.mockResolvedValue({ ...view, enforced: true });
    render(<Scopes />);
    expect(await screen.findByText('数据范围已在查询层生效')).toBeInTheDocument();
    expect(screen.queryByText('数据范围配置尚未在查询层生效')).not.toBeInTheDocument();
  });

  it('未改动时保存按钮禁用，改动后保存会真的写后端', async () => {
    getDataScopes.mockResolvedValue(view);
    saveDataScopes.mockResolvedValue({ ...view, version: 2 });
    render(<Scopes />);
    await screen.findByText('供应链负责人');

    // antd 会在两个中文字之间插入空格，可访问名是「保 存」
    const saveButton = screen.getByRole('button', { name: /保\s*存/ });
    expect(saveButton).toBeDisabled();

    // 改第一行的数据范围：全企业 -> 本部门
    await userEvent.click(screen.getAllByRole('combobox')[0]);
    await userEvent.click(await screen.findByTitle('本部门'));

    await waitFor(() => expect(saveButton).toBeEnabled());
    await userEvent.click(saveButton);

    await waitFor(() => expect(saveDataScopes).toHaveBeenCalledTimes(1));
    expect(saveDataScopes.mock.calls[0][0].scm_lead).toBe('dept');
  });
});
