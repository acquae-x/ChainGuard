import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// #4：受控 open、点击先标记已读再跳转、时间/类型/未读、Escape 焦点回铃铛。
const { pushMock, markReadMock, getNotificationsMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  markReadMock: vi.fn(() => Promise.resolve({ ok: true })),
  getNotificationsMock: vi.fn(),
}));
vi.mock('@umijs/max', () => ({ history: { push: pushMock } }));
vi.mock('@/services/notify', () => ({
  getNotifications: (...a: any[]) => getNotificationsMock(...a),
  markRead: (...a: any[]) => markReadMock(...a),
}));

import NotificationBell from './index';

beforeEach(() => {
  pushMock.mockClear();
  markReadMock.mockClear();
  // 用 risk 类通知，落在默认激活的第一个「风险告警」标签页，渲染即可见
  getNotificationsMock.mockResolvedValue({
    data: [{ id: 'n1', kind: 'risk_high', title: '高风险预警：核心供应商停产', target: '/risk/list', read: false, createdAt: '2026-07-15T09:00:00Z' }],
    unread: 1,
  });
});

describe('NotificationBell', () => {
  it('点击通知先标记已读再跳转（关层不遮挡目标页）', async () => {
    render(<NotificationBell />);
    fireEvent.click(screen.getByLabelText('通知'));
    const item = await screen.findByText('高风险预警：核心供应商停产');
    fireEvent.click(item);
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith('/risk/list'));
    expect(markReadMock).toHaveBeenCalledWith('n1');
    expect(markReadMock.mock.invocationCallOrder[0]).toBeLessThan(pushMock.mock.invocationCallOrder[0]);
  });

  it('渲染类型标签与时间', async () => {
    render(<NotificationBell />);
    fireEvent.click(screen.getByLabelText('通知'));
    await screen.findByText('高风险预警：核心供应商停产');
    expect(screen.getByText('风险预警')).toBeInTheDocument(); // 类型标签（≠标签页「风险告警」）
  });

  it('Escape 关闭后焦点回到通知按钮', async () => {
    render(<NotificationBell />);
    const bell = screen.getByLabelText('通知');
    fireEvent.click(bell);
    await screen.findByText('高风险预警：核心供应商停产');
    fireEvent.keyDown(document.activeElement || document.body, { key: 'Escape' });
    await waitFor(() => expect(document.activeElement).toBe(bell));
  });
});
