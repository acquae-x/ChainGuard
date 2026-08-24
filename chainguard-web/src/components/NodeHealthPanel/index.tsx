import { history } from '@/runtime';
import { Alert, Button, Card, Col, Empty, Row, Select, Space, Spin, Table, Tag, Typography } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { getMyNodes, getNodeHealth } from '@/services/dashboard';

// C02/C03 供应链节点健康：只呈现后端 /dashboard/node-health 与 /dashboard/my-nodes 返回的结构。
// 本组件**不做任何本地推算**——不自己数节点、不自己判健康、不补默认值。
// 后端说数据不足，界面就显示数据不足；后端不返回计数，界面就不显示计数。

const HEALTH_ORDER = ['critical', 'warning', 'healthy', 'unknown'] as const;

const HEALTH_META: Record<string, { label: string; color: string }> = {
  critical: { label: '异常', color: 'red' },
  warning: { label: '预警', color: 'orange' },
  healthy: { label: '健康', color: 'green' },
  unknown: { label: '数据不足', color: 'default' },
};

const METRIC_LABELS: Record<string, string> = {
  warningLevel: '预警级别', riskIndex: '库存风险指数', supportHours: '库存支撑(小时)',
  currentStock: '当前库存', safetyStock: '安全库存', inTransitQty: '在途数量',
  dailyConsumption: '日消耗', unit: '单位', isCritical: '关键物料',
  expertHealth: '绝对轨判定', relativeHealth: '相对轨判定',
  inventoryRowCount: '库存行数', materialCount: '物料数', onHandQty: '现有库存',
  availableQty: '可用库存', safetyStockQty: '安全库存', status: '状态', region: '区域',
  reliabilityScore: '可靠性评分', qualifiedMaterialCount: '合格供货物料数',
  supplierPrice: '供应商报价', orderStatus: '订单状态', promisedDeliveryAt: '承诺交期',
  lineCount: '行项目数', orderedQty: '订单数量', customerName: '客户',
  customerLevel: '客户等级', orderAmount: '订单金额', grossProfit: '毛利', penaltyCost: '违约罚金',
};

// dataQuality 是结构化的降级说明，单独渲染更清楚，不塞进指标行里。
const HIDDEN_METRICS = new Set(['dataQuality']);

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '数据缺失';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return String(Number(value.toFixed(2)));
  return String(value);
}

function summarizeMetrics(metrics: Record<string, unknown> | undefined): string {
  const entries = Object.entries(metrics || {})
    .filter(([key]) => !HIDDEN_METRICS.has(key))
    .filter(([, value]) => value !== null && value !== undefined && value !== '');
  if (!entries.length) return '无可展示字段';
  return entries.map(([key, value]) => `${METRIC_LABELS[key] || key}：${formatValue(value)}`).join('；');
}

export type NodeHealthPanelProps = {
  /** overview = 管理者概览（全部四类）；mine = 一线「我的节点」（范围由既有权限码派生）。 */
  mode?: 'overview' | 'mine';
  testIdPrefix?: string;
  /** 注入取数函数，仅供测试替换；生产走 services/dashboard。 */
  fetcher?: (params: Record<string, unknown>) => Promise<any>;
};

