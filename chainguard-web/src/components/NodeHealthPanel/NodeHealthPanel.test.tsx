import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import NodeHealthPanel from './index';
import { dashboardConfig } from '@/pages/Dashboard/dashboardConfig';

const push = vi.fn();
vi.mock('@umijs/max', () => ({ history: { push: (...args: unknown[]) => push(...args) } }));

const MATERIAL_NODE = {
  nodeType: 'material',
  id: 'MAT-CRIT',
  name: '关键芯片',
  health: 'critical',
  healthLabel: '异常',
  reasons: [{
    code: 'support_hours_below_red',
    label: '库存支撑低于红线',
    detail: '库存支撑 15.0 小时，低于红线 24 小时',
    observed: { field: '库存支撑小时数', value: 15, unit: 'hour' },
    threshold: { value: 24, unit: 'hour', source: 'expert_default' },
    via: 'inventory',
    derivedFrom: null,
  }],
  metrics: { warningLevel: '红色预警', riskIndex: 82.3, supportHours: 15, currentStock: 300 },
  source: { table: 'materials', batch: { importJobId: 'job-1', fileName: 'materials.csv', source: 'csv_import' } },
  updatedAt: '2026-07-19T09:12:00+00:00',
  link: '/data/material?id=MAT-CRIT',
  relatedLinks: [],
};

const WAREHOUSE_NODE = {
  nodeType: 'warehouse',
  id: 'WH-A',
  name: '一号仓',
  health: 'critical',
  healthLabel: '异常',
  reasons: [{
    code: 'hosts_critical_material',
    label: '存放的物料处于异常',
    detail: '存放的物料「关键芯片」当前为异常',
    observed: { field: '关联物料健康', value: '异常', unit: null },
    threshold: null,
    via: 'inventory',
    derivedFrom: { nodeType: 'material', id: 'MAT-CRIT', name: '关键芯片', health: 'critical', link: '/data/material?id=MAT-CRIT' },
  }],
  metrics: { inventoryRowCount: 2, materialCount: 2 },
  source: { table: 'inventory', batch: null },
  updatedAt: '2026-07-19T09:20:00+00:00',
  // 仓库没有主数据，因而没有资料页——link 必须是 null，不是一个点不开的假链接
  link: null,
  relatedLinks: [{ label: '查看库存明细', link: '/data/inventory' }],
};

const BY_TYPE = [
  { nodeType: 'material', label: '物料', total: 1, critical: 1, warning: 0, healthy: 0, unknown: 0 },
  { nodeType: 'warehouse', label: '仓库', total: 1, critical: 1, warning: 0, healthy: 0, unknown: 0 },
  { nodeType: 'supplier', label: '供应商', total: 0, critical: 0, warning: 0, healthy: 0, unknown: 0, emptyReason: '当前租户还没有供应商主数据' },
  { nodeType: 'order', label: '订单', total: 0, critical: 0, warning: 0, healthy: 0, unknown: 0, emptyReason: '当前租户还没有未关闭的销售订单' },
];

const AVAILABLE = {
  available: true,
  code: null,
  scope: null,
  summary: { critical: 2, warning: 0, healthy: 0, unknown: 0, total: 2 },
  byType: BY_TYPE,
  nodes: [MATERIAL_NODE, WAREHOUSE_NODE],
  filtered: { total: 2, current: 1, pageSize: 50, nodeTypes: ['material', 'warehouse', 'supplier', 'order'], health: null, keyword: null },
  filters: {
    nodeTypes: BY_TYPE.map((row) => ({ value: row.nodeType, label: row.label })),
    healthStates: [
      { value: 'critical', label: '异常' }, { value: 'warning', label: '预警' },
      { value: 'healthy', label: '健康' }, { value: 'unknown', label: '数据不足' },
    ],
  },
  dataFreshness: { scope: 'resource_type', batches: [], latestNodeUpdatedAt: '2026-07-19T09:20:00+00:00' },
  limitations: [
    { code: 'CG-C023', message: '系统没有独立的仓库主数据，仓库节点由库存行的仓库字段聚合得出。' },
    { code: 'CG-C024', message: '只有物料节点的健康由库存风险引擎计算；其余不是独立评分模型。' },
  ],
  generatedAt: '2026-07-20T00:00:00+00:00',
};

const UNAVAILABLE = {
  available: false,
  code: 'CG-C021',
  message: '当前租户还没有任何业务实体数据，节点健康无法计算；请先完成数据导入。',
  scope: null,
  summary: null,
  byType: [],
  nodes: [],
  filtered: null,
  filters: null,
  dataFreshness: null,
  limitations: [{ code: 'CG-C021', message: '当前租户还没有任何业务实体数据。' }],
};

beforeEach(() => { push.mockReset(); });

