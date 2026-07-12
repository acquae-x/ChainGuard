import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Tag } from 'antd';
import { useEffect, useState } from 'react';
import { SensitiveField } from '@/components';
import { workflowStore } from '@/services/workflowStore';

export default function Experience() {
  const [cards, setCards] = useState<any[]>([]);
  useEffect(() => setCards(workflowStore.listExperiences()), []);
  return <PageContainer title="经验卡片"><ProTable search={false} rowKey="id" dataSource={cards} columns={[{ title: '编号', dataIndex: 'id' }, { title: '触发条件', dataIndex: 'trigger' }, { title: '推荐动作', dataIndex: 'action' }, { title: '关键约束', dataIndex: 'constraint' }, { title: '效果', dataIndex: 'outcome', render: (_, row) => <SensitiveField field="profit" value={row.outcome} /> }, { title: '状态', dataIndex: 'status', render: (_, row) => <Tag color={row.status === 'verified' ? 'green' : 'blue'}>{row.status === 'verified' ? '已验证' : '待复核'}</Tag> }]} /></PageContainer>;
}
