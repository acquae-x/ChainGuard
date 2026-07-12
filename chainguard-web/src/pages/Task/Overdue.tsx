import { useAccess } from '@umijs/max';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Button, Card, message } from 'antd';
import ReactECharts from 'echarts-for-react';
import { BellOutlined } from '@ant-design/icons';
import { getTasks, urge } from '@/services/task';

export default function TaskOverdue() {
  const access = useAccess();
  return <PageContainer title="超时看板">
    <Card title="按负责人聚合"><ReactECharts style={{ height: 260 }} option={{ tooltip: {}, xAxis: { type: 'category', data: ['采购人员', '供应链负责人', '销售/客服'] }, yAxis: { type: 'value' }, series: [{ type: 'bar', data: [3, 1, 2], itemStyle: { color: '#CF1322' } }] }} /></Card>
    <ProTable<API.Task> headerTitle="超时明细" rowKey="id" search={false} request={async () => { const result = await getTasks('all'); return { ...result, data: result.data.slice(0, 2).map((item) => ({ ...item, status: 'overdue' })) }; }} columns={[{ title: '任务', dataIndex: 'title' }, { title: '负责人', dataIndex: 'assignee' }, { title: '截止时间', dataIndex: 'dueAt' }, { title: '操作', valueType: 'option', render: (_, row) => access.canTaskManage ? <Button danger type="link" icon={<BellOutlined />} onClick={async () => { await urge(row.id); message.success('已发送站内信催办'); }}>催办</Button> : [] }]} />
  </PageContainer>;
}
