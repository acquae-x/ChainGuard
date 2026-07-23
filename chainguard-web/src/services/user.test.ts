import { beforeEach, describe, expect, it, vi } from 'vitest';

const request = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  clearToken: vi.fn(),
  getToken: vi.fn(),
  setToken: vi.fn(),
}));

vi.mock('../utils/request', () => request);
vi.mock('./dataMode', () => ({
  DATA_MODE: 'api',
  isApiMode: () => true,
}));

import { login } from './user';

describe('API login error ownership', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps the request layer silent because the login page renders the error once', async () => {
    const error = Object.assign(new Error('请求过于频繁，请稍后重试'), {
      httpStatus: 429,
      code: 'CG-1006',
    });
    request.apiPost.mockRejectedValue(error);

    await expect(login({
      account: 'acceptance-missing@batch1.local',
      password: 'wrong',
    })).rejects.toBe(error);

    expect(request.apiPost).toHaveBeenCalledWith(
      '/auth/login',
      {
        account: 'acceptance-missing@batch1.local',
        password: 'wrong',
      },
      { skipAuth: true, silent: true },
    );
  });
});
