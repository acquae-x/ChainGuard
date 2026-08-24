import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RiskExplanationDrawer from './index';

const push = vi.fn();
vi.mock('@/runtime', () => ({ history: { push: (...args: unknown[]) => push(...args) } }));

const getRiskExplanation = vi.fn();
// A04：抽屉第五段「影响范围」走独立端点，这里默认返回"不可用"，
// 让本文件继续只测 A03 的四段，互不干扰。
const getRiskImpactScope = vi.fn();
vi.mock('@/services/risk', () => ({
  getRiskExplanation: (id: string) => getRiskExplanation(id),
  getRiskImpactScope: (id: string) => getRiskImpactScope(id),
}));

const COMPUTED = {
  available: true,
  risk: { id: 'risk-auto-1', code: 'RISK-20260719-A001', level: 'high', score: 78.75, status: 'new' },
  verdict: {
    mode: 'computed',
    warningLevel: '红色预警',
    riskIndex: 78.75,
    triggerThreshold: 70,
    thresholdSource: 'expert_default',
    shouldTriggerResponse: true,
    rule: '库存风险指数 78.75 超过触发阈值 70（主因：缺货紧迫度）',
    narrative: ['当前库存 300，小时消耗 20，可支撑 15 小时。'],
  },
  drivers: [
    { key: 'shortage_urgency', label: '缺货紧迫度', metric: '库存支撑小时数', unit: 'hour', score: 100, weight: 0.35, contribution: 35, currentValue: 15, threshold: { yellow: 48, red: 24 }, comparison: 'below_red' },
    { key: 'order_importance', label: '关键订单覆盖', metric: '关键订单覆盖率', unit: 'ratio', score: 95, weight: 0.25, contribution: 23.75, currentValue: 0.05, threshold: null, comparison: null },
  ],
  deltas: null,
  evidence: [
    { entity: 'inventory', id: 'INV-SH-001', name: '上海一仓', fields: { onHandQty: 300, safetyStockQty: 960 }, updatedAt: '2026-07-19T10:00:00+00:00', link: '/data/inventory?id=INV-SH-001' },
  ],
  provenance: { scope: 'resource_type', note: '最近一次导入批次（非本行血缘）', batches: [], unknownResources: ['inventory'] },
  decisionLink: { contextKeys: ['inventory.current_stock'], materialId: 'MCU-A9', incidentId: null, canCreateIncident: true },
  limitations: [{ code: 'missing_safety_stock', message: '安全库存缺失，已用「日消耗×24 小时」替代，该值为估算而非实测。' }],
};

