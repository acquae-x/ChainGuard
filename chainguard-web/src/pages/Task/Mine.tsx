import { history, useAccess, useModel } from '@/runtime';
import { PageContainer } from '@/components/pro';
import { Badge, Button, Card, Checkbox, Flex, Radio, Space, Tag, Typography, message } from 'antd';
import { CheckOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { getTasks, updateTaskStatus } from '@/services/task';

const statusMeta = [{ key: 'pending', title: '待办' }, { key: 'executing', title: '进行中' }, { key: 'done', title: '已完成' }];

export default function TaskMine() {
  const access = useAccess();
  const { initialState } = useModel('@@initialState');
  const [tasks, setTasks] = useState<API.Task[]>([]);
  const [view, setView] = useState('board');
  useEffect(() => { getTasks('mine').then((result) => setTasks(result.data.filter((item) => item.roleCode === initialState?.currentUser?.roleCode))); }, [initialState?.currentUser?.roleCode]);
  const complete = async (task: API.Task) => { await updateTaskStatus(task.id, 'done'); setTasks((items) => items.map((item) => item.id === task.id ? { ...item, status: 'done' } : item)); message.success('任务已完成'); };
  const taskCard = (task: API.Task) => <Card key={task.id} size="small" title={task.title} extra={<Tag color={task.priority === '高' ? 'red' : 'orange'}>{task.priority}</Tag>}>
    <Space direction="vertical" style={{ width: '100%' }}><Button type="link" style={{ padding: 0 }} onClick={() => history.push(task.incidentId ? `/incident/${task.incidentId}` : '/incident/list')}>{task.source}</Button><Typography.Text type="secondary">负责人：{task.assignee}</Typography.Text><Badge status="warning" text={`截止 ${task.dueAt}`} />{task.checklist.map((item) => <Checkbox key={item.text} defaultChecked={item.done}>{item.text}</Checkbox>)}{access.canTaskWrite && task.status !== 'done' && <Button block icon={<CheckOutlined />} onClick={() => complete(task)}>完成任务</Button>}</Space>
  </Card>;
  return <PageContainer title="我的任务" extra={<Radio.Group value={view} onChange={(event) => setView(event.target.value)} optionType="button" options={[{ label: '看板', value: 'board' }, { label: <><UnorderedListOutlined /> 列表</>, value: 'list' }]} />}>
    {view === 'board' ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(260px, 1fr))', gap: 16, overflowX: 'auto' }}>{statusMeta.map((status) => <section key={status.key} style={{ minWidth: 260 }}><Flex justify="space-between"><Typography.Title level={5}>{status.title}</Typography.Title><Tag>{tasks.filter((item) => item.status === status.key).length}</Tag></Flex><Space direction="vertical" style={{ width: '100%' }}>{tasks.filter((item) => item.status === status.key).map(taskCard)}</Space></section>)}</div> : <Space direction="vertical" style={{ width: '100%' }}>{tasks.map(taskCard)}</Space>}
  </PageContainer>;
}
