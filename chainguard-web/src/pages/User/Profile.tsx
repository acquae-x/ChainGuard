import { history } from '@umijs/max';
import { Button, Card, Form, Input, Typography, message } from 'antd';
import { changePassword, logout } from '@/services/user';

export default function Profile() {
  return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16, background: '#F5F6F8' }}><Card style={{ width: 'min(480px, 100%)' }}><Typography.Title level={3}>个人设置</Typography.Title><Typography.Paragraph type="secondary">修改成功后会作废所有设备的刷新令牌，请使用新密码重新登录。</Typography.Paragraph><Form layout="vertical" onFinish={async (values) => { await changePassword(values); await logout(); message.success('密码已修改，请重新登录'); history.push('/user/login'); }}><Form.Item name="oldPassword" label="旧密码" rules={[{ required: true }]}><Input.Password /></Form.Item><Form.Item name="newPassword" label="新密码" rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}><Input.Password /></Form.Item><Form.Item name="confirm" label="确认新密码" dependencies={['newPassword']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator: (_, value) => value === getFieldValue('newPassword') ? Promise.resolve() : Promise.reject(new Error('两次密码不一致')) })]}><Input.Password /></Form.Item><Button block type="primary" htmlType="submit">修改密码并重新登录</Button></Form></Card></div>;
}
