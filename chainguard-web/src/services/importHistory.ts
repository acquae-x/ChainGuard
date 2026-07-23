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

export type ImportRowRejection = {
  row: number | null;
  reason: string;
  source: UnknownRecord;
  suggestion: string;
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
  rejections: ImportRowRejection[];
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

function repairSuggestion(reason: string): string {
  if (reason.includes('缺业务主键') || reason.includes('必填字段') || reason.includes('业务键为空')) return '补齐必填字段，或返回人工确认步骤修正字段映射后重新导入。';
  if (reason.includes('类型/格式非法')) return '按目标字段格式修正该值（例如成本使用纯数字），再重新导入。';
  if (reason.includes('非法外键')) return '先导入或选择租户内已存在的关联主数据，再重新导入该行。';
  if (reason.includes('敏感列') || reason.includes('不允许')) return '移除不允许导入的字段后重新上传，敏感数据不要写入导入文件。';
  if (reason.includes('未声明列')) return '将源字段映射到正确的目标字段，或从文件中移除无关列。';
  return '核对该行原文、字段映射和目标字段格式，修正后重新导入。';
}

function normalizeRejections(result: UnknownRecord, streaming: UnknownRecord): ImportRowRejection[] {
  const candidate = Array.isArray(streaming.rejections) ? streaming.rejections : Array.isArray(result.rejections) ? result.rejections : [];
  return candidate.map((value) => {
    const item = asRecord(value);
    const reason = firstString([item], ['reason'], '该行未通过导入校验');
    const rowValue = Number(item.row ?? item.rowNumber);
    return {
      row: Number.isFinite(rowValue) ? rowValue : null,
      reason,
      source: asRecord(item.source ?? item.payload),
      suggestion: repairSuggestion(reason),
    };
  });
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
    rejections: normalizeRejections(result, streaming),
    operator: firstString([job, options], ['operator']),
    time: firstString([job], ['updatedAt', 'createdAt']),
    createdAt: typeof job.createdAt === 'string' ? job.createdAt : undefined,
    updatedAt: typeof job.updatedAt === 'string' ? job.updatedAt : undefined,
    status: firstString([job], ['status']),
    message: firstString([result, streaming], ['message']),
  };
}
