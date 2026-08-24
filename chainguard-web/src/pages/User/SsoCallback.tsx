import { history, useModel } from '@/runtime';
import { Alert, Button, Card, Spin, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { flushSync } from 'react-dom';
import { completeSsoLogin } from '@/services/account';

/** IdP 授权后的落地页：把 state+code 交回后端换取会话，成败都如实呈现。 */
export default function SsoCallbackPage() {
  const { setInitialState } = useModel('@@initialState');
  const [error, setError] = useState('');

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const state = params.get('state') || '';
    const code = params.get('code') || '';
    const denied = params.get('error');
    if (denied) {
      setError(`身份提供方拒绝了本次登录（${denied}）`);
      return;
    }
    if (!state || !code) {
      setError('回调参数不完整，请从登录页重新发起单点登录。');
      return;
    }
    completeSsoLogin(state, code)
      .then((result) => {
        // 同登录页：先同步提交会话状态再跳转，否则 layout 守卫会把人弹回登录页
        flushSync(() => { void setInitialState(result); });
        history.replace(result.tenant.status === 'initializing' ? '/onboarding' : '/dashboard');
      })
      .catch((err: any) => setError(err?.message || '单点登录失败，请联系企业管理员核对 SSO 配置。'));
  }, []);

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#F5F6F8', padding: 16 }}>
      <Card style={{ width: '100%', maxWidth: 520 }}>
        <Typography.Title level={3}>企业单点登录</Typography.Title>
        {error ? (
          <>
            <Alert type="error" showIcon message="单点登录未完成" description={error} />
            <Button type="primary" block style={{ marginTop: 16 }} onClick={() => history.push('/user/login')}>返回登录</Button>
          </>
        ) : (
          <Spin tip="正在校验身份提供方返回的登录凭据…"><div style={{ height: 80 }} /></Spin>
        )}
      </Card>
    </div>
  );
}
