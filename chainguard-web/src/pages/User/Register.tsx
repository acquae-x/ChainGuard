import { history, useModel } from '@/runtime';
import { Button, Card, Form, Input, Radio, Select, Space, Steps, Typography, message } from 'antd';
import { useState } from 'react';
import { registerTenant } from '@/services/user';
import { isApiMode } from '@/services/dataMode';

export default function RegisterPage() {
  const { setInitialState } = useModel('@@initialState');
  const [step, setStep] = useState(0);
  const [form] = Form.useForm();
  const apiMode = isApiMode();
  const next = async () => {
    await form.validateFields();
    if (step < 2) setStep(step + 1);
    else {
      const result = await registerTenant(form.getFieldsValue(true));
      await setInitialState(result);
      message.success('企业空间已创建');
      history.push('/onboarding');
    }
  };
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#F5F6F8', padding: 24 }}>
      <Card style={{ width: 760 }}>
        <Typography.Title level={3}>开通 ChainGuard 企业空间</Typography.Title>
        <Steps current={step} items={[{ title: '账号验证' }, { title: '企业信息' }, { title: '开通方式' }]} style={{ marginBottom: 24 }} />
        <Form form={form} layout="vertical">
          {step === 0 && <>
            <Form.Item name="phone" label="手机号" rules={[{ required: true, pattern: /^1[3-9]\d{9}$/, message: '请输入 +86 手机号' }]}><Input /></Form.Item>
            {!apiMode && <Form.Item name="code" label="短信验证码" rules={[{ required: true, message: '请输入验证码' }]}><Input addonAfter="演示功能" /></Form.Item>}
            <Form.Item name="password" label="密码" rules={[{ required: true, min: 8, message: '至少 8 位' }]}><Input.Password /></Form.Item>
            <Button type="link" onClick={() => history.push('/user/join')}>已有同事在用？通过邀请码加入</Button>
          </>}
          {step === 1 && <>
            <Form.Item name="companyName" label="企业名称" rules={[{ required: true, message: '请输入企业名称' }]}><Input autoComplete="organization" /></Form.Item>
            <Form.Item name="industry" label="行业" rules={[{ required: true }]}><Select options={['电子制造', '汽车零部件', '食品饮料', '医药', '日用消费品', '机械设备', '其他'].map((value) => ({ label: value, value }))} /></Form.Item>
            <Form.Item name="scale" label="企业规模" rules={[{ required: true }]}><Radio.Group options={['<50 人', '50-200', '200-1000', '>1000'].map((value) => ({ label: value, value }))} /></Form.Item>
            <Form.Item name="ownerRole" label="您的角色" rules={[{ required: true }]}><Select options={['老板/总经理', '供应链负责人', 'IT 管理员', '其他'].map((value) => ({ label: value, value }))} /></Form.Item>
          </>}
          {step === 2 && <>
            <Form.Item name="plan" initialValue="trial"><Radio.Group optionType="button" buttonStyle="solid" options={[{ label: '免费试用 30 天', value: 'trial' }, { label: '企业授权码（即将上线）', value: 'license', disabled: true }]} /></Form.Item>
            <Typography.Text type="secondary">当前为云端 SaaS 版，私有化部署请联系我们。</Typography.Text>
          </>}
        </Form>
        <Space style={{ marginTop: 24 }}>
          <Button disabled={step === 0} onClick={() => setStep(step - 1)}>上一步</Button>
          <Button type="primary" onClick={next}>{step === 2 ? '创建企业空间' : '下一步'}</Button>
          <Typography.Text type="secondary">第 {step + 1}/3 步，约还需 1 分钟</Typography.Text>
        </Space>
      </Card>
    </div>
  );
}
