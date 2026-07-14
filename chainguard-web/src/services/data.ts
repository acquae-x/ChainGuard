// 数据管理与导入服务（Phase 2 §2.2 双模式）。
// API 模式的容量/文件可用性预检以服务端结果为准，前端仅保留字段映射交互预览。
// api 模式：基础资料表读写走 /data/{type}；导入 commit 走后端多步流水线
// upload → preflight → confirm → execute → 轮询进度（保留原始 File 上传，服务端解析落库）。
// logistics（物流）后端无对应 resource_type，保留 mock。
import * as XLSX from 'xlsx';
import { customers, inventories, materials, orders, suppliers } from './mockData';
import { appendAudit } from './workflowStore';
import { isApiMode, pick } from './dataMode';
import { apiGet, apiPost } from '../utils/request';

const API_RESOURCE_TYPES = new Set(['material', 'supplier', 'customer', 'order', 'inventory']);
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export type ImportType = 'material' | 'supplier' | 'customer' | 'order' | 'inventory';
export type ImportFieldType = 'string' | 'number' | 'date' | 'enum';
export type ImportField = {
  key: string;
  label: string;
  aliases: string[];
  type: ImportFieldType;
  required?: boolean;
  unique?: boolean;
  enumValues?: string[];
};
export type ParsedImportFile = {
  fileName: string;
  headers: string[];
  rows: Record<string, unknown>[];
  total: number;
};
export type FieldMatch = {
  source: string;
  target?: string;
  confidence: number;
};
export type ImportValidationError = {
  row: number;
  field: string;
  type: 'required' | 'type' | 'enum' | 'duplicate';
  message: string;
};
export type ImportValidationResult = {
  total: number;
  success: number;
  failed: number;
  validRows: Record<string, unknown>[];
  mappedRows: Array<Record<string, unknown> & { __rowNumber: number }>;
  errors: ImportValidationError[];
  errorSummary: Record<string, number>;
};
export type ImportCommitResult = {
  ok: boolean;
  batchId: string;
  success: number;
  failed: number;
  total: number;
  attempted?: number;
  // 服务端预检未通过且未强制继续时返回，携带预检报告供页面展示
  preflightBlocked?: boolean;
  preflightReport?: any;
};

export async function preflightUpload(file: File, type: ImportType) {
  if (!isApiMode()) return null;
  const form = new FormData();
  form.append('file', file, file.name);
  const uploaded = await apiPost<any>(`/imports/upload?type=${encodeURIComponent(type)}`, form);
  return apiPost<any>(`/imports/${uploaded.id}/preflight`, {});
}

