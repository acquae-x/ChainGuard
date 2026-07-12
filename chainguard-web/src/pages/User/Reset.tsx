import { Button, Card, Form, Input, Steps, Typography, message } from 'antd';
import { useState } from 'react';

export default function ResetPage() {
  const [step, setStep] = useState(0);
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#F5F6F8' }}>
      <Card style={{ width: 520 }}>
        <Typography.Title level={3}>重置密码</Typography.Title>
        <Steps size="small" current={step} items={[{ title: '验证手机号' }, { title: '重设密码' }, { title: '完成' }]} />
        <Form layout="vertical" style={{ marginTop: 24 }} onFinish={() => step < 2 ? setStep(step + 1) : message.success('密码已重置')}>
          {step === 0 && <><Form.Item name="phone" label="手机号" rules={[{ required: true, pattern: /^1[3-9]\d{9}$/ }]}><Input /></Form.Item><Form.Item name="code" label="验证码"><Input addonAfter="发送验证码" /></Form.Item></>}
          {step === 1 && <Form.Item name="password" label="新密码" rules={[{ required: true, min: 8 }]}><Input.Password /></Form.Item>}
          {step === 2 && <Typography.Text>密码已重置，请返回登录。</Typography.Text>}
          <Button type="primary" htmlType="submit" block style={{ marginTop: 16 }}>{step === 2 ? '完成' : '下一步'}</Button>
        </Form>
      </Card>
    </div>
  );
}
