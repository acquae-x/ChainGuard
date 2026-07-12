import { PageContainer } from '@ant-design/pro-components';
import { Alert, Button, Card, Col, Form, Row, Select, Space, Steps, Switch, message } from 'antd';

export default function ApprovalSettings() {
  return <PageContainer title="审批流配置"><Alert type="info" showIcon message="高风险必须老板审批，涉及成本阈值时自动加入财务会签。" style={{ marginBottom: 16 }} /><Row gutter={16}><Col xs={24} lg={14}><Card title="风险分级审批链"><Steps direction="vertical" items={[{ title: '低风险', description: '供应链负责人直接批准' }, { title: '中风险', description: '供应链负责人审批，老板可抄送' }, { title: '高风险', description: '老板审批 + 财务并行会签' }]} /></Card></Col><Col xs={24} lg={10}><Card title="规则设置"><Form layout="vertical" onFinish={() => message.success('审批流已保存')}><Form.Item label="高风险主审批人" name="owner" initialValue="boss"><Select options={[{ label: '老板/总经理', value: 'boss' }, { label: '供应链负责人', value: 'scm_lead' }]} /></Form.Item><Form.Item label="启用财务会签" name="finance" valuePropName="checked" initialValue><Switch /></Form.Item><Space><Button type="primary" htmlType="submit">保存</Button><Button>恢复默认</Button></Space></Form></Card></Col></Row></PageContainer>;
}
