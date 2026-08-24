import { PageContainer, ProTable } from '@/components/pro';
import { Empty, Tag } from 'antd';
import { useEffect, useState } from 'react';
import { getExperienceCards } from '@/services/decision';

const STATUS_LABELS: Record<string, string> = { generated: '已生成', confirmed: '已确认', verified: '已验证', completed: '已完成' };
const STATUS_COLORS: Record<string, string> = { generated: 'blue', confirmed: 'green', verified: 'green', completed: 'green' };

export default function Experience() {
  const [cards, setCards] = useState<API.ExperienceCard[]>([]);
  useEffect(() => { getExperienceCards().then(setCards); }, []);
  return <PageContainer title="经验卡片" subTitle="仅展示当前租户沉淀的真实决策经验"><ProTable search={false} rowKey="id" dataSource={cards} locale={{ emptyText: <Empty description="暂无本租户经验卡" /> }} columns={[{ title: '编号', dataIndex: 'id' }, { title: '事件/物料上下文', dataIndex: 'scenario' }, { title: '推荐动作', dataIndex: 'recommendedPattern' }, { title: '关键约束', dataIndex: 'triggerConditions', render: (_, row) => row.triggerConditions.join('；') }, { title: '执行结果', dataIndex: ['outcome', 'summary'] }, { title: '来源作业', dataIndex: ['source', 'jobId'] }, // 兜底会把任何未知状态说成「已生成」——seed 的 verified 卡因此被标错。
{ title: '状态', dataIndex: 'status', render: (_, row) => <Tag color={STATUS_COLORS[row.status] || 'default'}>{STATUS_LABELS[row.status] || row.status}</Tag> }]} /></PageContainer>;
}
