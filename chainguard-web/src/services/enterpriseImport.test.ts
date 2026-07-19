import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiGet, apiPost } = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));

vi.mock('../utils/request', () => ({
  apiGet,
  apiPost,
}));

import { confirmAndExecuteRecognizedJob, syncErp } from './enterpriseImport';

describe('enterpriseImport ERP sync', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset(); });

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

  it('passes the reviewed OCR field mapping to the existing confirm API', async () => {
    apiPost.mockResolvedValue({});
    apiGet.mockResolvedValue({ id: 'ocr-1', status: 'succeeded', result: { successRows: 1, rejectedRows: 0 } });

    await confirmAndExecuteRecognizedJob({
      jobId: 'ocr-1', fileName: 'material.png', mode: 'ocr', selectedType: 'material', manualConfirmed: true,
      recognition: { label: '物料主数据', confidence: 1, requiresConfirmation: true, reasons: [], candidates: [] },
      fieldMapping: { 物料编码: 'material_id', 物料名称: 'material_name', 成本: 'standard_cost', 备注: undefined },
    });

    expect(apiPost).toHaveBeenNthCalledWith(1, '/imports/ocr-1/confirm', {
      values: {
        confirmedType: 'material', manualConfirmed: true,
        fieldMapping: { 物料编码: 'material_id', 物料名称: 'material_name', 成本: 'standard_cost' },
        duplicatePolicy: 'merge', onlyValidRows: true,
      },
    });
  });
});
