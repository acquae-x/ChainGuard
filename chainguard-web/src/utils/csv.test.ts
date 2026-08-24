import { describe, expect, it } from 'vitest';
import { parseCsv, serializeCsv } from './csv';

describe('UTF-8 BOM CSV', () => {
  it('quotes commas, quotes and line breaks and round-trips them', () => {
    const text = serializeCsv([{ 名称: 'A, "关键"', 备注: '第一行\n第二行' }]);
    expect(text.startsWith('\uFEFF')).toBe(true);
    expect(parseCsv(text)).toEqual([
      ['名称', '备注'],
      ['A, "关键"', '第一行\n第二行'],
    ]);
  });
});
