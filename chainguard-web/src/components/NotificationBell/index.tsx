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
  const list = (kind: NotificationItem['kind']) => {
    const data = items.filter((item) => item.kind === kind);
    return data.length ? <List size="small" dataSource={data} renderItem={(item) => <List.Item><Button type="link" onClick={async () => { await markRead(item.id); await reload(); history.push(item.target); }}>{item.read ? item.title : <strong>{item.title}</strong>}</Button></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />;
  };
  return <Dropdown trigger={['click']} onOpenChange={(open) => { if (open) reload(); }} popupRender={() => <div style={{ width: window.innerWidth < 768 ? '100vw' : 360, minHeight: window.innerWidth < 768 ? '100vh' : undefined, padding: 12, background: '#fff', boxShadow: '0 4px 16px rgba(0,0,0,0.12)' }}><Tabs size="small" items={[{ key: 'risk', label: '风险告警', children: list('risk') }, { key: 'approval', label: '待我审批', children: list('approval') }, { key: 'task', label: '任务提醒', children: list('task') }]} /></div>}><Badge count={unread} size="small"><Button type="text" icon={<BellOutlined />} aria-label="通知" /></Badge></Dropdown>;
}
