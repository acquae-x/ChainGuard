import { PageContainer } from '@ant-design/pro-components';
import { Button, Card, Descriptions, Form, Input, Select, Space, Tag, message } from 'antd';
import { getTenant, saveTenant } from '@/services/settings';
import { useEffect, useState } from 'react';
import { useModel } from '@umijs/max';

export default function TenantSettings() {
  const [tenant, setTenant] = useState<API.Tenant>();
  const [form] = Form.useForm<Pick<API.Tenant, 'name' | 'industry' | 'scale' | 'timezone'>>();
  const { initialState, setInitialState } = useModel('@@initialState');
  useEffect(() => {
    getTenant().then((value) => {
      setTenant(value);
      form.setFieldsValue(value);
    });
  }, [form]);
  const save = async (values: Pick<API.Tenant, 'name' | 'industry' | 'scale' | 'timezone'>) => {
    const saved = await saveTenant(values);
    setTenant(saved);
    form.setFieldsValue(saved);
    await setInitialState({ ...initialState, tenant: saved });
    message.success('企业信息已保存；日历指标已按新时区重新统计');
  };
  return <PageContainer title="企业信息"><Card><Descriptions column={2} items={[{ key: 'plan', label: '当前套餐', children: <Tag color="blue">30 天试用</Tag> }, { key: 'end', label: '到期时间', children: tenant?.trialEndAt }, { key: 'demo', label: '示例数据', children: tenant?.demoDataFlag ? '已启用' : '未启用' }]} /><Form form={form} layout="vertical" style={{ maxWidth: 640, marginTop: 24 }} onFinish={save}><Form.Item name="name" label="企业名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="industry" label="所属行业" rules={[{ required: true }]}><Select options={[{ label: '电子制造', value: '电子制造' }, { label: '机械制造', value: '机械制造' }]} /></Form.Item><Form.Item name="scale" label="企业规模" rules={[{ required: true }]}><Select options={[{ label: '50-200', value: '50-200' }, { label: '200-1000', value: '200-1000' }]} /></Form.Item><Form.Item name="timezone" label="统计时区" extra="“今日、本周、本月”和报表导出均按此时区统计；调整后历史指标会按新口径重新归类。" rules={[{ required: true }]}><Select showSearch options={['UTC', 'Asia/Shanghai', 'Asia/Tokyo', 'Asia/Singapore', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Los_Angeles'].map((value) => ({ label: value, value }))} /></Form.Item><Space><Button type="primary" htmlType="submit">保存</Button><Button danger>清空示例数据</Button></Space></Form></Card></PageContainer>;
}
