import { PageContainer } from '@ant-design/pro-components';
import { Card, Col, Row } from 'antd';
import ReactECharts from 'echarts-for-react';

export default function Operation() {
  return <PageContainer title="运营看板"><Row gutter={[16, 16]}><Col xs={24} lg={14}><Card title="风险处置漏斗"><ReactECharts style={{ height: 320 }} option={{ series: [{ type: 'funnel', data: [{ name: '风险发现', value: 18 }, { name: '创建事件', value: 8 }, { name: '生成方案', value: 5 }, { name: '批准执行', value: 4 }, { name: '完成复盘', value: 3 }], color: ['#1B4F9C', '#0958D9', '#5B8FF9', '#389E0D', '#8C8C8C'] }] }} /></Card></Col><Col xs={24} lg={10}><Card title="各环节平均耗时"><ReactECharts style={{ height: 320 }} option={{ xAxis: { type: 'category', data: ['发现→事件', '事件→方案', '方案→批准', '批准→完成'] }, yAxis: { type: 'value' }, series: [{ type: 'bar', data: [0.3, 1.2, 2.4, 8.5], itemStyle: { color: '#D46B08' } }] }} /></Card></Col></Row></PageContainer>;
}
