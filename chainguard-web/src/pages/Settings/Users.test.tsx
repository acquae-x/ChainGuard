import { describe, it, expect, vi } from 'vitest';
import { App } from 'antd';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// #11：重置密码必须弹确认对话框（Popconfirm）。
vi.mock('@umijs/max', () => ({ history: { push: vi.fn() } }));
vi.mock('@/services/settings', () => ({
  getUsers: vi.fn().mockResolvedValue({ data: [{ id: 'u1', name: '张三', phone: '13800000001', email: 'z@x.com', roleCode: 'buyer', dataScope: 'custom', status: 'active' }], total: 1, success: true }),
  getDepartments: vi.fn().mockResolvedValue([]),
  createUser: vi.fn(),
  resetUserPassword: vi.fn().mockResolvedValue({ temporaryPassword: 'Temp@1234' }),
}));
vi.mock('@/constants/status', () => ({ ROLE_LABELS: { buyer: '采购人员' } }));

import Users from './Users';

describe('Users 重置密码确认框', () => {
  it('点击「重置密码」弹出确认对话框', async () => {
    render(<App><Users /></App>);
    await waitFor(() => expect(screen.getByText('张三')).toBeInTheDocument());
    fireEvent.click(screen.getByText('重置密码'));
    expect(await screen.findByText('确认重置该用户密码？')).toBeInTheDocument();
  });
});
