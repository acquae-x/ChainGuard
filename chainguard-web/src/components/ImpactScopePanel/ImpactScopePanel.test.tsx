import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ImpactScopePanel from './index';

const push = vi.fn();
vi.mock('@umijs/max', () => ({ history: { push: (...args: unknown[]) => push(...args) } }));

const GROUP_ORDER = ['material', 'inventory', 'warehouse', 'supplier', 'order', 'customer', 'task'];
const LABELS: Record<string, string> = {
  material: '物料', inventory: '库存', warehouse: '仓库', supplier: '供应商',
  order: '订单', customer: '客户', task: '任务',
};

function group(entityType: string, items: any[] = []) {
  return {
    entityType,
    label: LABELS[entityType],
    total: items.length,
    direct: items.filter((item) => item.degree === 'direct').length,
    indirect: items.filter((item) => item.degree === 'indirect').length,
    emptyReason: items.length ? null : `暂无${LABELS[entityType]}关联数据`,
    items,
  };
}

const SUPPLIER = {
  entityType: 'supplier', id: 'SUP-01', name: '苏州芯片封测厂', degree: 'direct',
  relation: { code: 'supplies_material', label: '为受影响物料供货', via: 'supplier_materials', path: ['material:MCU-A9', 'supplier_materials', 'supplier:SUP-01'] },
  status: { label: '停产', value: '停产' },
  fields: { region: '江苏', reliabilityScore: 62, supplierPrice: 48 },
  source: { table: 'suppliers', resourceType: 'supplier', scope: 'resource_type', batch: { importJobId: 'job-1', fileName: 'suppliers.csv', source: 'csv_import', finishedAt: '2026-07-18T09:00:00+00:00' } },
  updatedAt: '2026-07-18T09:12:00+00:00',
  link: '/data/supplier?id=SUP-01',
};

const CUSTOMER = {
  entityType: 'customer', id: 'CUS-01', name: '整机客户甲', degree: 'indirect',
  relation: { code: 'order_customer', label: '经由订单关联的客户', via: 'sales_orders', path: ['material:MCU-A9', 'order:SO-01', 'customer:CUS-01'] },
  status: { label: '年度框架', value: '年度框架' },
  fields: { customerLevel: 'A', region: '华东' },
  source: { table: 'customers', resourceType: 'customer', scope: 'resource_type', batch: null },
  updatedAt: '2026-07-18T09:20:00+00:00',
  link: '/data/customer?id=CUS-01',
};

const AVAILABLE = {
  available: true,
  code: null,
  scopeOf: { kind: 'risk', id: 'risk-auto-1', code: 'RISK-20260719-A001', name: 'MCU-A9' },
  seeds: [{ entityType: 'material', id: 'MCU-A9', name: '主控芯片', from: 'risk.details.material_id' }],
  summary: { total: 2, direct: 1, indirect: 1, byType: { supplier: 1, customer: 1 } },
  groups: GROUP_ORDER.map((type) => {
    if (type === 'supplier') return group(type, [SUPPLIER]);
    if (type === 'customer') return group(type, [CUSTOMER]);
    return group(type);
  }),
  traversal: { maxHops: 2, relations: ['supplies_material', 'order_customer'], note: '所有关系均沿 C2 实体表真实外键遍历，不做字符串模糊匹配。' },
  limitations: [{ code: 'CG-A042', message: '系统没有独立的仓库主数据，仓库分组由库存行的仓库字段聚合得出。' }],
  generatedAt: '2026-07-19T10:00:00+00:00',
};

const UNAVAILABLE = {
  available: false,
  code: 'CG-2511',
  message: '该风险/事件没有关联到租户内的有效物料或供应商，无法确定影响范围的起点。',
  scopeOf: { kind: 'risk', id: 'risk-x', code: 'RISK-X', name: '' },
  seeds: [],
  summary: { total: 0, direct: 0, indirect: 0, byType: {} },
  groups: [],
  traversal: { maxHops: 2, relations: [], note: null },
  limitations: [{ code: 'CG-2511', message: '该风险/事件没有关联到租户内的有效物料或供应商，无法确定影响范围的起点。' }],
  generatedAt: null,
};

