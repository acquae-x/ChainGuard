import { LockOutlined, MobileOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';
import { history, useModel } from '@umijs/max';
import { Alert, Button, Card, Form, Grid, Input, Space, Tabs, Typography, message } from 'antd';
import { useState } from 'react';
import { DegradeBanner } from '@/components';
import { login } from '@/services/user';

export default function LoginPage() {
  const { setInitialState } = useModel('@@initialState');
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(0);
  const screens = Grid.useBreakpoint();

  const submit = async (values: any) => {
    setLoading(true);
    try {
      const result = await login(values);
      await setInitialState(result);
      message.success('登录成功');
      history.push(result.tenant.status === 'initializing' ? '/onboarding' : '/dashboard');
    } catch (error) {
      setFailed((value) => value + 1);
      message.error('登录失败，请检查账号密码');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <DegradeBanner />
      <div style={{ minHeight: '100vh', display: 'grid', gridTemplateColumns: screens.md ? '55% 45%' : '1fr', background: '#F5F6F8' }}>
        <section style={{ padding: 56, display: screens.md ? 'flex' : 'none', flexDirection: 'column', justifyContent: 'center' }}>
        <Typography.Title level={1}>ChainGuard</Typography.Title>
        <Typography.Title level={3}>供应链中断应急决策系统</Typography.Title>
        <Space direction="vertical" size="middle">
          <Typography.Text><SafetyCertificateOutlined /> 风险提前识别，异常两次点击建事件</Typography.Text>
          <Typography.Text><SafetyCertificateOutlined /> 多 Agent 方案对比，成本、交期、客户影响同屏可比</Typography.Text>
          <Typography.Text><SafetyCertificateOutlined /> 审批、任务、复盘全链路留痕</Typography.Text>
        </Space>
        <Card style={{ marginTop: 32, maxWidth: 720 }} title="系统静态界面预览">
          <Alert type="warning" showIcon message="高风险：苏州芯片封测厂停产影响 MCU-A9 供应" />
          <div style={{ marginTop: 16, height: 180, background: '#fff', border: '1px solid #E5E7EB', display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, padding: 16 }}>
            <div style={{ background: '#F7FAFF', border: '1px solid #D6E4FF' }} />
            <div style={{ background: '#FAFAFA', border: '1px solid #EEE' }} />
          </div>
        </Card>
        </section>
        <section style={{ padding: screens.md ? 56 : 20, display: 'flex', alignItems: 'center' }}>
        <Card style={{ width: '100%' }}>
          <Typography.Title level={3}>登录 ChainGuard</Typography.Title>
          <Tabs items={[
            {
              key: 'password',
              label: '账号密码',
              children: (
                <Form layout="vertical" onFinish={submit} initialValues={{ account: 'scm_lead@chainguard.demo', password: 'Demo@1234' }}>
                  <Form.Item name="account" label="手机号/邮箱" rules={[{ required: true, message: '请输入手机号或邮箱' }]}><Input prefix={<UserOutlined />} /></Form.Item>
                  <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}><Input.Password prefix={<LockOutlined />} /></Form.Item>
                  {failed >= 5 && <Form.Item name="captcha" label="图形验证码" rules={[{ required: true, message: '请输入验证码' }]}><Input placeholder="连续失败后出现，mock 任意输入" /></Form.Item>}
                  {failed >= 10 && <Alert type="error" showIcon message="账号已锁定 15 分钟（mock 状态）" style={{ marginBottom: 16 }} />}
                  <Button block type="primary" htmlType="submit" loading={loading}>登录</Button>
                </Form>
              )
            },
            {
              key: 'sms',
              label: '验证码登录',
              children: (
                <Form layout="vertical" onFinish={submit}>
                  <Form.Item name="account" label="手机号" rules={[{ required: true, pattern: /^1[3-9]\d{9}$/, message: '请输入正确手机号' }]}><Input prefix={<MobileOutlined />} /></Form.Item>
                  <Form.Item name="code" label="短信验证码" rules={[{ required: true, message: '验证码固定 123456' }]}><Input addonAfter="发送验证码" /></Form.Item>
                  <Button block type="primary" htmlType="submit" loading={loading}>登录</Button>
                </Form>
              )
            }
          ]} />
          <Space direction="vertical" style={{ width: '100%', marginTop: 16 }}>
            <Typography.Text type="secondary">演示账号使用对应角色邮箱，统一密码 Demo@1234；登录后可在头像菜单切换角色。</Typography.Text>
            <Space wrap>
              <Button type="link" onClick={() => history.push('/user/register')}>免费注册</Button>
              <Button type="link" onClick={() => history.push('/user/join')}>企业邀请码入口</Button>
              <Button type="link" onClick={() => history.push('/user/reset')}>忘记密码</Button>
              <Button type="link" onClick={() => message.info('该企业未配置 SSO')}>企业单点登录（SSO）</Button>
            </Space>
          </Space>
        </Card>
        </section>
      </div>
    </>
  );
}
