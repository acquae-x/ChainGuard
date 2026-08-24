import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/runtime', () => ({
  history: { location: { search: '' }, push: vi.fn(), replace: vi.fn() },
  useModel: () => ({ setInitialState: vi.fn() }),
}));
vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  return { ...actual, Grid: { ...actual.Grid, useBreakpoint: () => ({ md: true, lg: true }) } };
});
vi.mock('@/components', () => ({ DegradeBanner: () => null }));
vi.mock('@/services/user', () => ({ login: vi.fn() }));
vi.mock('@/services/account', () => ({ startSsoLogin: vi.fn() }));
vi.mock('@/services/dataMode', () => ({ isApiMode: () => true }));

import LoginPage from './Login';

describe('LoginPage desktop layout', () => {
  it('allows both desktop grid tracks to shrink below intrinsic preview content', () => {
    render(<LoginPage />);

    expect(screen.getByTestId('login-page-layout')).toHaveStyle({
      gridTemplateColumns: 'minmax(0, 55%) minmax(0, 45%)',
    });
  });
});