const importDefinitions: Record<ImportType, { label: string; sheetName: string; fields: ImportField[]; sample: Record<string, unknown> }> = {
  material: {
    label: '物料',
    sheetName: '物料模板',
    fields: [
      { key: 'id', label: '物料编号', aliases: ['物料编码', '编码', 'sku', 'materialcode'], type: 'string', required: true, unique: true },
      { key: 'name', label: '物料名称', aliases: ['名称', '品名', 'materialname'], type: 'string', required: true },
      { key: 'category', label: '分类', aliases: ['物料分类', '类别', 'category'], type: 'string', required: true },
      { key: 'stock', label: '库存数量', aliases: ['库存', '现有库存', 'stock'], type: 'number' },
      { key: 'safety', label: '安全库存', aliases: ['安全库存数量', 'safetystock'], type: 'number' },
      { key: 'cost', label: '单位成本', aliases: ['成本', '单价', 'cost'], type: 'number' }
    ],
    sample: { 物料编号: 'MAT-001', 物料名称: 'MCU-A9', 分类: '芯片', 库存数量: 1200, 安全库存: 3000, 单位成本: 18.5 }
  },
  supplier: {
    label: '供应商',
    sheetName: '供应商模板',
    fields: [
      { key: 'name', label: '供应商名称', aliases: ['供应商', '名称', 'vendorname', 'suppliername'], type: 'string', required: true, unique: true },
      { key: 'leadTime', label: '交期天数', aliases: ['交期', '供货周期', 'leadtime'], type: 'number', required: true },
      { key: 'supplierPrice', label: '供应商报价', aliases: ['报价', '采购价', '单价', 'price'], type: 'number', required: true },
      { key: 'status', label: '状态', aliases: ['供应商状态', 'status'], type: 'enum', enumValues: ['正常', '停产', '可替代'] }
    ],
    sample: { 供应商名称: '宁波微电科技', 交期天数: 3, 供应商报价: 21.2, 状态: '可替代' }
  },
  customer: {
    label: '客户',
    sheetName: '客户模板',
    fields: [
      { key: 'id', label: '客户编号', aliases: ['客户编码', '编码', 'customercode'], type: 'string', required: true, unique: true },
      { key: 'name', label: '客户名称', aliases: ['客户', '名称', 'customername'], type: 'string', required: true },
      { key: 'customerLevel', label: '客户等级', aliases: ['等级', '客户级别', 'level'], type: 'enum', required: true, enumValues: ['A', 'B', 'C'] },
      { key: 'contract', label: '合同信息', aliases: ['合同', '合同条款', 'contract'], type: 'string' }
    ],
    sample: { 客户编号: 'CUS-001', 客户名称: '长三角机器人集团', 客户等级: 'A', 合同信息: '年度框架合同' }
  },
  order: {
    label: '订单',
    sheetName: '订单模板',
    fields: [
      { key: 'orderNo', label: '订单号', aliases: ['订单编号', '单号', 'orderno'], type: 'string', required: true, unique: true },
      { key: 'customer', label: '客户名称', aliases: ['客户', 'customer'], type: 'string', required: true },
      { key: 'dueAt', label: '交付日期', aliases: ['交期', '要求交付日', 'duedate'], type: 'date', required: true },
      { key: 'amount', label: '订单金额', aliases: ['金额', '合同金额', 'amount'], type: 'number', required: true },
      { key: 'profit', label: '预计利润', aliases: ['利润', '毛利', 'profit'], type: 'number' }
    ],
    sample: { 订单号: 'SO-001', 客户名称: '长三角机器人集团', 交付日期: '2026-07-20', 订单金额: 420000, 预计利润: 76000 }
  },
  inventory: {
    label: '库存',
    sheetName: '库存模板',
    fields: [
      { key: 'warehouse', label: '仓库', aliases: ['仓库名称', '库房', 'warehouse'], type: 'string', required: true },
      { key: 'material', label: '物料名称', aliases: ['物料', '品名', 'material'], type: 'string', required: true },
      { key: 'quantity', label: '可用数量', aliases: ['库存数量', '数量', 'quantity'], type: 'number', required: true },
      { key: 'supportHours', label: '可支撑小时', aliases: ['支撑小时', '可支撑时长', 'supporthours'], type: 'number' }
    ],
    sample: { 仓库: '上海一仓', 物料名称: 'MCU-A9', 可用数量: 1200, 可支撑小时: 36 }
  }
};

const importBatches: Array<{ id: string; type: string; success: number; failed: number; operator: string; time: string; status: string; duplicatePolicy?: string; mode?: string }> = [
  { id: 'batch-1', type: '供应商', success: 126, failed: 2, operator: '企业管理员', time: '2026-07-09 14:00', status: 'succeeded', duplicatePolicy: 'skip', mode: '仅正确行' }
];

function normalize(value: unknown) {
  return String(value ?? '').trim().toLowerCase().replace(/[\s_\-（）()\/\\]/g, '');
}

function similarity(left: string, right: string) {
  if (left === right) return 1;
  if (!left || !right) return 0;
  if (left.includes(right) || right.includes(left)) return 0.82;
  const matrix = Array.from({ length: left.length + 1 }, () => Array(right.length + 1).fill(0));
  for (let i = 0; i <= left.length; i += 1) matrix[i][0] = i;
  for (let j = 0; j <= right.length; j += 1) matrix[0][j] = j;
  for (let i = 1; i <= left.length; i += 1) {
    for (let j = 1; j <= right.length; j += 1) {
      matrix[i][j] = Math.min(
        matrix[i - 1][j] + 1,
        matrix[i][j - 1] + 1,
        matrix[i - 1][j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1)
      );
    }
  }
  return 1 - matrix[left.length][right.length] / Math.max(left.length, right.length);
}

