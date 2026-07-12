import { PageContainer } from '@ant-design/pro-components';
import { Button, Card, Descriptions, Form, Input, Select, Space, Tag, message } from 'antd';
import { getTenant } from '@/services/settings';
import { useEffect, useState } from 'react';

export default function TenantSettings() {
  const [tenant, setTenant] = useState<API.Tenant>();
  useEffect(() => { getTenant().then(setTenant); }, []);
  return <PageContainer title="企业信息"><Card><Descriptions column={2} items={[{ key: 'plan', label: '当前套餐', children: <Tag color="blue">30 天试用</Tag> }, { key: 'end', label: '到期时间', children: tenant?.trialEndAt }, { key: 'demo', label: '示例数据', children: tenant?.demoDataFlag ? '已启用' : '未启用' }]} /><Form layout="vertical" style={{ maxWidth: 640, marginTop: 24 }} initialValues={tenant} onFinish={() => message.success('企业信息已保存')}><Form.Item name="name" label="企业名称"><Input /></Form.Item><Form.Item name="industry" label="所属行业"><Select options={[{ label: '电子制造', value: '电子制造' }, { label: '机械制造', value: '机械制造' }]} /></Form.Item><Form.Item name="scale" label="企业规模"><Select options={[{ label: '50-200', value: '50-200' }, { label: '200-1000', value: '200-1000' }]} /></Form.Item><Space><Button type="primary" htmlType="submit">保存</Button><Button danger>清空示例数据</Button></Space></Form></Card></PageContainer>;
}
