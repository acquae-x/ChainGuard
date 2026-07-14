import { history } from '@umijs/max';
import { Badge, Button, Dropdown, Empty, List, Tabs } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { getNotifications, markRead } from '@/services/notify';
import type { NotificationItem } from '@/services/notify';

export default function NotificationBell() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const reload = async () => { const result = await getNotifications(); setItems(result.data); setUnread(result.unread); };
  useEffect(() => { reload(); }, []);
  // 评审修复：5A 通知类型为 approval_submitted/countersign_*/task_*/decision_*/import_* 等前缀族，
  // 原先按 kind 精确匹配导致新类型通知不落任何标签页（徽标计数却包含它们）。改为前缀分组 + 兜底"系统消息"页。
  const groupOf = (kind: string) => kind.startsWith('risk') ? 'risk' : (kind.startsWith('approval') || kind.startsWith('countersign')) ? 'approval' : kind.startsWith('task') ? 'task' : 'system';
  const list = (group: string) => {
    const data = items.filter((item) => groupOf(String(item.kind)) === group);
    return data.length ? <List size="small" dataSource={data} renderItem={(item) => <List.Item><Button type="link" onClick={async () => { await markRead(item.id); await reload(); history.push(item.target); }}>{item.read ? item.title : <strong>{item.title}</strong>}</Button></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />;
  };
  return <Dropdown trigger={['click']} onOpenChange={(open) => { if (open) reload(); }} popupRender={() => <div style={{ width: window.innerWidth < 768 ? '100vw' : 360, minHeight: window.innerWidth < 768 ? '100vh' : undefined, padding: 12, background: '#fff', boxShadow: '0 4px 16px rgba(0,0,0,0.12)' }}><Tabs size="small" items={[{ key: 'risk', label: '风险告警', children: list('risk') }, { key: 'approval', label: '待我审批', children: list('approval') }, { key: 'task', label: '任务提醒', children: list('task') }, { key: 'system', label: '系统消息', children: list('system') }]} /></div>}><Badge count={unread} size="small"><Button type="text" icon={<BellOutlined />} aria-label="通知" /></Badge></Dropdown>;
}
