import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiGet, apiPost } = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));

vi.mock('../utils/request', () => ({
  apiGet,
  apiPost,
}));

import { confirmAndExecuteRecognizedJob, preflightRecognizedJob, syncErp } from './enterpriseImport';

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

  it('gives OCR preflight a timeout longer than server-side OCR so slow recognition is not cut off', async () => {
    // 回归守卫：OCR 预检在服务端同步跑识别，冷模型可达 11s+，超过全局 10s 超时。
    // 若这里退回默认超时，CI 冷模型下请求会在 OCR 完成前被掐断、误报「服务暂不可用」。
    apiPost.mockResolvedValue({ id: 'ocr-1', status: 'manual_review', result: {} });

    await preflightRecognizedJob('ocr-1');

    const [, , options] = apiPost.mock.calls[0];
    // 后端 OCR 自身超时默认 20s，前端必须显著高于它
    expect(options.timeoutMs).toBeGreaterThan(20_000);
  });
});