export default function NodeHealthPanel({
  mode = 'overview', testIdPrefix = 'node-health', fetcher,
}: NodeHealthPanelProps) {
  const [data, setData] = useState<any>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [nodeType, setNodeType] = useState<string>();
  const [health, setHealth] = useState<string>();

  const load = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    const params: Record<string, unknown> = { pageSize: 50 };
    if (nodeType) params.nodeType = nodeType;
    if (health) params.health = health;
    try {
      const request = fetcher || (mode === 'mine' ? getMyNodes : getNodeHealth);
      setData(await request(params));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '节点健康数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [fetcher, health, mode, nodeType]);

  useEffect(() => { load(); }, [load]);

  const limitations = useMemo(
    () => (data?.limitations || []) as { code: string; message: string }[],
    [data],
  );

  const limitationBlock = limitations.length ? (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      {limitations.map((item) => (
        <div key={item.code} data-testid={`${testIdPrefix}-limitation-${item.code}`}>
          <Alert type="info" showIcon message={item.message} />
        </div>
      ))}
    </Space>
  ) : null;

  if (loading) return <Spin><div style={{ height: 160 }} /></Spin>;
  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message="节点健康加载失败"
        description={error}
        action={<Button size="small" onClick={load}>重试</Button>}
      />
    );
  }
  if (!data) return <Empty description="暂无节点健康数据" />;

  // available=false：连节点都无从算起，只说明原因，绝不渲染任何计数或节点行。
  if (data.available === false) {
    return (
      <div data-testid={`${testIdPrefix}-unavailable`}>
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Alert
            type="warning"
            showIcon
            message={<span data-testid={`${testIdPrefix}-unavailable-title`}>暂时无法给出节点健康</span>}
            description={
              <Space direction="vertical" size={4}>
                <span data-testid={`${testIdPrefix}-unavailable-message`}>{data.message}</span>
                <Typography.Text type="secondary" data-testid={`${testIdPrefix}-code`}>
                  错误码：{data.code}
                </Typography.Text>
              </Space>
            }
          />
          {limitationBlock}
        </Space>
      </div>
    );
  }

  const byType = (data.byType || []) as any[];
  const nodes = (data.nodes || []) as any[];
  const typeOptions = (data.filters?.nodeTypes || []) as { value: string; label: string }[];
  const healthOptions = (data.filters?.healthStates || []) as { value: string; label: string }[];

  return (
    <div data-testid={testIdPrefix}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {/* 概览计数：数字全部来自 summary，界面不自己算一遍 */}
        <Row gutter={[8, 8]}>
          {HEALTH_ORDER.map((level) => (
            <Col xs={12} md={6} key={level}>
              <Card size="small" data-testid={`${testIdPrefix}-count-${level}`}>
                <Typography.Text type="secondary">{HEALTH_META[level].label}</Typography.Text>
                <Typography.Title level={3} style={{ margin: 0 }}>
                  <span data-testid={`${testIdPrefix}-count-${level}-value`}>
                    {data.summary?.[level] ?? 0}
                  </span>
                </Typography.Title>
              </Card>
            </Col>
          ))}
        </Row>

        {mode === 'mine' && data.scope ? (
          <Typography.Text type="secondary" data-testid={`${testIdPrefix}-scope`}>
            我负责的节点类型：{
              (data.scope.nodeTypes || [])
                .map((name: string) => byType.find((row) => row.nodeType === name)?.label || name)
                .join('、')
            }
            （范围依据：{data.scope.basis}）
          </Typography.Text>
        ) : null}

        <Space wrap>
          <Select
            allowClear
            placeholder="全部节点类型"
            style={{ minWidth: 150 }}
            value={nodeType}
            onChange={(value) => setNodeType(value)}
            options={typeOptions}
            data-testid={`${testIdPrefix}-filter-type`}
          />
          <Select
            allowClear
            placeholder="全部健康状态"
            style={{ minWidth: 150 }}
            value={health}
            onChange={(value) => setHealth(value)}
            options={healthOptions}
            data-testid={`${testIdPrefix}-filter-health`}
          />
          <Typography.Text type="secondary" data-testid={`${testIdPrefix}-filtered-total`}>
            当前筛选命中 {data.filtered?.total ?? 0} 个节点
          </Typography.Text>
        </Space>

        {/* 阈值来源：判定由绝对轨（专家阈值）与相对轨（数据推导）取较严者得出。
            这里如实说明相对轨当前用的是推导值还是回退值，不含糊成"智能阈值"。 */}
        {data.thresholdCalibration ? (
          <Typography.Text type="secondary" data-testid={`${testIdPrefix}-threshold-source`}>
            {data.thresholdCalibration.source === 'calibrated'
              ? `判定阈值：绝对红线 + 相对离群双轨取严。相对离群线由本批 ${
                  data.thresholdCalibration.sampleSize
                } 个物料的风险分布推导（预警 ${data.thresholdCalibration.warning}／异常 ${
                  data.thresholdCalibration.action
                }），且风险指数低于 ${data.thresholdCalibration.escalationFloor} 时不参与升级。`
              : `判定阈值：样本不足 ${data.thresholdCalibration.minSamples} 个或分布无离散度，相对离群线已回退为专家阈值，当前等价于仅绝对红线生效。`}
          </Typography.Text>
        ) : null}

        {/* 分类型计数；没有节点的类型仍然出现并说明原因 */}
        <Space wrap data-testid={`${testIdPrefix}-by-type`}>
          {byType.map((row) => (
            <Tag key={row.nodeType} data-testid={`${testIdPrefix}-type-${row.nodeType}`}>
              {row.label} {row.total}
              {row.total === 0 && row.emptyReason ? (
                <Typography.Text type="secondary" data-testid={`${testIdPrefix}-empty-${row.nodeType}`}>
                  （{row.emptyReason}）
                </Typography.Text>
              ) : null}
            </Tag>
          ))}
        </Space>

        <Table
          rowKey={(row: any) => `${row.nodeType}:${row.id}`}
          size="small"
          // 固定总宽而非 max-content：原因文案可以很长，用 max-content 会把它撑成一列，
          // 把「关键字段 / 更新时间 / 操作」整体挤出可视区，跳转按钮变得看不见。
          scroll={{ x: 1260 }}
          tableLayout="fixed"
          pagination={nodes.length > 20 ? { pageSize: 20 } : false}
          dataSource={nodes}
          locale={{ emptyText: '当前筛选条件下没有节点' }}
          data-testid={`${testIdPrefix}-table`}
          columns={[
            {
              title: '节点',
              width: 180,
              render: (_: unknown, row: any) => (
                <Space direction="vertical" size={0}>
                  <span data-testid={`${testIdPrefix}-node-${row.nodeType}-${row.id}`}>{row.name}</span>
                  <Typography.Text type="secondary">{row.id}</Typography.Text>
                </Space>
              ),
            },
            {
              title: '类型',
              width: 80,
              render: (_: unknown, row: any) => (
                byType.find((item) => item.nodeType === row.nodeType)?.label || row.nodeType
              ),
            },
            {
              title: '健康状态',
              width: 100,
              render: (_: unknown, row: any) => (
                <Tag
                  color={HEALTH_META[row.health]?.color}
                  data-testid={`${testIdPrefix}-health-${row.nodeType}-${row.id}`}
                >
                  {row.healthLabel}
                </Tag>
              ),
            },
            {
              title: '异常原因',
              width: 360,
              render: (_: unknown, row: any) => (
                row.reasons?.length ? (
                  <Space direction="vertical" size={2}>
                    {row.reasons.map((reason: any, index: number) => (
                      <div key={`${reason.code}-${index}`} data-testid={`${testIdPrefix}-reason-${row.nodeType}-${row.id}-${reason.code}`}>
                        <Typography.Text>{reason.detail}</Typography.Text>
                        {reason.threshold?.source ? (
                          <Typography.Text type="secondary">
                            {' '}（判据来源：{reason.threshold.source}）
                          </Typography.Text>
                        ) : null}
                        {reason.derivedFrom ? (
                          <Button
                            type="link"
                            size="small"
                            data-testid={`${testIdPrefix}-derived-${row.nodeType}-${row.id}`}
                            onClick={() => history.push(reason.derivedFrom.link)}
                          >
                            来源物料：{reason.derivedFrom.name}
                          </Button>
                        ) : null}
                      </div>
                    ))}
                  </Space>
                ) : <Typography.Text type="secondary">无异常</Typography.Text>
              ),
            },
            {
              title: '关键字段',
              width: 220,
              render: (_: unknown, row: any) => (
                <Typography.Text type="secondary">{summarizeMetrics(row.metrics)}</Typography.Text>
              ),
            },
            {
              title: '数据更新时间',
              width: 180,
              dataIndex: 'updatedAt',
              render: (value: string, row: any) => (
                <Space direction="vertical" size={0}>
                  <span>{value || '未记录'}</span>
                  <Typography.Text type="secondary">
                    {row.source?.batch
                      ? `批次：${row.source.batch.fileName || row.source.batch.source}（非本行血缘）`
                      : '无导入批次记录'}
                  </Typography.Text>
                </Space>
              ),
            },
            {
              title: '操作',
              width: 140,
              render: (_: unknown, row: any) => (
                <Space size={0} wrap>
                  {row.link ? (
                    <Button
                      type="link"
                      size="small"
                      data-testid={`${testIdPrefix}-link-${row.nodeType}-${row.id}`}
                      onClick={() => history.push(row.link)}
                    >
                      查看资料
                    </Button>
                  ) : (
                    <Typography.Text type="secondary" data-testid={`${testIdPrefix}-nolink-${row.nodeType}-${row.id}`}>
                      无资料页
                    </Typography.Text>
                  )}
                  {(row.relatedLinks || []).map((item: any) => (
                    <Button
                      key={item.link}
                      type="link"
                      size="small"
                      data-testid={`${testIdPrefix}-related-${row.nodeType}-${row.id}`}
                      onClick={() => history.push(item.link)}
                    >
                      {item.label}
                    </Button>
                  ))}
                </Space>
              ),
            },
          ]}
        />

        {limitationBlock}
      </Space>
    </div>
  );
}
