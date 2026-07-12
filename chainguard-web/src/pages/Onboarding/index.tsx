import { history } from '@umijs/max';
import { Alert, Button, Card, Checkbox, Col, Form, Input, Radio, Row, Slider, Space, Steps, Tour, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import { ImportWizard } from '@/components';
import { getTemplates, saveProgress, startDrillIncident } from '@/services/onboarding';

export default function OnboardingPage() {
  const [step, setStep] = useState(0);
  const [templates, setTemplates] = useState<any[]>([]);
  const [tourOpen, setTourOpen] = useState(false);
  useEffect(() => { getTemplates().then(setTemplates); }, []);
  const next = async () => {
    await saveProgress({ step });
    if (step === 5) {
      await startDrillIncident();
      message.success('示例演练已生成');
      history.push('/dashboard');
    } else setStep(step + 1);
  };
  return (
    <Card>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={3}>企业初始化向导</Typography.Title>
        <Button onClick={() => history.push('/dashboard')}>稍后再说，直接进入系统</Button>
      </Space>
      <Steps current={step} items={['选行业模板', '选业务模块', '导入基础数据', '配置风险阈值', '邀请成员', '示例应急演练'].map((title) => ({ title }))} style={{ marginBottom: 24 }} />
      {step === 0 && <Radio.Group defaultValue="electronics" style={{ width: '100%' }}><Row gutter={16}>{templates.map((item) => <Col span={8} key={item.id}><Card><Radio value={item.id}>{item.name}</Radio><p>{item.desc}</p></Card></Col>)}</Row></Radio.Group>}
      {step === 1 && <Checkbox.Group defaultValue={['风险监控', '应急决策', '库存管理', '订单管理', '供应商管理']} options={['风险监控', '应急决策', '库存管理', '订单管理', '供应商管理', '物流管理', '报表']} />}
      {step === 2 && <><Alert type="warning" showIcon message="跳过将自动灌入行业模板示例数据，并标记 demoDataFlag。" style={{ marginBottom: 16 }} /><ImportWizard embedded /></>}
      {step === 3 && <Form layout="vertical"><Form.Item label="安全库存预警线"><Slider defaultValue={20} marks={{ 20: '20%' }} /></Form.Item><Form.Item label="交期延误容忍天数"><Slider defaultValue={3} min={1} max={10} /></Form.Item><Form.Item label="单一供应商依赖占比上限"><Slider defaultValue={60} marks={{ 60: '60%' }} /></Form.Item></Form>}
      {step === 4 && <Form layout="vertical"><Form.Item label="批量输入手机号"><Input.TextArea rows={5} placeholder="每行一个手机号" /></Form.Item><Form.Item label="默认角色"><Radio.Group defaultValue="buyer" options={[{ label: '采购人员', value: 'buyer' }, { label: '仓库人员', value: 'warehouse' }, { label: '销售/客服', value: 'sales' }]} /></Form.Item><Button>复制邀请链接到微信群</Button></Form>}
      {step === 5 && <Card title="一键触发 supplier_shutdown 演练"><p>系统将引导你看到风险告警、打开事件、查看多 Agent 方案并点一次批准。</p><Button onClick={() => setTourOpen(true)}>查看引导蒙层</Button><Tour open={tourOpen} onClose={() => setTourOpen(false)} steps={[{ title: '告警条', description: '这里展示供应商停产告警' }, { title: '事件卡', description: '进入事件详情' }, { title: '方案对比', description: '查看多方案指标' }, { title: '批准按钮', description: '完成第一次演练' }]} /></Card>}
      <Space style={{ marginTop: 24 }}>
        <Button disabled={step === 0} onClick={() => setStep(step - 1)}>上一步</Button>
        {step > 0 && <Button onClick={next}>跳过</Button>}
        <Button type="primary" onClick={next}>{step === 5 ? '完成演练并进入工作台' : '下一步'}</Button>
      </Space>
    </Card>
  );
}
