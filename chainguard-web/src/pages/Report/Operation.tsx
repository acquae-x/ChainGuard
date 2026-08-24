import { PageContainer, ProTable } from '@/components/pro';
import { Card, Col, Empty, Row, Select, Spin, Statistic } from 'antd';
import ReactECharts from 'echarts-for-react';
import { useEffect, useState } from 'react';
import { useModel } from '@/runtime';
import { ROLE_LABELS } from '@/constants/status';
import { getOperationReport, type OperationReport } from '@/services/report';

const percent = (value: number | null) => (value === null ? '数据缺失' : `${(value * 100).toFixed(1)}%`);

export default function Operation() {
  const { initialState } = useModel('@@initialState');
  const [months, setMonths] = useState(6);
  const [data, setData] = useState<OperationReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getOperationReport(months)
      .then(setData)
      .finally(() => setLoading(false));
  }, [months]);

  const funnel = data?.funnel ?? [];
  const hasFunnel = funnel.some((item) => item.count > 0);
  const typeDist = data?.riskTypeDistribution ?? [];

  return (
    <PageContainer
      title="运营看板"
      subTitle={`风险处置漏斗、任务超时与风险分布（按 ${data?.window.timezone || initialState?.tenant?.timezone || 'UTC'} 统计）`}
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
      <Spin spinning={loading}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <Card title="风险处置漏斗">
              {hasFunnel ? (
                <ReactECharts
                  style={{ height: 320 }}
                  option={{
                    tooltip: { trigger: 'item' },
                    series: [{
                      type: 'funnel',
                      data: funnel.map((item) => ({ name: item.stage, value: item.count })),
                      color: ['#1B4F9C', '#0958D9', '#5B8FF9', '#389E0D', '#8C8C8C'],
                    }],
                  }}
                />
              ) : (
                <Empty description="所选范围内暂无风险处置记录" />
              )}
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card title="任务超时率">
              <Statistic value={percent(data?.overdueRate ?? null)} />
              <ProTable
                search={false}
                options={false}
                pagination={false}
                rowKey="roleCode"
                style={{ marginTop: 12 }}
                dataSource={data?.overdueByRole ?? []}
                columns={[
                  { title: '角色', dataIndex: 'roleCode', render: (_, row) => (ROLE_LABELS as any)[row.roleCode] || row.roleCode },
                  { title: '在办', dataIndex: 'total' },
                  { title: '超时', dataIndex: 'overdue' },
                  { title: '超时率', dataIndex: 'rate', render: (_, row) => percent(row.rate) },
                ]}
              />
            </Card>
          </Col>
          <Col xs={24}>
            <Card title="风险类型分布">
              {typeDist.length === 0 ? (
                <Empty description="暂无风险记录" />
              ) : (
                <ReactECharts
                  style={{ height: 300 }}
                  option={{
                    tooltip: { trigger: 'axis' },
                    xAxis: { type: 'category', data: typeDist.map((item) => item.type) },
                    yAxis: { type: 'value' },
                    series: [{ type: 'bar', data: typeDist.map((item) => item.count), itemStyle: { color: '#0958D9' } }],
                  }}
                />
              )}
            </Card>
          </Col>
        </Row>
      </Spin>
    </PageContainer>
  );
}
