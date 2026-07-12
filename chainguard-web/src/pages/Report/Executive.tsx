import { PageContainer } from '@ant-design/pro-components';
import { useModel } from '@umijs/max';
import { Card, Col, Row, Statistic, Typography } from 'antd';
import ReactECharts from 'echarts-for-react';
import { KpiCard, SensitiveField } from '@/components';

export default function Executive() {
  const { initialState } = useModel('@@initialState');
  const canViewCost = initialState?.currentUser?.permissions.includes('field:cost:view');
  const costSeries = canViewCost ? [12, 14, 9, 18, 16, 12.8] : [];
  const lossSeries = canViewCost ? [42, 58, 51, 76, 83, 86] : [];

  return (
    <PageContainer title="经营看板" subTitle="本月供应链风险、成本与经营收益">
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}><Card><Typography.Text type="secondary">净收益</Typography.Text><Typography.Title level={3}><SensitiveField field="profit" value="¥732,000" /></Typography.Title><Typography.Text type="secondary">避免损失 - 应急成本</Typography.Text></Card></Col>
        <Col xs={24} sm={12} xl={6}><KpiCard title="风险事件" value={18} trend="同比 -12%" /></Col>
        <Col xs={24} sm={12} xl={6}><KpiCard title="平均响应" value="5.2 小时" trend="较上月缩短 1.8 小时" /></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="高等级客户履约率" value={96.8} suffix="%" /></Card></Col>
        <Col xs={24} xl={14}>
          <Card title="避免损失与应急成本" extra={!canViewCost && <SensitiveField field="cost" value="¥0" />}>
            <ReactECharts
              style={{ height: 300 }}
              option={{
                tooltip: { trigger: 'axis', show: canViewCost },
                legend: {
                  data: ['避免损失', '应急成本'],
                  selected: canViewCost ? undefined : { 避免损失: false, 应急成本: false }
                },
                xAxis: { type: 'category', data: ['2月', '3月', '4月', '5月', '6月', '7月'] },
                yAxis: { type: 'value' },
                series: [
                  { name: '避免损失', type: 'line', data: lossSeries, itemStyle: { color: '#389E0D' } },
                  { name: '应急成本', type: 'bar', data: costSeries, itemStyle: { color: '#D46B08' } }
                ]
              }}
            />
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card title="Top 风险供应商">
            <ReactECharts style={{ height: 300 }} option={{ grid: { left: 110 }, xAxis: { type: 'value' }, yAxis: { type: 'category', data: ['苏州芯片', '东莞电机', '无锡精密', '宁波微电'] }, series: [{ type: 'bar', data: [92, 78, 66, 53], itemStyle: { color: '#1B4F9C' } }] }} />
          </Card>
        </Col>
      </Row>
    </PageContainer>
  );
}
