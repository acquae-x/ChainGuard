import { history } from '@umijs/max';
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd';
import { useState } from 'react';
import { confirmPasswordReset, requestPasswordReset, type PasswordResetOutcome } from '@/services/account';

export default function ResetPage() {
  // 带 token 进来 = 邮件里的重置链接；否则是"申请找回"入口
  const token = new URLSearchParams(location.search).get('token') || '';
  const [outcome, setOutcome] = useState<PasswordResetOutcome>();
  const [loading, setLoading] = useState(false);

  const apply = async (values: { account: string }) => {
    setLoading(true);
    try {
      setOutcome(await requestPasswordReset(values.account));
    } catch (error: any) {
      message.error(error?.message || '申请失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  const confirm = async (values: { newPassword: string }) => {
    setLoading(true);
    try {
      await confirmPasswordReset(token, values.newPassword);
      message.success('密码已重置，请用新密码登录');
      history.push('/user/login');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#F5F6F8', padding: 16 }}>
      <Card style={{ width: '100%', maxWidth: 520 }}>
        <Typography.Title level={3}>忘记密码</Typography.Title>
        {token ? (
          <Form layout="vertical" onFinish={confirm}>
            <Typography.Paragraph type="secondary">重置链接仅可使用一次，设置新密码后原有登录会话会全部失效。</Typography.Paragraph>
            <Form.Item name="newPassword" label="新密码" rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}>
              <Input.Password placeholder="至少 8 位" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>设置新密码</Button>
          </Form>
        ) : (
          <>
            <Form layout="vertical" onFinish={apply}>
              <Form.Item name="account" label="账号（手机号/邮箱）" rules={[{ required: true, message: '请输入手机号或邮箱' }]}>
                <Input placeholder="用于定位你的企业账号" />
              </Form.Item>
              <Button type="primary" htmlType="submit" block loading={loading}>提交找回申请</Button>
            </Form>
            {/* 通道未配置时明确告知"无法自助"并给出管理员兜底路径，绝不显示"邮件已发送" */}
            {outcome && (
              <Alert
                style={{ marginTop: 16 }}
                showIcon
                type={outcome.mode === 'self_service' ? 'success' : 'warning'}
                message={outcome.mode === 'self_service' ? '重置链接已发送' : '当前无法自助重置，请走管理员兜底'}
                description={outcome.message}
              />
            )}
          </>
        )}
        <Button type="link" block style={{ marginTop: 12 }} onClick={() => history.push('/user/login')}>返回登录</Button>
      </Card>
    </div>
  );
}