const logisticsRows: any[] = [{ id: 'log-1', line: '沪深干线', eta: '2026-07-11', status: 'watching' }];

export async function getDataTable(type: string) {
  return pick(
    async () => {
      // logistics 无后端资源，回退 mock
      if (!API_RESOURCE_TYPES.has(type)) {
        return { data: logisticsRows, total: logisticsRows.length, success: true };
      }
      return apiGet(`/data/${type}`);
    },
    async () => {
      const map: Record<string, any[]> = { material: materials, supplier: suppliers, customer: customers, order: orders, inventory: inventories, logistics: logisticsRows };
      return { data: map[type] || [], total: (map[type] || []).length, success: true };
    },
  );
}

// 新建基础资料：api 模式 POST /data/{type}，mock 写入内存 store 并留审计痕迹（02 §6）。
export async function createRecord(type: string, values: { name: string; remark?: string }) {
  const name = values.name?.trim();
  if (!name) throw new Error('名称不能为空');
  return pick(
    async () => {
      if (!API_RESOURCE_TYPES.has(type)) return createRecordMock(type, values);
      return apiPost(`/data/${type}`, { name, remark: values.remark || '' });
    },
    async () => createRecordMock(type, values),
  );
}

async function createRecordMock(type: string, values: { name: string; remark?: string }) {
  const id = `${type}-${Date.now()}`;
  const name = values.name?.trim();
  if (!name) throw new Error('名称不能为空');
  const record: Record<string, any> = (
    type === 'material' ? { id, name, category: '未分类', stock: 0, safety: 0, cost: 0 }
    : type === 'supplier' ? { id, name, status: '正常', leadTime: 7, supplierPrice: 0 }
    : type === 'customer' ? { id, name, customerLevel: 'C', contract: values.remark || '—', owner: '销售/客服' }
    : type === 'order' ? { id, orderNo: name, customer: '—', dueAt: new Date().toISOString().slice(0, 10), amount: 0, profit: 0, status: 'pending' }
    : type === 'inventory' ? { id, warehouse: name, material: '—', quantity: 0, supportHours: 0, status: 'new' }
    : { id, line: name, eta: new Date().toISOString().slice(0, 10), status: 'watching' }
  );
  const map: Record<string, any[]> = { material: materials, supplier: suppliers, customer: customers, order: orders, inventory: inventories, logistics: logisticsRows };
  (map[type] || logisticsRows).unshift(record);
  appendAudit('新建资料', type, id, name, { remark: values.remark || '' });
  return record;
}

// 对接后端时：enterprise_ingest.py / import_preflight.py / streaming_import.py。
export async function parseFile(file: File): Promise<ParsedImportFile> {
  const workbook = XLSX.read(await file.arrayBuffer(), { type: 'array', cellDates: true });
  const sheet = workbook.Sheets[workbook.SheetNames[0]];
  if (!sheet) throw new Error('文件中没有可读取的工作表');
  const matrix = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1, defval: '', raw: true });
  const headers = (matrix[0] || []).map((value) => String(value).trim()).filter(Boolean);
  if (!headers.length) throw new Error('文件第一行没有有效表头');
  const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: '', raw: true });
  return { fileName: file.name, headers, rows, total: rows.length };
}

export async function getFieldMapping(type: ImportType, headers: string[] = []) {
  const definition = importDefinitions[type];
  const used = new Set<string>();
  const matches: FieldMatch[] = headers.map((source) => {
    const sourceName = normalize(source);
    const ranked = definition.fields
      .filter((field) => !used.has(field.key))
      .map((field) => ({
        field,
        score: Math.max(...[field.label, field.key, ...field.aliases].map((name) => similarity(sourceName, normalize(name))))
      }))
      .sort((a, b) => b.score - a.score);
    const best = ranked[0];
    if (best && best.score >= 0.45) used.add(best.field.key);
    return { source, target: best?.score >= 0.45 ? best.field.key : undefined, confidence: best?.score || 0 };
  });
  return { type, fields: definition.fields, matches };
}

