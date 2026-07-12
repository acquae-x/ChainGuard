import { incident, tenant } from './mockData';

// 对接后端时：行业模板读取 ChainGuard/demo_assets 与 thresholds.yaml。
export async function getTemplates() {
  return [
    { id: 'electronics', name: '电子制造', desc: '芯片、PCB、关键物料齐套与替代供应商模板' },
    { id: 'auto', name: '汽车零部件', desc: '长周期件与多级供应商协同模板' },
    { id: 'food', name: '食品饮料', desc: '保质期、区域仓与物流时效模板' }
  ];
}

export async function saveProgress(values: any) {
  return { ok: true, progress: values };
}

export async function applyTemplate(templateId: string) {
  return { ok: true, tenant: { ...tenant, industry: templateId } };
}

// 对接后端时：POST /decisions/scenario/{event_id}，event_id=supplier_shutdown。
export async function startDrillIncident() {
  return incident;
}
