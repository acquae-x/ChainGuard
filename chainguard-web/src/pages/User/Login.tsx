import { LockOutlined, MobileOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';
import { history, useModel } from '@/runtime';
import { Alert, App, Button, Card, Form, Grid, Input, Space, Tabs, Typography } from 'antd';
import { useState } from 'react';
import { flushSync } from 'react-dom';
import { DegradeBanner } from '@/components';
import { login } from '@/services/user';
import { startSsoLogin } from '@/services/account';
import { isApiMode } from '@/services/dataMode';

export default function LoginPage() {
  const { message } = App.useApp();
  const { setInitialState } = useModel('@@initialState');
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(0);
  // 后端 423 = 账号级锁定；与 429（IP 限流）是两回事，提示也必须分开
  const [lockNotice, setLockNotice] = useState('');
  const [form] = Form.useForm();
  const screens = Grid.useBreakpoint();
  const apiMode = isApiMode();
  // CSS Grid tracks default to min-content sizing.  The preview card has an
  // intrinsic width, so without an explicit zero minimum it can push the
  // login pane outside a 1280px viewport.  Keep both tracks shrinkable.
  const desktopPadding = screens.xxl ? 56 : screens.lg ? 32 : 20;

  // SSO 入口：先探测该账号所属企业是否真的配了 SSO，没配就照实说，不跳假流程。
  const goSso = async () => {
    const account = (form.getFieldValue('account') || '').trim();
    try {
      const started = await startSsoLogin({ account });
      window.location.href = started.authorizeUrl;
    } catch (error: any) {
      message.info(error?.message || '该企业未配置企业单点登录（SSO）');
    }
  };

  const submit = async (values: any) => {
    setLoading(true);
    setLockNotice('');
    try {
      const result = await login(values);
      // setInitialState 的 Promise 会在 React 真正提交状态前返回；若紧接着
      // history.push，layout.onPageChange 仍可能读到未登录状态并把用户推回登录页。
      // 同步提交会话状态后再导航，消除这条竞态。
      flushSync(() => {
        void setInitialState(result);
      });
      message.success('登录成功');
      const requested = new URLSearchParams(history.location.search).get('redirect');
      const safeRequested = requested?.startsWith('/') && !requested.startsWith('//') && !requested.startsWith('/user/login')
        ? requested
        : undefined;
      history.replace(safeRequested || (result.tenant.status === 'initializing' ? '/onboarding' : '/dashboard'));
    } catch (error: any) {
      setFailed((value) => value + 1);
      // 账号锁定（423）要常驻提示，一次性 toast 容易被忽略而让用户反复重试
      if (error?.httpStatus === 423) setLockNotice(error.message);
      // 透传后端错误信封的真实原因（如限流"请求过于频繁"），不要一律误报成密码错误
      message.error(error?.message || '登录失败，请检查账号密码');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <DegradeBanner />
      <div data-testid="login-page-layout" style={{ minHeight: '100vh', display: 'grid', gridTemplateColumns: screens.md ? 'minmax(0, 55%) minmax(0, 45%)' : '1fr', background: '#F5F6F8' }}>
        <section style={{ minWidth: 0, overflow: 'hidden', padding: desktopPadding, display: screens.md ? 'flex' : 'none', flexDirection: 'column', justifyContent: 'center' }}>
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
        <section style={{ minWidth: 0, padding: screens.md ? desktopPadding : 20, display: 'flex', alignItems: 'center' }}>
        <Card style={{ width: '100%' }}>
          <Typography.Title level={3}>登录 ChainGuard</Typography.Title>
          <Tabs items={[
            {
              key: 'password',
              label: '账号密码',
              children: (
                <Form form={form} layout="vertical" onFinish={submit} initialValues={apiMode ? undefined : { account: 'scm_lead@chainguard.demo', password: 'Demo@1234' }}>
                  <Form.Item name="account" label="手机号/邮箱" rules={[{ required: true, message: '请输入手机号或邮箱' }]}><Input autoComplete="username" prefix={<UserOutlined />} /></Form.Item>
                  <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}><Input.Password autoComplete="current-password" prefix={<LockOutlined />} /></Form.Item>
                  {!apiMode && failed >= 5 && <Form.Item name="captcha" label="图形验证码" rules={[{ required: true, message: '请输入验证码' }]}><Input placeholder="连续失败后出现，mock 任意输入" /></Form.Item>}
                  {!apiMode && failed >= 10 && <Alert type="error" showIcon message="账号已锁定 15 分钟（mock 状态）" style={{ marginBottom: 16 }} />}
                  {/* 账号锁定与 IP 限流是两条独立防线，提示分开呈现，避免用户误以为只要换个网络就能继续试 */}
                  {lockNotice && <Alert type="error" showIcon message="账号已锁定" description={`${lockNotice}，也可联系企业管理员在「系统设置 → 用户管理」中立即解锁。`} style={{ marginBottom: 16 }} />}
                  {apiMode && !lockNotice && failed >= 3 && <Alert type="info" showIcon message="登录接口限流 5 次/分钟，多次失败请等待 1 分钟再试" style={{ marginBottom: 16 }} />}
                  <Button block type="primary" htmlType="submit" loading={loading}>登录</Button>
                </Form>
              )
            },
            ...(!apiMode ? [{
              key: 'sms',
              label: '验证码登录',
              children: (
                <Form layout="vertical" onFinish={submit}>
                  <Form.Item name="account" label="手机号" rules={[{ required: true, pattern: /^1[3-9]\d{9}$/, message: '请输入正确手机号' }]}><Input prefix={<MobileOutlined />} /></Form.Item>
                  <Form.Item name="code" label="短信验证码" rules={[{ required: true, message: '验证码固定 123456' }]}><Input addonAfter="发送验证码" /></Form.Item>
                  <Button block type="primary" htmlType="submit" loading={loading}>登录</Button>
                </Form>
              )
            }] : [])
          ]} />
          <Space direction="vertical" style={{ width: '100%', marginTop: 16 }}>
            {!apiMode && <Typography.Text type="secondary">演示账号使用对应角色邮箱，统一密码 Demo@1234；登录后可在头像菜单切换角色。</Typography.Text>}
            <Space wrap>
              <Button type="link" onClick={() => history.push('/user/register')}>免费注册</Button>
              <Button type="link" onClick={() => history.push('/user/join')}>企业邀请码入口</Button>
              <Button type="link" onClick={() => history.push('/user/reset')}>忘记密码</Button>
              <Button type="link" onClick={goSso}>企业单点登录（SSO）</Button>
            </Space>
          </Space>
        </Card>
        </section>
      </div>
    </>
  );
}