describe('NodeHealthPanel', () => {
  it('F1 三色计数与「数据不足」单列，数字直接取自 summary', async () => {
    render(<NodeHealthPanel fetcher={async () => AVAILABLE} />);
    await screen.findByTestId('node-health');
    expect(screen.getByTestId('node-health-count-critical-value')).toHaveTextContent('2');
    expect(screen.getByTestId('node-health-count-warning-value')).toHaveTextContent('0');
    expect(screen.getByTestId('node-health-count-healthy-value')).toHaveTextContent('0');
    // 数据不足单独成列，绝不并入健康
    expect(screen.getByTestId('node-health-count-unknown-value')).toHaveTextContent('0');
  });

  it('F2 四类节点按固定顺序出现，空类型给出 emptyReason', async () => {
    render(<NodeHealthPanel fetcher={async () => AVAILABLE} />);
    await screen.findByTestId('node-health');
    const tags = screen.getByTestId('node-health-by-type');
    const order = ['material', 'warehouse', 'supplier', 'order'].map(
      (type) => tags.querySelector(`[data-testid="node-health-type-${type}"]`),
    );
    expect(order.every(Boolean)).toBe(true);
    expect(screen.getByTestId('node-health-empty-supplier')).toHaveTextContent('还没有供应商主数据');
    expect(screen.getByTestId('node-health-empty-order')).toBeTruthy();
  });

  it('F3 available=false 时只渲染说明，不渲染任何计数与节点行', async () => {
    render(<NodeHealthPanel fetcher={async () => UNAVAILABLE} />);
    await screen.findByTestId('node-health-unavailable');
    expect(screen.getByTestId('node-health-unavailable-message')).toHaveTextContent('还没有任何业务实体数据');
    expect(screen.getByTestId('node-health-code')).toHaveTextContent('CG-C021');
    expect(screen.queryByTestId('node-health-count-critical-value')).toBeNull();
    expect(screen.queryByTestId('node-health-table')).toBeNull();
    expect(screen.queryByTestId('node-health-by-type')).toBeNull();
  });

  it('F4 改变筛选器会以新参数重新请求（筛选由后端做，不在本地过滤）', async () => {
    const fetcher = vi.fn(async () => AVAILABLE);
    render(<NodeHealthPanel fetcher={fetcher} />);
    await screen.findByTestId('node-health');
    expect(fetcher).toHaveBeenCalledWith({ pageSize: 50 });

    await userEvent.click(screen.getByTestId('node-health-filter-health').querySelector('input')!);
    await userEvent.click(await screen.findByTitle('异常'));
    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledWith({ pageSize: 50, health: 'critical' });
    });
  });

  it('F5 节点跳转参数正确；仓库不渲染资料页链接', async () => {
    render(<NodeHealthPanel fetcher={async () => AVAILABLE} />);
    await screen.findByTestId('node-health');
    await userEvent.click(screen.getByTestId('node-health-link-material-MAT-CRIT'));
    expect(push).toHaveBeenCalledWith('/data/material?id=MAT-CRIT');
    expect(screen.queryByTestId('node-health-link-warehouse-WH-A')).toBeNull();
    expect(screen.getByTestId('node-health-nolink-warehouse-WH-A')).toHaveTextContent('无资料页');
  });

  it('F6 异常原因带观测值/阈值来源，传播型可跳回来源物料', async () => {
    render(<NodeHealthPanel fetcher={async () => AVAILABLE} />);
    await screen.findByTestId('node-health');
    const reason = screen.getByTestId('node-health-reason-material-MAT-CRIT-support_hours_below_red');
    expect(reason).toHaveTextContent('库存支撑 15.0 小时，低于红线 24 小时');
    expect(reason).toHaveTextContent('expert_default');

    await userEvent.click(screen.getByTestId('node-health-derived-warehouse-WH-A'));
    expect(push).toHaveBeenCalledWith('/data/material?id=MAT-CRIT');
  });

  it('F7 逐条渲染限制说明，含仓库口径与「非独立评分模型」声明', async () => {
    render(<NodeHealthPanel fetcher={async () => AVAILABLE} />);
    await screen.findByTestId('node-health');
    expect(screen.getByTestId('node-health-limitation-CG-C023')).toHaveTextContent('没有独立的仓库主数据');
    expect(screen.getByTestId('node-health-limitation-CG-C024')).toHaveTextContent('不是独立评分模型');
  });

  it('mine 模式展示范围依据，说明这些类型是怎么来的', async () => {
    const mine = {
      ...AVAILABLE,
      scope: { nodeTypes: ['warehouse'], isGlobal: false, matched: true, basis: '既有权限码（data:*:manage / risk:manage:*），未新增权限码' },
    };
    render(<NodeHealthPanel mode="mine" testIdPrefix="my-nodes" fetcher={async () => mine} />);
    await screen.findByTestId('my-nodes');
    expect(screen.getByTestId('my-nodes-scope')).toHaveTextContent('仓库');
    expect(screen.getByTestId('my-nodes-scope')).toHaveTextContent('未新增权限码');
  });
});

describe('dashboardConfig', () => {
  it('F8 四个写死的节点类 KPI 字面量已删除，节点计数只能来自面板', () => {
    const kpiKeys = Object.values(dashboardConfig).flatMap((config) => config.kpis.map((kpi) => kpi.key));
    // supplier=负责供应商异常数 / sku=本仓预警 SKU / order=受影响订单 / gap=物料缺口 SKU
    for (const fabricated of ['supplier', 'sku', 'order', 'gap']) {
      expect(kpiKeys).not.toContain(fabricated);
    }
    const titles = Object.values(dashboardConfig).flatMap((config) => config.kpis.map((kpi) => kpi.title));
    for (const fabricated of ['负责供应商异常数', '本仓预警 SKU', '受影响订单', '物料缺口 SKU']) {
      expect(titles).not.toContain(fabricated);
    }
    // 一线四角色改由「我的节点」面板承载
    for (const role of ['buyer', 'warehouse', 'sales', 'planner'] as const) {
      expect(dashboardConfig[role].second).toContain('myNodes');
    }
    // 管理者侧挂节点健康概览
    for (const role of ['boss', 'scm_lead', 'admin'] as const) {
      expect([...dashboardConfig[role].second, ...dashboardConfig[role].third]).toContain('nodeHealth');
    }
  });
});
