import { history } from '@/runtime';
import { Alert, Badge, Button, Collapse, Empty, Space, Spin, Table, Tag, Typography } from 'antd';

// A04 影响范围完整版：按实体类型分组展示"这条风险/这个事件波及了哪些真实业务对象"。
// 本组件只呈现后端 /risks/{id}/impact-scope 与 /incidents/{id}/impact 返回的结构，
// 不做任何本地推算、不补默认值——后端说没有，界面就显示没有。

const DEGREE_LABELS: Record<string, string> = { direct: '直接', indirect: '间接' };
const DEGREE_COLORS: Record<string, string> = { direct: 'red', indirect: 'orange' };

const FIELD_LABELS: Record<string, string> = {
  category: '类别', unit: '单位', dailyConsumption: '日消耗', unitCost: '单位成本',
  isCritical: '关键物料', materialId: '物料', warehouseName: '仓库', warehouseId: '仓库编号',
  onHandQty: '现有库存', availableQty: '可用库存', safetyStockQty: '安全库存',
  inTransitQty: '在途数量', plannedArrivalAt: '计划到货', estimatedArrivalAt: '预计到货',
  region: '区域', reliabilityScore: '可靠性评分', qualified: '合格供应商',
  supplierRank: '供应商排序', leadTimeHours: '交付周期(小时)', supplierPrice: '供应商报价',
  availableEmergencyQty: '可紧急供应量', customerId: '客户', orderedQty: '订单数量',
  promisedDeliveryAt: '承诺交期', orderAmount: '订单金额', grossProfit: '毛利',
  penaltyCost: '违约罚金', customerLevel: '客户等级', contract: '合同', owner: '负责人',
  assignee: '负责人', roleCode: '角色', priority: '优先级', dueAt: '截止时间', source: '来源',
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '数据缺失';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return String(Number(value.toFixed(2)));
  return String(value);
}

function summarizeFields(fields: Record<string, unknown> | undefined): string {
  const entries = Object.entries(fields || {}).filter(([, value]) => value !== null && value !== undefined && value !== '');
  if (!entries.length) return '无附加字段';
  return entries.map(([key, value]) => `${FIELD_LABELS[key] || key}：${formatValue(value)}`).join('；');
}

export type ImpactScopePanelProps = {
  data?: any;
  loading?: boolean;
  error?: string;
  /** 跳转前的收尾动作，例如关闭承载本面板的抽屉。 */
  onNavigate?: () => void;
  testIdPrefix?: string;
};