export async function getImportTemplate(type: ImportType) {
  const definition = importDefinitions[type];
  return { fileName: `${type}-template.xlsx`, sheetName: definition.sheetName, rows: [definition.sample] };
}

export async function validateRows(
  rows: Record<string, unknown>[],
  mapping: Record<string, string | undefined>,
  fields: ImportField[]
): Promise<ImportValidationResult> {
  const errors: ImportValidationError[] = [];
  const uniqueFields = fields.filter((field) => field.unique);
  const seen = new Map<string, Set<string>>(uniqueFields.map((field) => [field.key, new Set()]));
  const mappedRows = rows.map((sourceRow, index) => {
    const mapped: Record<string, unknown> & { __rowNumber: number } = { __rowNumber: index + 2 };
    Object.entries(mapping).forEach(([source, target]) => {
      if (target) mapped[target] = sourceRow[source];
    });

    fields.forEach((field) => {
      const value = mapped[field.key];
      const empty = value === '' || value === null || value === undefined;
      if (field.required && empty) {
        errors.push({ row: index + 2, field: field.label, type: 'required', message: `${field.label}为必填项` });
        return;
      }
      if (empty) return;
      if (field.type === 'number' && (typeof value === 'boolean' || Number.isNaN(Number(value)))) {
        errors.push({ row: index + 2, field: field.label, type: 'type', message: `${field.label}必须是数字` });
      }
      if (field.type === 'date' && !(value instanceof Date) && typeof value !== 'number' && Number.isNaN(Date.parse(String(value)))) {
        errors.push({ row: index + 2, field: field.label, type: 'type', message: `${field.label}必须是有效日期` });
      }
      if (field.type === 'enum' && field.enumValues && !field.enumValues.includes(String(value).trim())) {
        errors.push({ row: index + 2, field: field.label, type: 'enum', message: `${field.label}仅允许：${field.enumValues.join('、')}` });
      }
      if (field.unique) {
        const normalizedValue = normalize(value);
        const values = seen.get(field.key)!;
        if (values.has(normalizedValue)) {
          errors.push({ row: index + 2, field: field.label, type: 'duplicate', message: `${field.label}与文件内已有行重复` });
        } else {
          values.add(normalizedValue);
        }
      }
    });
    return mapped;
  });
  const failedRows = new Set(errors.map((error) => error.row));
  const validRows = mappedRows.filter((row) => !failedRows.has(row.__rowNumber));
  const errorSummary = errors.reduce<Record<string, number>>((summary, error) => {
    summary[error.type] = (summary[error.type] || 0) + 1;
    return summary;
  }, {});
  return { total: rows.length, success: validRows.length, failed: failedRows.size, validRows, mappedRows, errors, errorSummary };
}

type CommitParams = {
  type: ImportType;
  validation: ImportValidationResult;
  onlyValidRows: boolean;
  duplicatePolicy: 'skip' | 'overwrite' | 'merge';
  // 原始文件：api 模式上传给后端服务端解析落库；mock 模式忽略
  file?: File;
  // 服务端预检未通过时，用户显式确认"仍要导入"后置 true，才越过预检闸门
  force?: boolean;
};

