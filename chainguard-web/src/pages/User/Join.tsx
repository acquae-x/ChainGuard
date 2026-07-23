import { history, useModel } from '@umijs/max';
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd';
import { useState } from 'react';
import { flushSync } from 'react-dom';
import { joinByInvitation } from '@/services/account';

export default function JoinPage() {
  const { setInitialState } = useModel('@@initialState');
  const invitationCode = new URLSearchParams(location.search).get('code') || '';
  const [loading, setLoading] = useState(false);

  const submit = async (values: any) => {
    setLoading(true);
    try {
      // 加入哪个企业由服务端从邀请码解析，前端既不传也无从指定租户
      const result = await joinByInvitation({
        code: (values.code || '').trim().toUpperCase(),
        name: values.name,
        phone: values.phone,
        email: values.email,
        password: values.password,
      });
      // 与登录页同款：setInitialState 的 Promise 早于 React 提交返回，
      // 直接 push 会让 layout.onPageChange 读到未登录态并把人弹回登录页。
      flushSync(() => { void setInitialState(result); });
      message.success(`已加入「${result.tenant.name}」`);
      history.push('/dashboard');
    } catch (error: any) {
      message.error(error?.message || '加入失败，请核对邀请码');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#F5F6F8', padding: 16 }}>
      <Card style={{ width: '100%', maxWidth: 520 }}>
        <Typography.Title level={3}>加入已有企业</Typography.Title>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="邀请码由企业管理员生成"
          description="角色、部门与数据范围已由管理员在邀请码中预设，加入后即刻生效；邀请码有有效期与使用次数上限。"
        />
        <Form layout="vertical" initialValues={{ code: invitationCode }} onFinish={submit}>
          <Form.Item name="code" label="邀请码" rules={[{ required: true, len: 12, message: '请输入 12 位邀请码' }]}>
            <Input placeholder="例如 ABCD2345EFGH" style={{ textTransform: 'uppercase' }} />
          </Form.Item>
          <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}><Input /></Form.Item>
          <Form.Item name="phone" label="手机号" rules={[{ pattern: /^1[3-9]\d{9}$/, message: '请输入正确手机号' }]}><Input placeholder="手机号与邮箱至少填一项" /></Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '请输入正确邮箱' }]}><Input placeholder="手机号与邮箱至少填一项" /></Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}><Input.Password /></Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>加入企业</Button>
        </Form>
        <Button type="link" block style={{ marginTop: 12 }} onClick={() => history.push('/user/login')}>返回登录</Button>
      </Card>
    </div>
  );
}