export default function ImpactScopePanel({
  data, loading, error, onNavigate, testIdPrefix = 'impact-scope',
}: ImpactScopePanelProps) {
  if (loading) return <Spin><div style={{ height: 160 }} /></Spin>;
  if (error) return <Alert type="error" showIcon message="影响范围加载失败" description={error} />;
  if (!data) return <Empty description="暂无影响范围数据" />;

  const limitations = (data.limitations || []) as { code: string; message: string }[];

  // available=false：起点都定位不到，只能说明为什么，绝不拼一份看起来合理的影响范围。
  if (data.available === false) {
    return (
      <div data-testid={`${testIdPrefix}-unavailable`}>
        <Alert
          type="warning"
          showIcon
          message={<span data-testid={`${testIdPrefix}-unavailable-title`}>无法确定影响范围</span>}
          description={
            <Space direction="vertical" size={4}>
              <span data-testid={`${testIdPrefix}-unavailable-message`}>{data.message}</span>
              <Typography.Text type="secondary" data-testid={`${testIdPrefix}-code`}>错误码：{data.code}</Typography.Text>
            </Space>
          }
        />
      </div>
    );
  }

  const groups = (data.groups || []) as any[];

  return (
    <div data-testid={testIdPrefix}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap>
          <Typography.Text strong>
            共波及 <span data-testid={`${testIdPrefix}-total`}>{data.summary?.total ?? 0}</span> 个业务对象
          </Typography.Text>
          <Tag color="red" data-testid={`${testIdPrefix}-direct-total`}>直接 {data.summary?.direct ?? 0}</Tag>
          <Tag color="orange" data-testid={`${testIdPrefix}-indirect-total`}>间接 {data.summary?.indirect ?? 0}</Tag>
          <Typography.Text type="secondary">
            起点：{(data.seeds || []).map((seed: any) => seed.name).join('、') || '未记录'}
          </Typography.Text>
        </Space>

        <Typography.Text type="secondary" data-testid={`${testIdPrefix}-traversal-note`}>
          {data.traversal?.note || '所有关系均沿实体表真实外键遍历。'}
          {data.traversal?.maxHops ? `最多 ${data.traversal.maxHops} 跳。` : ''}
        </Typography.Text>

        <Collapse
          data-testid={`${testIdPrefix}-groups`}
          items={groups.map((group: any) => ({
            key: group.entityType,
            label: (
              <Space data-testid={`${testIdPrefix}-group-${group.entityType}`}>
                <Typography.Text strong>{group.label}</Typography.Text>
                <Badge count={group.total} showZero color={group.total ? '#1677ff' : '#bfbfbf'} />
                <Typography.Text type="secondary" data-testid={`${testIdPrefix}-group-${group.entityType}-counts`}>
                  直接 {group.direct} / 间接 {group.indirect}
                </Typography.Text>
              </Space>
            ),
            children: group.total
              ? (
                <Table
                  rowKey="id"
                  size="small"
                  pagination={group.total > 20 ? { pageSize: 20 } : false}
                  dataSource={group.items}
                  data-testid={`${testIdPrefix}-table-${group.entityType}`}
                  columns={[
                    {
                      title: '名称',
                      render: (_: unknown, row: any) => (
                        <Space direction="vertical" size={0}>
                          <span data-testid={`${testIdPrefix}-item-${row.entityType}-${row.id}`}>{row.name}</span>
                          <Typography.Text type="secondary">{row.id}</Typography.Text>
                        </Space>
                      ),
                    },
                    {
                      title: '影响关系',
                      render: (_: unknown, row: any) => (
                        <Space direction="vertical" size={0}>
                          <Space size={4}>
                            <Tag color={DEGREE_COLORS[row.degree]} data-testid={`${testIdPrefix}-degree-${row.entityType}-${row.id}`}>
                              {DEGREE_LABELS[row.degree] || row.degree}
                            </Tag>
                            <span data-testid={`${testIdPrefix}-relation-${row.entityType}-${row.id}`}>{row.relation?.label}</span>
                          </Space>
                          {/* 关系经由哪张表是可核对的事实，明示出来 */}
                          <Typography.Text type="secondary">经由 {row.relation?.via}</Typography.Text>
                        </Space>
                      ),
                    },
                    {
                      title: '当前状态',
                      render: (_: unknown, row: any) => (
                        <Space direction="vertical" size={0}>
                          <span>{row.status?.label || '无状态字段'}</span>
                          <Typography.Text type="secondary">{summarizeFields(row.fields)}</Typography.Text>
                        </Space>
                      ),
                    },
                    {
                      title: '数据来源',
                      render: (_: unknown, row: any) => (
                        <Space direction="vertical" size={0}>
                          <Typography.Text type="secondary">{row.source?.table}</Typography.Text>
                          <Typography.Text type="secondary" data-testid={`${testIdPrefix}-batch-${row.entityType}-${row.id}`}>
                            {row.source?.batch
                              ? `${row.source.batch.fileName || row.source.batch.source}（非本行血缘）`
                              : '无导入批次记录'}
                          </Typography.Text>
                        </Space>
                      ),
                    },
                    {
                      title: '更新时间',
                      dataIndex: 'updatedAt',
                      render: (value: string) => value || '未记录',
                    },
                    {
                      title: '操作',
                      render: (_: unknown, row: any) => (row.link ? (
                        <Button
                          type="link"
                          size="small"
                          data-testid={`${testIdPrefix}-link-${row.entityType}-${row.id}`}
                          onClick={() => { onNavigate?.(); history.push(row.link); }}
                        >
                          查看
                        </Button>
                      ) : <Typography.Text type="secondary">无资料页</Typography.Text>),
                    },
                  ]}
                />
              )
              : (
                // 空组不静默消失：显式说明为什么这里是空的。
                <Typography.Text type="secondary" data-testid={`${testIdPrefix}-empty-${group.entityType}`}>
                  {group.emptyReason || '暂无数据'}
                </Typography.Text>
              ),
          }))}
        />

        {limitations.length ? (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            {limitations.map((item) => (
              <div key={item.code} data-testid={`${testIdPrefix}-limitation-${item.code}`}>
                <Alert type="warning" showIcon message={item.message} />
              </div>
            ))}
          </Space>
        ) : null}
      </Space>
    </div>
  );
}
