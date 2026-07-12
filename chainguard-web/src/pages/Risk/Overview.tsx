import ReactECharts from 'echarts-for-react';
import { Card, Col, Row, Table } from 'antd';
import { useEffect, useState } from 'react';
import { KpiCard, RiskTag, StatusTag } from '@/components';
import { getRiskMatrix, getRisks } from '@/services/risk';
import { palette } from '@/theme';

export default function RiskOverviewPage() {
  const [risks, setRisks] = useState<API.Risk[]>([]);
  const [matrix, setMatrix] = useState<any[]>([]);
  useEffect(() => { getRisks().then((res) => setRisks(res.data)); getRiskMatrix().then(setMatrix); }, []);
  return (
    <div>
      <Row gutter={[16, 16]}>{['高风险数', '中风险数', '低风险数', '今日新增'].map((title, index) => <Col xs={24} md={12} xl={6} key={title}><KpiCard title={title} value={[1, 2, 1, 3][index]} /></Col>)}</Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={14}><Card title="风险矩阵图"><ReactECharts style={{ height: 320 }} option={{ color: palette.chart, xAxis: { name: '影响' }, yAxis: { name: '概率' }, series: [{ type: 'scatter', symbolSize: (v: any) => v[2] / 2, data: matrix.map((item) => item.value) }] }} /></Card></Col>
        <Col span={10}><Card title="按类型分布"><ReactECharts style={{ height: 320 }} option={{ color: palette.chart, tooltip: {}, series: [{ type: 'pie', radius: '60%', data: [{ name: '供应', value: 2 }, { name: '库存', value: 1 }, { name: '需求', value: 1 }] }] }} /></Card></Col>
      </Row>
      <Card title="最新风险" style={{ marginTop: 16 }}>
        <Table rowKey="id" dataSource={risks} pagination={false} columns={[{ title: '等级', dataIndex: 'level', render: (v) => <RiskTag level={v} /> }, { title: '对象', dataIndex: 'objectName' }, { title: '状态', dataIndex: 'status', render: (v) => <StatusTag status={v} /> }]} />
      </Card>
    </div>
  );
}
