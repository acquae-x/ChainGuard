import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }));

vi.mock('../utils/request', () => ({
  apiGet: vi.fn(),
  apiPost,
}));

import { syncErp } from './enterpriseImport';

describe('enterpriseImport ERP sync', () => {
  beforeEach(() => apiPost.mockReset());

  it('allows a long-running full ERP synchronization to finish', async () => {
    apiPost.mockResolvedValue({ id: 'erp-1', status: 'succeeded' });

    await syncErp({
      baseUrl: 'http://127.0.0.1:8452',
      types: ['material', 'inventory_snapshot'],
    });

    expect(apiPost).toHaveBeenCalledWith(
      '/imports/erp/sync',
      {
        values: {
          baseUrl: 'http://127.0.0.1:8452',
          types: ['material', 'inventory_snapshot'],
          confirmed: true,
        },
      },
      { timeoutMs: 5 * 60 * 1000 },
    );
  });
});
