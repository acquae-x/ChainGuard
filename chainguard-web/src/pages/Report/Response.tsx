import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Card, Col, Row, Select, Statistic, Tag, Tooltip } from 'antd';
import { useEffect, useState } from 'react';
import { useModel } from '@umijs/max';
import { RiskTag, SensitiveField } from '@/components';
import { getResponseReport, type ResponseReport } from '@/services/report';

const MISSING = '数据缺失';

// 预算偏差 = 实际应急成本 - 方案预估成本；负数代表比预估省钱。
// 任一侧缺失时后端返回 null，这里必须显示"数据缺失"而不是 ¥0。
const money = (value: number | null) => (value === null ? MISSING : `¥${value.toLocaleString('zh-CN')}`);

export default function Response() {
  const { initialState } = useModel('@@initialState');
  const [months, setMonths] = useState(6);
  const [data, setData] = useState<ResponseReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getResponseReport(months)
      .then(setData)
      .finally(() => setLoading(false));
  }, [months]);

  return (
    <PageContainer
      title="应急效果"
      subTitle={`每事件复盘：响应时长、方案预估 vs 实际、经验卡片产出（按 ${data?.window.timezone || initialState?.tenant?.timezone || 'UTC'} 统计）`}
      extra={
        <Select
          value={months}
          style={{ width: 140 }}
          onChange={setMonths}
          options={[
            { label: '近 3 个月', value: 3 },
            { label: '近 6 个月', value: 6 },
            { label: '近 12 个月', value: 12 },
          ]}
        />
      }
    >
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12}>
          <Card>
            <Statistic
              title="平均响应时长"
              value={data?.avgResponseHours === null || data?.avgResponseHours === undefined ? MISSING : `${data.avgResponseHours} 小时`}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card>
            <Statistic title="经验卡片产出" value={data?.experienceCardTotal ?? 0} />
          </Card>
        </Col>
      </Row>
      <ProTable
        search={false}
        options={false}
        loading={loading}
        rowKey="id"
        dataSource={data?.events ?? []}
        pagination={{ pageSize: 10 }}
        columns={[
          { title: '事件编号', dataIndex: 'code' },
          { title: '标题', dataIndex: 'title' },
          { title: '等级', dataIndex: 'level', render: (_, row) => <RiskTag level={row.level as any} /> },
          {
            title: '响应时长',
            dataIndex: 'responseHours',
            render: (_, row) => (row.responseHours === null ? MISSING : `${row.responseHours} 小时`),
          },
          {
            title: (
              <Tooltip title="方案预估成本，来自被采纳方案的 total_cost">
                <span>预估成本</span>
              </Tooltip>
            ),
            dataIndex: 'estimatedCost',
            render: (_, row) => <SensitiveField field="cost" value={money(row.estimatedCost)} />,
          },
          {
            title: '实际成本',
            dataIndex: 'actualCost',
            render: (_, row) => <SensitiveField field="cost" value={money(row.actualCost)} />,
          },
          {
            title: (
              <Tooltip title="实际成本 - 预估成本；负数表示低于预估">
                <span>预算偏差</span>
              </Tooltip>
            ),
            dataIndex: 'costDiff',
            render: (_, row) =>
              row.costDiff === null ? (
                MISSING
              ) : (
                <Tag color={row.costDiff <= 0 ? 'green' : 'orange'}>
                  <SensitiveField field="cost" value={money(row.costDiff)} />
                </Tag>
              ),
          },
          { title: '方案数', dataIndex: 'proposalCount' },
          { title: '经验卡片', dataIndex: 'experienceCards' },
        ]}
      />
    </PageContainer>
  );
}
