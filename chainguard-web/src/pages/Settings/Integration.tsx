import { PageContainer } from '@ant-design/pro-components';
import { Alert, Button, Card, List, Tag } from 'antd';
import { ApiOutlined, LinkOutlined } from '@ant-design/icons';

export default function Integration() {
  const items = [{ name: '企业微信 / 钉钉通知', icon: <LinkOutlined /> }, { name: 'ERP 主数据同步', icon: <ApiOutlined /> }, { name: 'Webhook 事件推送', icon: <ApiOutlined /> }];
  return <PageContainer title="系统集成"><Alert type="info" showIcon message="集成能力属于后续阶段，本期仅预留可替换服务接口。" style={{ marginBottom: 16 }} /><Card><List dataSource={items} renderItem={(item) => <List.Item actions={[<Button key="config" disabled>暂未开放</Button>]}><List.Item.Meta avatar={item.icon} title={item.name} description={<Tag>规划中</Tag>} /></List.Item>} /></Card></PageContainer>;
}
