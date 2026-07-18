import { describe, expect, it } from 'vitest';
import { normalizeImportHistoryJob } from './importHistory';

describe('导入历史公共字段兼容', () => {
  it('读取企业导入 sourceRows/successRows/rejectedRows 和逐表报告', () => {
    const row = normalizeImportHistoryJob({
      id: 'enterprise-1', importType: 'enterprise', status: 'succeeded', operator: '验收员',
      createdAt: '2026-07-18T01:00:00Z', updatedAt: '2026-07-18T01:01:00Z',
      result: {
        sourceRows: 111460, successRows: 111460, rejectedRows: 0,
        tableReports: [{ table: 'materials', sourceRows: 240 }],
      },
    });
    expect(row).toMatchObject({ total: 111460, sourceRows: 111460, success: 111460, successRows: 111460, failed: 0, rejectedRows: 0, operator: '验收员' });
    expect(row.reports).toHaveLength(1);
    expect(row.time).toBe('2026-07-18T01:01:00Z');
  });

  it('兼容旧 total/success/failed 与 streaming 结果', () => {
    expect(normalizeImportHistoryJob({ id: 'old', result: { total: 2, success: 1, failed: 1 } })).toMatchObject({ total: 2, success: 1, failed: 1 });
    const stream = normalizeImportHistoryJob({ id: 'stream', result: { reports: [], tableReports: [], streaming: { table: 'materials', sourceRows: 3, successRows: 2, rejectedRows: 1 } } });
    expect(stream).toMatchObject({ total: 3, success: 2, failed: 1 });
    expect(stream.reports).toEqual([expect.objectContaining({ table: 'materials', sourceRows: 3, successRows: 2, rejectedRows: 1 })]);
  });
});
