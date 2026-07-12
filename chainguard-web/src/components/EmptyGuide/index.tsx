import { Empty, Button, Space, Typography } from 'antd';

export default function EmptyGuide({
  title,
  description,
  actionText,
  onAction
}: {
  title: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
}) {
  return (
    <Empty description={<Space direction="vertical"><Typography.Text strong>{title}</Typography.Text>{description && <Typography.Text type="secondary">{description}</Typography.Text>}</Space>}>
      {actionText && <Button type="primary" onClick={onAction}>{actionText}</Button>}
    </Empty>
  );
}
