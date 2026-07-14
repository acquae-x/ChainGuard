import { Button, Card, Typography } from 'antd';
import { history } from '@umijs/max';

export default function ResetPage() {
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#F5F6F8' }}>
      <Card style={{ width: 520 }}>
        <Typography.Title level={3}>忘记密码</Typography.Title>
        <Typography.Paragraph>请联系企业管理员在“系统设置 → 用户管理”中重置密码。管理员会提供一次性临时密码，首次登录后必须立即修改。</Typography.Paragraph>
        <Button type="primary" block onClick={() => history.push('/user/login')}>返回登录</Button>
      </Card>
    </div>
  );
}