export async function commitImport(values: CommitParams): Promise<ImportCommitResult> {
  return pick(
    async () => {
      if (!values.file) return commitImportMock(values);
      // 1) 上传原始文件
      const form = new FormData();
      form.append('file', values.file, values.file.name);
      const uploaded = await apiPost<any>(`/imports/upload?type=${encodeURIComponent(values.type)}`, form);
      const jobId = uploaded.id;
      // 2) 服务端预检——失败则中止并回传报告，不再静默继续（导入质量闸门）
      let preflight: any;
      try {
        preflight = await apiPost<any>(`/imports/${jobId}/preflight`, {});
      } catch {
        preflight = { status: 'failed', result: { error: '预检执行失败' } };
      }
      const preflightFailed = preflight?.status === 'failed' || preflight?.result?.canProceed === false;
      // P1-4：磁盘不足与解析失败都是硬闸门，"仍要导入"不适用
      const hardBlocked = preflight?.result?.verdict === 'INSUFFICIENT_DISK' || preflight?.result?.verdict === 'PARSE_ERROR';
      if (hardBlocked) {
        return {
          ok: false,
          batchId: jobId,
          success: 0,
          failed: values.validation.total,
          total: values.validation.total,
          attempted: 0,
          preflightBlocked: true,
          preflightReport: preflight?.result ?? preflight,
        };
      }
      if (preflightFailed && !values.force) {
        return {
          ok: false,
          batchId: jobId,
          success: 0,
          failed: values.validation.total,
          total: values.validation.total,
          attempted: 0,
          preflightBlocked: true,
          preflightReport: preflight?.result ?? preflight,
        };
      }
      // 3) 确认导入选项（用户已在预检失败后显式选择继续，或预检通过）
      await apiPost(`/imports/${jobId}/confirm`, { values: { duplicatePolicy: values.duplicatePolicy, onlyValidRows: values.onlyValidRows, force: !!values.force } });
      // 4) 触发异步执行
      await apiPost(`/imports/${jobId}/execute`, {});
      // 5) 轮询进度直到完成
      let job: any = uploaded;
      for (let i = 0; i < 40; i += 1) {
        job = await apiGet<any>(`/imports/${jobId}`, undefined, { silent: true });
        if (['succeeded', 'failed', 'done', 'completed', 'rolled_back'].includes(job.status)) break;
        await sleep(1200);
      }
      const result = job.result || {};
      const total = result.total ?? values.validation.total;
      const success = result.success ?? result.imported ?? 0;
      const failed = result.failed ?? Math.max(total - success, 0);
      return { ok: job.status !== 'failed', batchId: jobId, success, failed, total, attempted: total };
    },
    async () => commitImportMock(values),
  );
}

async function commitImportMock(values: CommitParams): Promise<ImportCommitResult> {
  const errorsByRow = new Map<number, ImportValidationError[]>();
  values.validation.errors.forEach((error) => errorsByRow.set(error.row, [...(errorsByRow.get(error.row) || []), error]));
  const acceptedRows = values.validation.mappedRows.filter((row) => {
    const rowErrors = errorsByRow.get(row.__rowNumber) || [];
    return rowErrors.length === 0 || (values.duplicatePolicy !== 'skip' && rowErrors.every((error) => error.type === 'duplicate'));
  });
  const success = acceptedRows.length;
  const failed = values.validation.total - success;
  const attempted = values.onlyValidRows ? acceptedRows.length : values.validation.total;
  const batchId = `batch-${Date.now()}`;
  importBatches.unshift({
    id: batchId,
    type: importDefinitions[values.type].label,
    success,
    failed,
    operator: '当前用户',
    time: new Date().toLocaleString('zh-CN', { hour12: false }),
    status: 'succeeded',
    duplicatePolicy: values.duplicatePolicy,
    mode: values.onlyValidRows ? '仅正确行' : '全量尝试'
  });
  return { ok: true, batchId, success, failed, total: values.validation.total, attempted };
}

export async function getImportHistory() {
  return pick(
    async () => {
      const res = await apiGet<any>('/imports');
      const list: any[] = Array.isArray(res) ? res : res.data || [];
      const data = list.map((job) => ({
        id: job.id,
        type: job.importType || job.type || '-',
        success: job.result?.success ?? job.result?.imported ?? 0,
        failed: job.result?.failed ?? 0,
        operator: job.operator || '-',
        time: job.createdAt || job.updatedAt || '-',
        status: job.status,
      }));
      return { data };
    },
    async () => ({ data: importBatches }),
  );
}

export async function rollback(id: string) {
  return pick(
    () => apiPost(`/imports/${id}/rollback`, {}),
    async () => ({ ok: true, id }),
  );
}