describe('A04 影响范围面板', () => {
  beforeEach(() => { push.mockClear(); });

  it('F1 按固定顺序渲染全部分组，组头显示总数与直接/间接计数', () => {
    render(<ImpactScopePanel data={AVAILABLE} />);

    for (const type of GROUP_ORDER) {
      expect(screen.getByTestId(`impact-scope-group-${type}`)).toBeTruthy();
    }
    // 顺序必须稳定，不能因为哪一组为空就把它挪走或删掉
    const rendered = GROUP_ORDER.map((type) => screen.getByTestId(`impact-scope-group-${type}`));
    const positions = rendered.map((node) => node.compareDocumentPosition(rendered[0]));
    expect(positions[0]).toBe(0);

    expect(screen.getByTestId('impact-scope-total').textContent).toBe('2');
    expect(screen.getByTestId('impact-scope-direct-total').textContent).toContain('1');
    expect(screen.getByTestId('impact-scope-indirect-total').textContent).toContain('1');
    expect(screen.getByTestId('impact-scope-group-supplier-counts').textContent).toContain('直接 1');
    expect(screen.getByTestId('impact-scope-group-supplier-counts').textContent).toContain('间接 0');
  });

  it('F2 空组渲染 emptyReason，而不是一张空表格', async () => {
    render(<ImpactScopePanel data={AVAILABLE} />);
    await userEvent.click(screen.getByTestId('impact-scope-group-task'));

    expect(screen.getByTestId('impact-scope-empty-task').textContent).toContain('暂无任务关联数据');
    expect(screen.queryByTestId('impact-scope-table-task')).toBeNull();
  });

  it('F3 available=false 时只渲染限制说明，不渲染任何分组与计数', () => {
    render(<ImpactScopePanel data={UNAVAILABLE} />);

    expect(screen.getByTestId('impact-scope-unavailable-message').textContent).toContain('无法确定影响范围的起点');
    expect(screen.getByTestId('impact-scope-code').textContent).toContain('CG-2511');
    // 一个数字都不能有：不可用就是不可用，不能顺手显示"共波及 0 个"给人以已算过的错觉
    expect(screen.queryByTestId('impact-scope-total')).toBeNull();
    for (const type of GROUP_ORDER) {
      expect(screen.queryByTestId(`impact-scope-group-${type}`)).toBeNull();
    }
  });

  it('F4 明细行跳转到正确的业务对象资料页', async () => {
    const onNavigate = vi.fn();
    render(<ImpactScopePanel data={AVAILABLE} onNavigate={onNavigate} />);
    await userEvent.click(screen.getByTestId('impact-scope-group-supplier'));
    await userEvent.click(screen.getByTestId('impact-scope-link-supplier-SUP-01'));

    expect(onNavigate).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/data/supplier?id=SUP-01');
  });

  it('F5 逐条渲染 limitations，含仓库口径说明', () => {
    render(<ImpactScopePanel data={AVAILABLE} />);
    expect(screen.getByTestId('impact-scope-limitation-CG-A042').textContent).toContain('没有独立的仓库主数据');
  });

  it('间接影响带「间接」徽标与关系标签，并标明经由哪张表', async () => {
    render(<ImpactScopePanel data={AVAILABLE} />);
    await userEvent.click(screen.getByTestId('impact-scope-group-customer'));

    expect(screen.getByTestId('impact-scope-degree-customer-CUS-01').textContent).toBe('间接');
    expect(screen.getByTestId('impact-scope-relation-customer-CUS-01').textContent).toBe('经由订单关联的客户');
    // 直接/间接是两个分组各自的标注，供应商组要单独展开才挂载
    await userEvent.click(screen.getByTestId('impact-scope-group-supplier'));
    expect(screen.getByTestId('impact-scope-degree-supplier-SUP-01').textContent).toBe('直接');
  });

  it('批次来源标注为非本行血缘；无批次时如实说没有', async () => {
    render(<ImpactScopePanel data={AVAILABLE} />);
    await userEvent.click(screen.getByTestId('impact-scope-group-supplier'));
    await userEvent.click(screen.getByTestId('impact-scope-group-customer'));

    expect(screen.getByTestId('impact-scope-batch-supplier-SUP-01').textContent).toContain('非本行血缘');
    expect(screen.getByTestId('impact-scope-batch-customer-CUS-01').textContent).toContain('无导入批次记录');
  });

  it('testIdPrefix 可切换，同一面板能在事件页与风险抽屉各自定位', () => {
    render(<ImpactScopePanel data={AVAILABLE} testIdPrefix="incident-impact-scope" />);
    expect(screen.getByTestId('incident-impact-scope-total').textContent).toBe('2');
  });

  it('loading 与 error 各自成立，不会把加载中显示成"暂无影响"', () => {
    const { unmount } = render(<ImpactScopePanel loading />);
    expect(screen.queryByTestId('impact-scope')).toBeNull();
    unmount();

    render(<ImpactScopePanel error="接口 500" />);
    expect(screen.getByText('影响范围加载失败')).toBeTruthy();
  });
});
