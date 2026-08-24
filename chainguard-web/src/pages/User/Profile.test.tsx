import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// #8：mustChangePassword=true 明确显示管理员重置文案，标题不再是工作台。
const useModelMock = vi.fn();
vi.mock('@/runtime', () => ({ history: { push: vi.fn() }, useModel: () => useModelMock() }));
vi.mock('@/services/user', () => ({ changePassword: vi.fn(), logout: vi.fn() }));

import Profile from './Profile';

describe('Profile 首次强制改密', () => {
  it('mustChangePassword=true 显示管理员重置提示', () => {
    useModelMock.mockReturnValue({ initialState: { currentUser: { mustChangePassword: true } } });
    render(<Profile />);
    expect(screen.getByText('管理员已重置您的密码')).toBeInTheDocument();
    expect(screen.getByText('首次登录，请修改密码')).toBeInTheDocument();
    expect(screen.queryByText('工作台')).toBeNull();
  });

  it('普通进入显示个人设置', () => {
    useModelMock.mockReturnValue({ initialState: { currentUser: { mustChangePassword: false } } });
    render(<Profile />);
    expect(screen.getByText('个人设置')).toBeInTheDocument();
  });
});
