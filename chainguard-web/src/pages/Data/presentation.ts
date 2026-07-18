export function formatSupportHours(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '—';
  return `${numeric.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 小时`;
}
