import { EyeOutlined } from '@ant-design/icons';
import { Button, Descriptions, Drawer, Space, Tag } from 'antd';
import { useState } from 'react';
import type { ReactNode } from 'react';

export default function ObjectPeek({ type, name, data }: { type: string; name: string; data?: Record<string, ReactNode> }) {
  const [open, setOpen] = useState(false);
  const content = data || { 编号: `${type}-${name}`, 状态: <Tag color="green">正常</Tag>, 负责人: '系统示例' };
  return (
    <>
      <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => setOpen(true)}>{name}</Button>
      <Drawer title={`${type}概要`} width={420} open={open} onClose={() => setOpen(false)}>
        <Descriptions column={1} bordered size="small">
          {Object.entries(content).map(([key, value]) => <Descriptions.Item key={key} label={key}>{value}</Descriptions.Item>)}
        </Descriptions>
        <Space style={{ marginTop: 16 }}>
          <Button type="primary">查看完整详情</Button>
          <Button onClick={() => setOpen(false)}>关闭</Button>
        </Space>
      </Drawer>
    </>
  );
}
