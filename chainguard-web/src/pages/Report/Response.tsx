import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Tag } from 'antd';
import { SensitiveField } from '@/components';

export default function Response() {
  return <PageContainer title="应急效果"><ProTable search={false} rowKey="id" dataSource={[{ id: 'INC-20260709-001', title: '苏州芯片封测厂停产', response: 9.5, costDiff: -22000, orders: 3, result: '达标' }]} columns={[{ title: '事件', dataIndex: 'id' }, { title: '标题', dataIndex: 'title' }, { title: '响应时长', dataIndex: 'response', renderText: (value) => `${value} 小时` }, { title: '预算偏差', dataIndex: 'costDiff', render: (_, row) => <SensitiveField field="cost" value={`¥${row.costDiff.toLocaleString()}`} /> }, { title: '受影响订单', dataIndex: 'orders' }, { title: '效果', dataIndex: 'result', render: () => <Tag color="green">达标</Tag> }]} /></PageContainer>;
}
