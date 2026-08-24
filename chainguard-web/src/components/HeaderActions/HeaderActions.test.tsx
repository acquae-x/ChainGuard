import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// #3：窄屏（jsdom matchMedia matches:false → compact）只留 更多/通知/用户，搜索/上报收进「更多」。
vi.mock('@/runtime', () => ({ history: { push: vi.fn() } }));
vi.mock('@/services/user', () => ({ logout: vi.fn(), switchDemoRole: vi.fn() }));
vi.mock('@/services/mockData', () => ({ roleNames: {} }));
vi.mock('@/services/dataMode', () => ({ isApiMode: () => true }));
vi.mock('@/services/notify', () => ({ getNotifications: vi.fn().mockResolvedValue({ data: [], unread: 0 }), markRead: vi.fn() }));
vi.mock('../GlobalSearch', () => ({ default: () => <div data-testid="global-search" /> }));

import HeaderActions from './index';

describe('HeaderActions 375px 收纳', () => {
  it('窄屏保留通知与用户入口，搜索/上报收进「更多」', () => {
    render(<HeaderActions user={{ name: '王五', permissions: ['risk:event:create'] } as any} tenant={{ name: '演示企业' } as any} />);
    expect(screen.getByLabelText('通知')).toBeInTheDocument();
    expect(screen.getByLabelText('更多')).toBeInTheDocument();
    expect(screen.getByLabelText('用户菜单')).toBeInTheDocument();
    expect(screen.getByTestId('compact-header-actions')).toHaveStyle({
      position: 'fixed',
      top: '8px',
      right: '8px',
    });
    // 搜索在未展开的「更多」内，不在常驻栏
    expect(screen.queryByTestId('global-search')).toBeNull();
  });
});