describe('A03 风险解释抽屉', () => {
  beforeEach(() => {
    push.mockClear();
    getRiskExplanation.mockReset();
    getRiskImpactScope.mockReset();
    getRiskImpactScope.mockResolvedValue({
      available: false, code: 'CG-2511', message: '无影响范围起点',
      groups: [], summary: { total: 0, direct: 0, indirect: 0, byType: {} },
      limitations: [{ code: 'CG-2511', message: '无影响范围起点' }],
    });
  });

  it('F1 渲染结论、当前值/阈值对比与驱动因素贡献', async () => {
    getRiskExplanation.mockResolvedValue(COMPUTED);
    render(<RiskExplanationDrawer riskId="risk-auto-1" open onClose={() => {}} />);

    // 按 testid 唯一取值：同一数值也出现在触发规则文案里，文本匹配会命中多个节点。
    await waitFor(() => expect(screen.getByTestId('risk-explanation-index')).toHaveTextContent('78.75'));
    expect(screen.getByTestId('risk-explanation-threshold')).toHaveTextContent('70');
    expect(screen.getByTestId('risk-explanation-warning-level')).toHaveTextContent('红色预警');
    expect(screen.getByTestId('risk-explanation-threshold-source')).toHaveTextContent('阈值来源：专家默认');
    // 当前值与红黄线必须同屏可读
    expect(screen.getByTestId('risk-driver-shortage_urgency-current')).toHaveTextContent('库存支撑小时数：15 小时');
    expect(screen.getByTestId('risk-driver-shortage_urgency-threshold')).toHaveTextContent('黄线 48 / 红线 24（低于红线）');
    // 比率类当前值按百分比呈现，不能直接把 0.05 摆出来
    expect(screen.getByTestId('risk-driver-order_importance-current')).toHaveTextContent('关键订单覆盖率：5.0%');
    expect(screen.getByText('当前库存 300，小时消耗 20，可支撑 15 小时。')).toBeInTheDocument();
  });

  it('结论区的指数锚点唯一，不会被触发规则里的同一数值污染', async () => {
    getRiskExplanation.mockResolvedValue(COMPUTED);
    render(<RiskExplanationDrawer riskId="risk-auto-1" open onClose={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('risk-explanation-index')).toBeInTheDocument());
    // 规则文案确实含同一数值——这正是模糊选择器会翻车的原因，锚点必须各自唯一。
    expect(screen.getByTestId('risk-explanation-rule')).toHaveTextContent('库存风险指数 78.75 超过触发阈值 70');
    expect(screen.getAllByTestId('risk-explanation-index')).toHaveLength(1);
    expect(screen.getAllByTestId('risk-explanation-threshold')).toHaveLength(1);
  });

  it('F2 不可解释时只渲染限制说明，不出现任何指数或阈值数字', async () => {
    getRiskExplanation.mockResolvedValue({
      available: false,
      code: 'CG-2513',
      message: '物料缺少库存记录',
      risk: { id: 'risk-x', code: 'R-X', level: 'medium' },
      verdict: null, drivers: [], deltas: null, evidence: [],
      provenance: { scope: 'resource_type', batches: [] },
      decisionLink: null,
      limitations: [{ code: 'CG-2513', message: '物料缺少库存记录' }],
    });
    render(<RiskExplanationDrawer riskId="risk-x" open onClose={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('risk-explanation-unavailable-title')).toHaveTextContent('当前无法生成风险解释'));
    expect(screen.getByTestId('risk-explanation-code')).toHaveTextContent('错误码：CG-2513');
    expect(screen.queryByTestId('risk-explanation-index')).not.toBeInTheDocument();
    expect(screen.queryByTestId('risk-explanation-threshold')).not.toBeInTheDocument();
    expect(screen.queryByTestId('risk-explanation-drivers')).not.toBeInTheDocument();
  });

  it('F3 无对比基线时明说首次计算，不编造变化', async () => {
    getRiskExplanation.mockResolvedValue(COMPUTED);
    render(<RiskExplanationDrawer riskId="risk-auto-1" open onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText('首次计算，无对比基线。')).toBeInTheDocument());
    expect(screen.queryByText(/较上次扫描/)).not.toBeInTheDocument();
  });

  it('F4 证据卡片可跳转到对应资料页', async () => {
    const onClose = vi.fn();
    getRiskExplanation.mockResolvedValue(COMPUTED);
    const user = (await import('@testing-library/user-event')).default.setup();
    render(<RiskExplanationDrawer riskId="risk-auto-1" open onClose={onClose} />);

    await waitFor(() => expect(screen.getByTestId('risk-evidence-inventory-INV-SH-001')).toBeInTheDocument());
    expect(screen.getByTestId('risk-evidence-inventory-INV-SH-001')).toHaveTextContent('上海一仓');
    expect(screen.getByText('更新时间：2026-07-19T10:00:00+00:00')).toBeInTheDocument();
    await user.click(screen.getByTestId('risk-evidence-link-inventory-INV-SH-001'));
    expect(push).toHaveBeenCalledWith('/data/inventory?id=INV-SH-001');
    expect(onClose).toHaveBeenCalled();
  });

  it('F5 批次来源标明为资源类型级而非本行血缘', async () => {
    getRiskExplanation.mockResolvedValue({
      ...COMPUTED,
      provenance: {
        scope: 'resource_type',
        note: '最近一次导入批次（非本行血缘）',
        batches: [{ resourceType: 'inventory', importJobId: 'job-1', fileName: '库存.csv', source: 'csv', finishedAt: '2026-07-19T09:00:00+00:00' }],
        unknownResources: [],
      },
    });
    render(<RiskExplanationDrawer riskId="risk-auto-1" open onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText('最近一次导入批次（非本行血缘）')).toBeInTheDocument());
    expect(screen.getByText('库存.csv')).toBeInTheDocument();
  });

  it('外部录入风险展示来源标注，不展示编造的指标推导', async () => {
    getRiskExplanation.mockResolvedValue({
      available: true,
      risk: { id: 'risk-1', code: 'RISK-1', level: 'high', score: 92, status: 'incident_created' },
      verdict: {
        mode: 'declared', level: 'high', score: 92, scoreSource: 'declared_by_reporter',
        reportedChannel: '供应商电话通知', reportedBy: '采购人员', reportedAt: '2026-07-09 09:12',
        narrative: ['该等级由录入方申报，系统未对其重新计算。'],
      },
      drivenImpact: { materialId: 'MCU-A9', materialName: 'MCU-A9 主控芯片', riskIndex: 78.75, warningLevel: '红色预警', supportHours: 15, triggerThreshold: 70, shouldTriggerResponse: true },
      drivers: [], deltas: null, evidence: [],
      provenance: { scope: 'resource_type', batches: [] },
      decisionLink: null,
      limitations: [{ code: 'CG-A034', message: '该风险来自外部事件录入，其等级为申报值而非系统计算值。' }],
    });
    render(<RiskExplanationDrawer riskId="risk-1" open onClose={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('risk-explanation-declared-origin')).toHaveTextContent('来源：外部事件录入'));
    expect(screen.getByTestId('risk-explanation-declared-notice')).toHaveTextContent('等级为申报值，非系统计算');
    expect(screen.getByText('供应商电话通知')).toBeInTheDocument();
    expect(screen.getByTestId('risk-explanation-driven-impact')).toBeInTheDocument();
    expect(screen.getByTestId('risk-limitation-CG-A034')).toBeInTheDocument();
    // 申报型风险不得渲染"由指标算出等级"的结论区
    expect(screen.queryByTestId('risk-explanation-index')).not.toBeInTheDocument();
    expect(screen.queryByTestId('risk-explanation-threshold-source')).not.toBeInTheDocument();
  });

  it('已消除风险标注为历史快照', async () => {
    getRiskExplanation.mockResolvedValue({
      available: false, code: 'CG-A031',
      message: '风险已消除，以下为消除当时的最后一次解释快照；当前数据下该解释可能已不成立。',
      isSnapshot: true, snapshotAt: '2026-07-19T08:00:00+00:00',
      snapshot: { riskIndex: 58.75, shouldTriggerResponse: false },
      risk: { id: 'risk-r', code: 'R-R', level: 'low' },
      verdict: null, drivers: [], deltas: null, evidence: [],
      provenance: { scope: 'resource_type', batches: [] }, decisionLink: null,
      limitations: [{ code: 'CG-A031', message: '风险已消除' }],
    });
    render(<RiskExplanationDrawer riskId="risk-r" open onClose={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('risk-explanation-unavailable-title'))
      .toHaveTextContent('当前无法生成实时解释（以下为历史快照）'));
    expect(screen.getByTestId('risk-explanation-code')).toHaveTextContent('错误码：CG-A031');
    expect(screen.getByTestId('risk-explanation-snapshot')).toHaveTextContent('快照时间：2026-07-19T08:00:00+00:00');
    expect(screen.queryByTestId('risk-explanation-index')).not.toBeInTheDocument();
  });
});
