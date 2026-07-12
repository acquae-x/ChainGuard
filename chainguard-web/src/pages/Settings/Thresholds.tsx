import { PageContainer } from '@ant-design/pro-components';
import { Button, Card, Form, InputNumber, Table, message } from 'antd';

export default function Thresholds() {
  const data = [{ key: 'high', level: '高风险', score: '≥ 80', action: '立即创建事件并通知老板' }, { key: 'medium', level: '中风险', score: '60-79', action: '进入关注队列' }, { key: 'low', level: '低风险', score: '< 60', action: '持续监控' }];
  return <PageContainer title="风险阈值"><Card><Table pagination={false} dataSource={data} columns={[{ title: '等级', dataIndex: 'level' }, { title: '分值区间', dataIndex: 'score' }, { title: '系统动作', dataIndex: 'action' }]} /><Form layout="inline" style={{ marginTop: 24 }} onFinish={() => message.success('阈值已保存并记录审计')}><Form.Item name="high" label="高风险起始分" initialValue={80}><InputNumber min={1} max={100} /></Form.Item><Form.Item name="medium" label="中风险起始分" initialValue={60}><InputNumber min={1} max={100} /></Form.Item><Button type="primary" htmlType="submit">保存阈值</Button></Form></Card></PageContainer>;
}
