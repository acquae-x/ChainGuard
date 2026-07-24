import { PageContainer } from '@ant-design/pro-components';
import { useModel } from '@umijs/max';
import { Alert, Card, Col, Empty, Row, Select, Spin, Statistic, Typography } from 'antd';
import ReactECharts from 'echarts-for-react';
import { useEffect, useState } from 'react';
import { KpiCard, SensitiveField } from '@/components';
import { getExecutiveReport, type ExecutiveReport } from '@/services/report';

const MISSING = '数据缺失';

// 后端对不可测量的指标返回 null（P0-2 口径）：0 表示"真的没赚没亏"，null 表示"这段时间没有事件可测量"。
const money = (value: number | null) => (value === null ? MISSING : `¥${value.toLocaleString('zh-CN')}`);
const hours = (value: number | null) => (value === null ? MISSING : `${value} 小时`);

export default function Executive() {
  const { initialState } = useModel('@@initialState');
  const canViewCost = initialState?.currentUser?.permissions.includes('field:cost:view');
  const [months, setMonths] = useState(6);
  const [data, setData] = useState<ExecutiveReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getExecutiveReport(months)
      .then(setData)
      .finally(() => setLoading(false));
  }, [months]);

  const series = data?.series ?? [];
  const costSeries = canViewCost ? series.map((item) => item.emergencyCost) : [];
  const lossSeries = canViewCost ? series.map((item) => item.avoidedLoss) : [];
  const months_axis = series.map((item) => item.month);
  const suppliers = data?.topRiskSuppliers ?? [];

  return (
    <PageContainer
      title="经营看板"
      subTitle={`本月供应链风险、成本与经营收益（按 ${data?.window.timezone || initialState?.tenant?.timezone || 'UTC'} 统计）`}
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
        {data && data.riskCount === 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="所选时间范围内没有风险事件，经营指标暂不可测量。"
          />
        )}
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} xl={6}>
            <Card>
              <Typography.Text type="secondary">净收益</Typography.Text>
              <Typography.Title level={3}>
                <SensitiveField field="profit" value={money(data?.netBenefit ?? null)} />
              </Typography.Title>
              <Typography.Text type="secondary">避免损失 - 应急成本</Typography.Text>
            </Card>
          </Col>
          <Col xs={24} sm={12} xl={6}>
            <KpiCard title="风险事件" value={data?.riskCount ?? 0} trend={`近 ${months} 个月`} />
          </Col>
          <Col xs={24} sm={12} xl={6}>
            <KpiCard title="平均响应" value={hours(data?.avgResponseHours ?? null)} trend="提交到审批完成" />
          </Col>
          <Col xs={24} sm={12} xl={6}>
            <Card>
              <Statistic title="避免损失" value={money(data?.avoidedLoss ?? null)} />
            </Card>
          </Col>
          <Col xs={24} xl={14}>
            <Card title="避免损失与应急成本">
              {series.length === 0 ? (
                <Empty description="暂无可绘制的月度数据" />
              ) : (
                <ReactECharts
                  style={{ height: 300 }}
                  option={{
                    tooltip: { trigger: 'axis', show: canViewCost },
                    legend: {
                      data: ['避免损失', '应急成本'],
                      selected: canViewCost ? undefined : { 避免损失: false, 应急成本: false },
                    },
                    xAxis: { type: 'category', data: months_axis },
                    yAxis: { type: 'value' },
                    series: [
                      { name: '避免损失', type: 'line', data: lossSeries, itemStyle: { color: '#389E0D' } },
                      { name: '应急成本', type: 'bar', data: costSeries, itemStyle: { color: '#D46B08' } },
                    ],
                  }}
                />
              )}
            </Card>
          </Col>
          <Col xs={24} xl={10}>
            <Card title="Top 风险供应商">
              {suppliers.length === 0 ? (
                <Empty description="暂无供应商风险记录" />
              ) : (
                <ReactECharts
                  style={{ height: 300 }}
                  option={{
                    grid: { left: 110 },
                    xAxis: { type: 'value' },
                    yAxis: { type: 'category', data: suppliers.map((item) => item.name) },
                    series: [{ type: 'bar', data: suppliers.map((item) => item.score), itemStyle: { color: '#1B4F9C' } }],
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
