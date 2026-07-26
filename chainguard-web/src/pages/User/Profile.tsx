import { history, useModel } from '@umijs/max';
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd';
import { useEffect } from 'react';
import { changePassword, logout } from '@/services/user';

export default function Profile() {
  const { initialState } = useModel('@@initialState');
  // mustChangePassword=true 时明确告知“管理员已重置密码，首次登录必须修改”，
  // 标题与浏览器标题都不再是“工作台”。
  const forced = initialState?.currentUser?.mustChangePassword;
  useEffect(() => {
    document.title = forced ? '首次登录 · 修改密码 — ChainGuard' : '个人设置 — ChainGuard';
  }, [forced]);
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16, background: '#F5F6F8' }}>
      <Card style={{ width: 'min(480px, 100%)' }}>
        <Typography.Title level={3}>{forced ? '首次登录，请修改密码' : '个人设置'}</Typography.Title>
        {forced ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="管理员已重置您的密码"
            description="您正在使用管理员下发的一次性临时密码首次登录，必须先修改密码后才能继续使用系统。"
          />
        ) : (
          <Typography.Paragraph type="secondary">修改成功后会作废所有设备的刷新令牌，请使用新密码重新登录。</Typography.Paragraph>
        )}
        <Form
          layout="vertical"
          onFinish={async (values) => {
            await changePassword(values);
            await logout();
            message.success('密码已修改，请重新登录');
            history.push('/user/login');
          }}
        >
          <Form.Item name="oldPassword" label={forced ? '临时密码' : '旧密码'} rules={[{ required: true }]}><Input.Password /></Form.Item>
          <Form.Item name="newPassword" label="新密码" rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}><Input.Password /></Form.Item>
          <Form.Item name="confirm" label="确认新密码" dependencies={['newPassword']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator: (_, value) => (value === getFieldValue('newPassword') ? Promise.resolve() : Promise.reject(new Error('两次密码不一致'))) })]}><Input.Password /></Form.Item>
          <Button block type="primary" htmlType="submit">修改密码并重新登录</Button>
        </Form>
      </Card>
    </div>
  );
}
