import { useAccess } from '@umijs/max';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Button, Select, Tag, message } from 'antd';
import { getTasks, reassign } from '@/services/task';

export default function TaskAll() {
  const access = useAccess();
  return <PageContainer title="全部任务"><ProTable<API.Task> rowKey="id" request={() => getTasks('all')} columns={[
    { title: '任务', dataIndex: 'title' }, { title: '来源方案', dataIndex: 'source' }, { title: '负责人', dataIndex: 'assignee' },
    { title: '状态', dataIndex: 'status', valueType: 'select', valueEnum: { pending: { text: '待办' }, executing: { text: '进行中' }, done: { text: '已完成' } } },
    { title: '优先级', dataIndex: 'priority', render: (_, row) => <Tag color={row.priority === '高' ? 'red' : 'orange'}>{row.priority}</Tag> }, { title: '截止时间', dataIndex: 'dueAt', valueType: 'dateTime' },
    { title: '操作', valueType: 'option', render: (_, row) => access.canTaskManage ? <Select style={{ width: 130 }} placeholder="改派负责人" options={[{ label: '采购人员', value: '采购人员' }, { label: '供应链负责人', value: '供应链负责人' }]} onChange={async (value) => { await reassign(row.id, value); message.success('已改派'); }} /> : [] }
  ]} /></PageContainer>;
}
