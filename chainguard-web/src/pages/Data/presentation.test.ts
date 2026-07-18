import { describe, expect, it } from 'vitest';
import { formatSupportHours } from './presentation';

describe('库存可支撑时长展示', () => {
  it('保留底层数值但最多显示两位小数', () => {
    expect(formatSupportHours(77.53846153846153)).toBe('77.54 小时');
    expect(formatSupportHours(77.5)).toBe('77.5 小时');
  });

  it('正确处理零值、空值和非法值', () => {
    expect(formatSupportHours(0)).toBe('0 小时');
    expect(formatSupportHours(null)).toBe('—');
    expect(formatSupportHours(undefined)).toBe('—');
    expect(formatSupportHours(Number.NaN)).toBe('—');
  });
});
