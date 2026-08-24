import { beforeEach, describe, expect, it, vi } from 'vitest';

const runtime = vi.hoisted(() => ({ history: { location: { pathname: '/settings/integration' }, push: vi.fn() } }));
vi.mock('@/runtime', () => runtime);
vi.mock('antd', () => ({ message: { error: vi.fn(), success: vi.fn() } }));

import { apiPost } from './request';
import { useBackendState } from '@/services/dataMode';

const response = (status: number, data: unknown) => Promise.resolve(new Response(JSON.stringify(data), {
  status,
  headers: { 'content-type': 'application/json' },
}));

describe('normalizeError 对 5xx 的分类', () => {
  beforeEach(() => {
    useBackendState.getState().reset();
    vi.stubGlobal('fetch', vi.fn());
  });

  // 后端用 503 表达业务级拒绝（凭证加密未启用 = CG-2802），响应带完整错误信封。
  // 曾经这类响应被一律判为网络故障，界面会弹「后端服务暂不可用……部分数据可能为
  // 离线演示数据」——后端其实是健康的，管理员会被引去排查服务而不是去配密钥。
  it('带错误码的 503 属于业务错误，不标记后端不可用', async () => {
    vi.mocked(fetch).mockReturnValueOnce(response(503, { code: 'CG-2802', message: '凭证加密未启用，不能保存 ERP 凭证', traceId: 't-1' }));

    await expect(apiPost('/settings/integrations/erp', {})).rejects.toMatchObject({
      code: 'CG-2802',
      httpStatus: 503,
      message: '凭证加密未启用，不能保存 ERP 凭证',
    });

    expect(useBackendState.getState().down).toBe(false);
  });

  // 开发代理在后端真不可达时返回裸 5xx，没有错误信封——这才是降级黄条的场景。
  it('不带错误码的 503 仍判为后端不可达', async () => {
    vi.mocked(fetch).mockReturnValueOnce(response(503, {}));

    await expect(apiPost('/settings/integrations/erp', {})).rejects.toMatchObject({ isNetwork: true });

    expect(useBackendState.getState().down).toBe(true);
  });

  it('无响应的网络错误仍判为后端不可达', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error('Network Error'));

    await expect(apiPost('/settings/integrations/erp', {})).rejects.toMatchObject({ isNetwork: true });

    expect(useBackendState.getState().down).toBe(true);
  });
});
