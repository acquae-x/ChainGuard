type UnknownRecord = Record<string, unknown>;

export type ImportTableReport = {
  table: string;
  label: string;
  sourceRows: number;
  successRows: number;
  rejectedRows: number;
  inserted: number;
  updated: number;
  entityRows: number;
};

export type NormalizedImportHistoryJob = {
  id: string;
  type: string;
  total: number;
  sourceRows: number;
  success: number;
  successRows: number;
  failed: number;
  rejectedRows: number;
  reports: ImportTableReport[];
  operator: string;
  time: string;
  createdAt?: string;
  updatedAt?: string;
  status: string;
  message: string;
};

function asRecord(value: unknown): UnknownRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as UnknownRecord : {};
}

function firstNumber(sources: UnknownRecord[], keys: string[]): number {
  for (const source of sources) {
    if (!source) continue;
    for (const key of keys) {
      if (source[key] !== null && source[key] !== undefined && source[key] !== '') {
        const value = Number(source[key]);
        if (Number.isFinite(value)) return value;
      }
    }
  }
  return 0;
}

function firstString(sources: UnknownRecord[], keys: string[], fallback = '-'): string {
  for (const source of sources) {
    for (const key of keys) {
      const value = source[key];
      if (typeof value === 'string' && value.trim()) return value;
    }
  }
  return fallback;
}

function normalizeReport(value: unknown): ImportTableReport | null {
  const report = asRecord(value);
  if (!Object.keys(report).length) return null;
  const sources = [report];
  return {
    table: firstString(sources, ['table', 'type'], '-'),
    label: firstString(sources, ['label', 'table', 'type'], '-'),
    sourceRows: firstNumber(sources, ['sourceRows', 'total']),
    successRows: firstNumber(sources, ['successRows', 'success', 'imported']),
    rejectedRows: firstNumber(sources, ['rejectedRows', 'failed']),
    inserted: firstNumber(sources, ['inserted']),
    updated: firstNumber(sources, ['updated']),
    entityRows: firstNumber(sources, ['entityRows']),
  };
}

function normalizeReports(job: UnknownRecord, result: UnknownRecord, streaming: UnknownRecord): ImportTableReport[] {
  const candidate = [result.reports, result.tableReports, streaming.reports, streaming.tableReports, job.reports]
    .find((value) => Array.isArray(value) && value.length > 0);
  const values = Array.isArray(candidate) && candidate.length > 0
    ? candidate
    : Object.keys(streaming).length && ('table' in streaming || 'sourceRows' in streaming)
      ? [streaming]
      : [];
  return values.map(normalizeReport).filter((report): report is ImportTableReport => report !== null);
}

export function normalizeImportHistoryJob(value: unknown): NormalizedImportHistoryJob {
  const job = asRecord(value);
  const result = asRecord(job.result);
  const streaming = asRecord(result.streaming);
  const sources = [result, streaming, job];
  const total = firstNumber(sources, ['total', 'sourceRows']);
  const success = firstNumber(sources, ['success', 'successRows', 'imported']);
  const failed = firstNumber(sources, ['failed', 'rejectedRows']);
  const options = asRecord(job.options);
  return {
    id: firstString([job], ['id', 'jobId']),
    type: firstString([job], ['importType', 'type']),
    total,
    sourceRows: total,
    success,
    successRows: success,
    failed,
    rejectedRows: failed,
    reports: normalizeReports(job, result, streaming),
    operator: firstString([job, options], ['operator']),
    time: firstString([job], ['updatedAt', 'createdAt']),
    createdAt: typeof job.createdAt === 'string' ? job.createdAt : undefined,
    updatedAt: typeof job.updatedAt === 'string' ? job.updatedAt : undefined,
    status: firstString([job], ['status']),
    message: firstString([result, streaming], ['message']),
  };
}
