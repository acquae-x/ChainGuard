import { history } from '@umijs/max';
import { Alert, Button, Card, Descriptions, Drawer, Empty, Progress, Space, Spin, Table, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
// 直接引 RiskTag 而非从 '@/components' 桶文件引，避免 index.ts ↔ 本组件的循环依赖。
import RiskTag from '@/components/RiskTag';
import ImpactScopePanel from '@/components/ImpactScopePanel';
import { getRiskExplanation, getRiskImpactScope } from '@/services/risk';

// A03 风险解释抽屉：四段式——结论 / 驱动因素 / 证据来源 / 数据来源与限制。
// 所有数值均来自后端 /risks/{id}/explanation（由引擎算出），本组件只负责呈现，不做任何换算。

const COMPARISON_LABELS: Record<string, string> = {
  below_red: '低于红线',
  below_yellow: '低于黄线',
  normal: '正常区间',
};

const UNIT_SUFFIX: Record<string, string> = { hour: ' 小时', ratio: '', score: ' 分' };

function formatValue(value: unknown, unit?: string) {
  if (value === null || value === undefined) return '数据缺失';
  if (typeof value === 'string') return value;
  if (typeof value !== 'number') return String(value);
  if (unit === 'ratio') return `${(value * 100).toFixed(1)}%`;
  return `${Number(value.toFixed(2))}${UNIT_SUFFIX[unit || ''] || ''}`;
}

const ENTITY_LABELS: Record<string, string> = {
  material: '物料', inventory: '库存', supplier: '供应商', order: '订单', customer: '客户',
};

const FIELD_LABELS: Record<string, string> = {
  dailyConsumption: '日消耗', unit: '单位', isCritical: '关键物料',
  onHandQty: '现有库存', availableQty: '可用库存', safetyStockQty: '安全库存',
  inTransitQty: '在途数量', plannedArrivalAt: '计划到货', estimatedArrivalAt: '预计到货',
  status: '状态', region: '区域', reliabilityScore: '可靠性评分', leadTimeHours: '交付周期(小时)',
  availableEmergencyQty: '可紧急供应量', supplierPrice: '供应商报价',
  customerLevel: '客户等级', demandQty: '需求数量', dueHours: '距交期(小时)',
  orderAmount: '订单金额', grossProfit: '毛利', penaltyCost: '违约罚金',
};

export type RiskExplanationDrawerProps = {
  riskId?: string;
  open: boolean;
  onClose: () => void;
};

export default function RiskExplanationDrawer({ riskId, open, onClose }: RiskExplanationDrawerProps) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>();
  const [error, setError] = useState<string>();
  // A04：影响范围是独立端点，与解释各自失败互不牵连——影响范围挂了不该让解释也不可见。
  const [scope, setScope] = useState<any>();
  const [scopeLoading, setScopeLoading] = useState(false);
  const [scopeError, setScopeError] = useState<string>();

  useEffect(() => {
    if (!open || !riskId) return;
    setLoading(true); setError(undefined); setData(undefined);
    getRiskExplanation(riskId)
      .then(setData)
      .catch((reason) => setError(reason?.message || '风险解释加载失败'))
      .finally(() => setLoading(false));

    setScopeLoading(true); setScopeError(undefined); setScope(undefined);
    getRiskImpactScope(riskId)
      .then(setScope)
      .catch((reason) => setScopeError(reason?.message || '影响范围加载失败'))
      .finally(() => setScopeLoading(false));
  }, [open, riskId]);

  const limitations = (data?.limitations || []) as { code: string; message: string }[];
  const verdict = data?.verdict;
  const drivers = (data?.drivers || []) as any[];
  const maxContribution = Math.max(1, ...drivers.map((item) => Number(item.contribution) || 0));

  return (
    <Drawer
      title="风险解释"
      width={720}
      open={open}
      onClose={onClose}
      destroyOnClose
      // 稳定的测试锚点：验收断言一律按 testid 唯一定位，不依赖文案子串。
      // 同一数值会同时出现在「结论」与「触发规则」两处，模糊匹配必然命中多个元素。
      rootClassName="risk-explanation-drawer"
    >
      {/* antd Drawer 不透传 data-* 到内容节点，锚点挂在内层容器上。 */}
      <div data-testid="risk-explanation-drawer">
      {loading ? <Spin><div style={{ height: 200 }} /></Spin> : null}
      {error ? <Alert type="error" showIcon message="风险解释加载失败" description={error} /> : null}

      {data && !loading ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {/* ① 结论 */}
          {data.available === false ? (
            <Alert
              type="warning"
              showIcon
              message={<span data-testid="risk-explanation-unavailable-title">{data.isSnapshot ? '当前无法生成实时解释（以下为历史快照）' : '当前无法生成风险解释'}</span>}
              description={
                <Space direction="vertical" size={4}>
                  <span data-testid="risk-explanation-unavailable-message">{data.message}</span>
                  <Typography.Text type="secondary" data-testid="risk-explanation-code">错误码：{data.code}</Typography.Text>
                  {data.isSnapshot && data.snapshot ? (
                    <Typography.Text type="secondary" data-testid="risk-explanation-snapshot">
                      快照时间：{data.snapshotAt || '未记录'}；快照风险指数：{formatValue(data.snapshot.riskIndex)}
                    </Typography.Text>
                  ) : null}
                </Space>
              }
            />
          ) : (
            <Card size="small" title="结论">
              {verdict?.mode === 'declared' ? (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Space wrap>
                    <RiskTag level={data.risk?.level} />
                    <Tag color="default" data-testid="risk-explanation-declared-origin">来源：外部事件录入</Tag>
                    <Tag color="orange" data-testid="risk-explanation-declared-notice">等级为申报值，非系统计算</Tag>
                  </Space>
                  <Descriptions size="small" column={1}>
                    <Descriptions.Item label="录入渠道">{verdict.reportedChannel || '未记录'}</Descriptions.Item>
                    <Descriptions.Item label="录入人">{verdict.reportedBy || '未记录'}</Descriptions.Item>
                    <Descriptions.Item label="录入时间">{verdict.reportedAt || '未记录'}</Descriptions.Item>
                  </Descriptions>
                  {(verdict.narrative || []).map((line: string) => (
                    <Typography.Paragraph key={line} style={{ marginBottom: 4 }}>{line}</Typography.Paragraph>
                  ))}
                  {data.drivenImpact ? (
                    <div data-testid="risk-explanation-driven-impact">
                    <Alert
                      type="info"
                      showIcon
                      message="该事件驱动的库存影响（此部分为实时计算）"
                      description={`物料 ${data.drivenImpact.materialName}：风险指数 ${formatValue(data.drivenImpact.riskIndex)}，`
                        + `支撑 ${formatValue(data.drivenImpact.supportHours, 'hour')}，触发阈值 ${formatValue(data.drivenImpact.triggerThreshold)}。`}
                    />
                    </div>
                  ) : null}
                </Space>
              ) : (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Space wrap>
                    <RiskTag level={data.risk?.level} />
                    <Tag color={verdict?.shouldTriggerResponse ? 'red' : 'green'} data-testid="risk-explanation-warning-level">{verdict?.warningLevel}</Tag>
                    <Tag color={verdict?.thresholdSource === 'tenant_config' ? 'blue' : 'default'} data-testid="risk-explanation-threshold-source">
                      阈值来源：{verdict?.thresholdSource === 'tenant_config' ? '数据驱动（本租户配置）' : '专家默认'}
                    </Tag>
                  </Space>
                  {/* 指数与阈值各自独立锚点：验收断言按 testid 取值比对，不做整句模糊匹配。 */}
                  <Typography.Text strong>
                    风险指数 <span data-testid="risk-explanation-index">{formatValue(verdict?.riskIndex)}</span>
                    {' / '}触发阈值 <span data-testid="risk-explanation-threshold">{formatValue(verdict?.triggerThreshold)}</span>
                    （{verdict?.shouldTriggerResponse ? '已超过阈值' : '未超过阈值'}）
                  </Typography.Text>
                  <Typography.Text type="secondary" data-testid="risk-explanation-rule">触发规则：{verdict?.rule}</Typography.Text>
                  {(verdict?.narrative || []).map((line: string) => (
                    <Typography.Paragraph key={line} type="secondary" style={{ marginBottom: 2 }}>{line}</Typography.Paragraph>
                  ))}
                  {data.deltas ? (
                    <Alert
                      type="info"
                      showIcon
                      message={`较上次扫描 ${Number(data.deltas.change) >= 0 ? '上升' : '下降'} ${Math.abs(Number(data.deltas.change))}`}
                      description={`上次 ${formatValue(data.deltas.previousScore)}（${data.deltas.previousAt || '时间未记录'}）`
                        + (data.deltas.changedDrivers?.length
                          ? `；变化项：${data.deltas.changedDrivers.map((item: any) => `${item.label} ${item.from}→${item.to}`).join('、')}`
                          : '')}
                    />
                  ) : (
                    <Typography.Text type="secondary">首次计算，无对比基线。</Typography.Text>
                  )}
                </Space>
              )}
            </Card>
          )}

          {/* ② 驱动因素 */}
          {drivers.length ? (
            <div data-testid="risk-explanation-drivers">
            <Card size="small" title="驱动因素（权重 × 分项 = 贡献）">
              <Table
                rowKey="key"
                size="small"
                pagination={false}
                dataSource={drivers}
                columns={[
                  { title: '因素', dataIndex: 'label' },
                  {
                    title: '当前值 / 阈值',
                    render: (_: unknown, row: any) => (
                      <Space direction="vertical" size={0}>
                        <span data-testid={`risk-driver-${row.key}-current`}>{row.metric}：{formatValue(row.currentValue, row.unit)}</span>
                        {row.threshold ? (
                          <Typography.Text type="secondary" data-testid={`risk-driver-${row.key}-threshold`}>
                            黄线 {row.threshold.yellow} / 红线 {row.threshold.red}
                            {row.comparison ? `（${COMPARISON_LABELS[row.comparison] || row.comparison}）` : ''}
                          </Typography.Text>
                        ) : <Typography.Text type="secondary">无阈值对照</Typography.Text>}
                      </Space>
                    ),
                  },
                  { title: '分项得分', dataIndex: 'score', render: (value: number) => formatValue(value) },
                  { title: '权重', dataIndex: 'weight', render: (value: number) => `${(Number(value) * 100).toFixed(0)}%` },
                  {
                    title: '贡献',
                    dataIndex: 'contribution',
                    render: (value: number) => (
                      <Space direction="vertical" size={0} style={{ width: 120 }}>
                        <span>{formatValue(value)}</span>
                        <Progress percent={Math.round((Number(value) / maxContribution) * 100)} showInfo={false} size="small" />
                      </Space>
                    ),
                  },
                ]}
              />
            </Card>
            </div>
          ) : null}

          {/* ③ 证据来源 */}
          {data.evidence?.length ? (
            <Card size="small" title="证据来源（本租户实体）">
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {data.evidence.map((item: any) => (
                  <div key={`${item.entity}-${item.id}`} data-testid={`risk-evidence-${item.entity}-${item.id}`}>
                  <Card size="small" type="inner"
                    title={<Space><Tag>{ENTITY_LABELS[item.entity] || item.entity}</Tag><span>{item.name}</span><Typography.Text type="secondary">{item.id}</Typography.Text></Space>}
                    extra={<Button type="link" size="small" data-testid={`risk-evidence-link-${item.entity}-${item.id}`} onClick={() => { onClose(); history.push(item.link); }}>查看来源</Button>}
                  >
                    <Descriptions size="small" column={2}>
                      {Object.entries(item.fields || {}).map(([key, value]) => (
                        <Descriptions.Item key={key} label={FIELD_LABELS[key] || key}>{formatValue(value)}</Descriptions.Item>
                      ))}
                    </Descriptions>
                    <Typography.Text type="secondary">更新时间：{item.updatedAt || '未记录'}</Typography.Text>
                  </Card>
                  </div>
                ))}
              </Space>
            </Card>
          ) : null}

          {/* ④ 数据来源与限制 */}
          <Card size="small" title="数据来源与限制">
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {data.provenance?.batches?.length ? (
                <>
                  <Typography.Text type="secondary">{data.provenance.note || '最近一次导入批次（非本行血缘）'}</Typography.Text>
                  <Table
                    rowKey="importJobId"
                    size="small"
                    pagination={false}
                    dataSource={data.provenance.batches}
                    columns={[
                      { title: '资源类型', dataIndex: 'resourceType' },
                      { title: '批次', dataIndex: 'fileName' },
                      { title: '来源', dataIndex: 'source' },
                      { title: '完成时间', dataIndex: 'finishedAt' },
                    ]}
                  />
                </>
              ) : (
                <Typography.Text type="secondary">
                  没有可关联的导入批次记录{data.provenance?.unknownResources?.length ? `（${data.provenance.unknownResources.join('、')}）` : ''}。
                </Typography.Text>
              )}
              {limitations.length ? limitations.map((item) => (
                <div key={item.code} data-testid={`risk-limitation-${item.code}`}>
                  <Alert type="warning" showIcon message={item.message} />
                </div>
              )) : <Typography.Text type="secondary">无已知数据限制。</Typography.Text>}
              {data.decisionLink ? (
                <Typography.Text type="secondary">
                  后续方案生成将使用同一批上下文：{data.decisionLink.contextKeys?.join('、')}
                </Typography.Text>
              ) : null}
            </Space>
          </Card>

          {/* ⑤ 影响范围（A04）：与事件详情页复用同一面板，口径一致。 */}
          <Card size="small" title="影响范围">
            <ImpactScopePanel
              data={scope}
              loading={scopeLoading}
              error={scopeError}
              onNavigate={onClose}
              testIdPrefix="risk-impact-scope"
            />
          </Card>
        </Space>
      ) : null}

      {!loading && !data && !error ? <Empty description="暂无解释数据" /> : null}
      </div>
    </Drawer>
  );
}
