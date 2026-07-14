// P0-2 统一口径：方案列表 / 审批摘要 / 方案对比共用同一套"缺失即数据缺失"格式化。
// 后端把未知指标落为 null，前端禁止把 null 渲染成 ¥0 / 0 天 / 0 单。

// 类型守卫：false 分支可将 nullable 联合类型收窄为非空（供 RiskTag 等严格 props 使用）
export const isMissing = (value: unknown): value is null | undefined | '' => value === null || value === undefined || value === '';

export const MISSING_TEXT = '数据缺失';

export const riskLabel = (value?: string | null): string =>
  isMissing(value) ? MISSING_TEXT : value === 'low' ? '低' : value === 'medium' ? '中' : value === 'high' ? '高' : String(value);

export const daysLabel = (value?: number | null): string => (isMissing(value) ? MISSING_TEXT : `${value} 天`);

export const countLabel = (value?: number | null, suffix = '单'): string => (isMissing(value) ? MISSING_TEXT : `${value} ${suffix}`);

export const customerLabel = (impact?: number | null, highValue?: number | null): string =>
  isMissing(impact) ? MISSING_TEXT : `${impact} 单 / 高等级 ${isMissing(highValue) ? '未知' : highValue}`;

export const moneyLabel = (value?: number | null): string => (isMissing(value) ? MISSING_TEXT : `¥${Number(value).toLocaleString()}`);
