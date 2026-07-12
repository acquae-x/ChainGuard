import { history, useModel } from '@umijs/max';
import { Button, Card, Form, Input, Typography, message } from 'antd';
import { joinTenant } from '@/services/user';

export default function JoinPage() {
  const { setInitialState } = useModel('@@initialState');
  const invitationCode = new URLSearchParams(location.search).get('code') || '';
  const submit = async (values: any) => {
    const result = await joinTenant(values);
    await setInitialState(result);
    message.success('已加入企业');
    history.push('/dashboard');
  };
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#F5F6F8' }}>
      <Card style={{ width: 520 }}>
        <Typography.Title level={3}>加入已有企业</Typography.Title>
        <Form layout="vertical" initialValues={{ code: invitationCode }} onFinish={submit}>
          <Form.Item name="code" label="邀请码或邀请链接" rules={[{ required: true, min: 8, message: '请输入 8 位邀请码' }]}><Input /></Form.Item>
          <Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="phone" label="手机号" rules={[{ required: true, pattern: /^1[3-9]\d{9}$/, message: '请输入正确手机号' }]}><Input /></Form.Item>
          <Form.Item name="sms" label="验证码" rules={[{ required: true }]}><Input addonAfter="发送验证码" /></Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 8 }]}><Input.Password /></Form.Item>
          <Button type="primary" htmlType="submit" block>加入企业</Button>
        </Form>
      </Card>
    </div>
  );
}
