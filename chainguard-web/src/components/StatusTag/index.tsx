import { Tag } from 'antd';
import { STATUS_META } from '@/constants/status';

export default function StatusTag({ status }: { status?: string }) {
  const meta = STATUS_META[status || 'pending'] || { text: status || '未知', color: 'default' };
  return <Tag color={meta.color}>{meta.text}</Tag>;
}
