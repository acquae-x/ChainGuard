import { history } from '@umijs/max';
import { Badge, Button, Drawer, Empty, Grid, List, Popover, Tabs, Tag } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { useEffect, useRef, useState } from 'react';
import { getNotifications, markRead } from '@/services/notify';
import type { NotificationItem } from '@/services/notify';

const KIND_META: Record<string, { label: string; color: string }> = {
  risk: { label: '风险预警', color: 'red' },
  approval: { label: '审批', color: 'blue' },
  task: { label: '任务', color: 'green' },
  system: { label: '系统', color: 'default' },
};
// 5A 通知类型是 approval_submitted/countersign_*/task_*/decision_*/import_*/risk_* 前缀族。
const groupOf = (kind: string) =>
  kind.startsWith('risk') ? 'risk'
    : kind.startsWith('approval') || kind.startsWith('countersign') || kind.startsWith('decision') ? 'approval'
    : kind.startsWith('task') ? 'task'
    : 'system';
const metaOf = (kind: string) => KIND_META[groupOf(kind)];
const fmtTime = (iso?: string) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

export default function NotificationBell() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const bellRef = useRef<HTMLButtonElement>(null);
  const screens = Grid.useBreakpoint();
  const mobile = !screens.md;
  const reload = async () => { const r = await getNotifications(); setItems(r.data); setUnread(r.unread); };
  useEffect(() => { reload(); }, []);
  useEffect(() => { if (open) reload(); }, [open]);

  const focusBell = () => requestAnimationFrame(() => bellRef.current?.focus());
  const handleOpenChange = (next: boolean) => { setOpen(next); if (!next) focusBell(); };
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') handleOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open]);

  // 评审修复：点击通知后先关闭弹层并标记已读，再跳转，避免弹层持续遮挡目标页。
  const onItem = async (item: NotificationItem) => {
    setOpen(false);
    await markRead(item.id);
    await reload();
    history.push(item.target);
  };

  const listFor = (group: string) => {
    const data = items.filter((item) => groupOf(String(item.kind)) === group);
    if (!data.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />;
    return (
      <List
        size="small"
        dataSource={data}
        renderItem={(item) => {
          const meta = metaOf(String(item.kind));
          return (
            <List.Item style={{ cursor: 'pointer', alignItems: 'flex-start' }} onClick={() => onItem(item)}>
              <List.Item.Meta
                title={<span>{!item.read && <Badge status="processing" style={{ marginRight: 6 }} />}<span style={{ fontWeight: item.read ? 400 : 600 }}>{item.title}</span></span>}
                description={<span><Tag color={meta.color} bordered={false} style={{ marginRight: 6 }}>{meta.label}</Tag><span style={{ color: '#999', fontSize: 12 }}>{fmtTime(item.createdAt)}</span></span>}
              />
            </List.Item>
          );
        }}
      />
    );
  };

  const panel = (
    <Tabs
      size="small"
      items={[
        { key: 'risk', label: '风险告警', children: listFor('risk') },
        { key: 'approval', label: '待我审批', children: listFor('approval') },
        { key: 'task', label: '任务提醒', children: listFor('task') },
        { key: 'system', label: '系统消息', children: listFor('system') },
      ]}
    />
  );

  const trigger = (
    <Badge count={unread} size="small">
      <Button ref={bellRef} type="text" icon={<BellOutlined />} aria-label="通知" aria-haspopup="true" aria-expanded={open} onClick={mobile ? () => setOpen((v) => !v) : undefined} />
    </Badge>
  );

  if (mobile) {
    return (
      <>
        {trigger}
        <Drawer title="通知" placement="right" width="100vw" open={open} onClose={() => handleOpenChange(false)} styles={{ body: { padding: 12 } }}>
          {panel}
        </Drawer>
      </>
    );
  }
  return (
    <Popover open={open} onOpenChange={handleOpenChange} trigger="click" placement="bottomRight" content={<div style={{ width: 360, maxHeight: '70vh', overflowY: 'auto' }}>{panel}</div>}>
      {trigger}
    </Popover>
  );
}
