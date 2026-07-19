import { apiGet, apiPost } from '../utils/request';
import type { ImportField } from './data';

export type ImportMode = 'mixed' | 'structured' | 'ocr' | 'erp';

export type ImportCatalogType = {
  value: string;
  label: string;
  group: string;
  source_table: string;
  erp_resource: string;
  entity: boolean;
};

export type Recognition = {
  recognizedType?: string | null;
  label: string;
  confidence: number;
  requiresConfirmation: boolean;
  reasons: string[];
  candidates: Array<{ type: string; label: string; score: number; reasons: string[] }>;
};

export type EnterpriseImportResult = Record<string, unknown> & {
  recognition?: Recognition;
  canProceed?: boolean;
  manualReview?: { confirmationLevel?: 'full' | 'light' };
};

export type ClassifiedFile = {
  jobId: string;
  fileName: string;
  mode: Exclude<ImportMode, 'erp'>;
  recognition: Recognition;
  selectedType?: string;
  preflight?: EnterpriseImportResult;
  manualConfirmed?: boolean;
  fieldMapping?: Record<string, string | undefined>;
  mappingFields?: ImportField[];
};

export type EnterpriseImportJob = {
  id: string;
  jobId?: string;
  status: string;
  result?: EnterpriseImportResult;
};

export async function getEnterpriseImportCatalog() {
  return apiGet<{ modes: Array<{ value: ImportMode; label: string; description: string }>; types: ImportCatalogType[] }>('/imports/catalog');
}

export async function uploadForRecognition(file: File, mode: Exclude<ImportMode, 'erp'>): Promise<ClassifiedFile> {
  const form = new FormData();
  form.append('file', file, file.name);
  const job = await apiPost<any>(`/imports/upload?type=auto&mode=${mode}`, form);
  return {
    jobId: job.id,
    fileName: job.fileName,
    mode,
    recognition: job.options?.recognition,
    selectedType: job.options?.recognition?.recognizedType || undefined,
  };
}

export async function uploadBatchForRecognition(files: File[]) {
  const form = new FormData();
  files.forEach((file) => form.append('files', file, file.name));
  const result = await apiPost<any>('/imports/batch/classify', form);
  return {
    ...result,
    files: (result.files || []).map((item: ClassifiedFile) => ({
      ...item,
      selectedType: item.recognition?.recognizedType || undefined,
    })),
  };
}

export async function preflightRecognizedJob(jobId: string): Promise<EnterpriseImportJob> {
  return apiPost<EnterpriseImportJob>(`/imports/${jobId}/preflight`, {});
}

export async function confirmAndExecuteRecognizedJob(file: ClassifiedFile): Promise<EnterpriseImportJob> {
  await apiPost(`/imports/${file.jobId}/confirm`, {
    values: {
      confirmedType: file.selectedType,
      manualConfirmed: file.mode === 'ocr' ? !!file.manualConfirmed : false,
      fieldMapping: Object.fromEntries(Object.entries(file.fieldMapping || {}).filter((entry): entry is [string, string] => !!entry[1])),
      duplicatePolicy: 'merge',
      onlyValidRows: true,
    },
  });
  await apiPost(`/imports/${file.jobId}/execute`, {});
  for (let index = 0; index < 50; index += 1) {
    const job = await apiGet<EnterpriseImportJob>(`/imports/${file.jobId}`, undefined, { silent: true });
    if (['succeeded', 'failed', 'rolled_back'].includes(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`${file.fileName} 执行超时，请到导入历史查看`);
}

export async function testErpConnection(values: { baseUrl: string; apiKey?: string }) {
  return apiPost<any>('/imports/erp/test', { values });
}

export async function previewErp(values: { baseUrl: string; apiKey?: string; types: string[] }) {
  return apiPost<any>('/imports/erp/preview', { values });
}

export async function syncErp(values: { baseUrl: string; apiKey?: string; types: string[] }): Promise<EnterpriseImportJob> {
  return apiPost<EnterpriseImportJob>(
    '/imports/erp/sync',
    { values: { ...values, confirmed: true } },
    { timeoutMs: 5 * 60 * 1000 },
  );
}
