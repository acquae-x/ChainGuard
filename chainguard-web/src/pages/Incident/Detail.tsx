import { history, useAccess, useParams } from '@umijs/max';
import { Button, Card, Col, Descriptions, Form, Input, List, Modal, Result, Row, Select, Space, Steps, Table, Tabs, Timeline, Typography, Upload, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { RiskTag, SensitiveField, StatusTag } from '@/components';
import { addIncidentNote, closeIncident, getImpact, getIncident, getTimeline, updateIncident } from '@/services/incident';
import { getTasks } from '@/services/task';
import { getProposalsForIncident } from '@/services/decision';

const stepIndex: Record<string, number> = { new: 0, evaluating: 1, planning: 2, approving: 3, executing: 4, reviewing: 5, closed: 5 };

export default function IncidentDetailPage() {
  const { id = 'inc-supplier-shutdown' } = useParams();
  const access = useAccess();
  const [incident, setIncident] = useState<API.Incident>();
  const [loaded, setLoaded] = useState(false);
  const [impact, setImpact] = useState<any>({});
  const [timeline, setTimeline] = useState<API.AuditLog[]>([]);
  const [tasks, setTasks] = useState<API.Task[]>([]);
  const [proposals, setProposals] = useState<API.Proposal[]>([]);
  const [tab, setTab] = useState(new URLSearchParams(location.search).get('tab') || 'impact');
  const [levelOpen, setLevelOpen] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [form] = Form.useForm();

  const reload = async () => {
    const [nextIncident, nextImpact, nextTimeline, nextTasks, nextProposals] = await Promise.all([getIncident(id), getImpact(id), getTimeline(id), getTasks(), getProposalsForIncident(id)]);
    setIncident(nextIncident);
    setImpact(nextImpact);
    setTimeline(nextTimeline);
    setTasks(nextTasks.data.filter((task) => task.source === nextIncident?.code));
    setProposals(nextProposals);
    setLoaded(true);
  };

  useEffect(() => { reload(); }, [id]);
  const timelineItems = useMemo(() => timeline.map((item) => ({ children: `${item.time} ${item.action}：${item.targetName}${item.detail.note ? `（${item.detail.note}）` : ''}` })), [timeline]);
  if (!loaded) return <Card loading />;
  if (!incident) return <Result status="404" title="事件不存在" subTitle="该事件可能已失效或演示数据已重置。" extra={<Button type="primary" onClick={() => history.push('/incident/list')}>返回事件列表</Button>} />;

  const impactContent = (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <section><Typography.Title level={5}>受影响物料</Typography.Title><Table size="small" rowKey="id" pagination={false} dataSource={impact.materials || []} columns={[{ title: '物料', dataIndex: 'name' }, { title: '当前库存', dataIndex: 'stock' }, { title: '安全库存', dataIndex: 'safety' }, { title: '缺口量', dataIndex: 'shortage' }, { title: '单位成本', render: (_, row: any) => <SensitiveField field="cost" value={`¥${row.cost}`} /> }]} /></section>
      <section><Typography.Title level={5}>受影响订单</Typography.Title><Table size="small" rowKey="id" pagination={false} dataSource={impact.orders || []} columns={[{ title: '订单号', dataIndex: 'orderNo' }, { title: '客户', dataIndex: 'customer' }, { title: '客户等级', render: () => <SensitiveField field="customerLevel" value="A" /> }, { title: '承诺交期', dataIndex: 'dueAt' }, { title: '预计延误', render: () => '2 天' }, { title: '利润', render: (_, row: any) => <SensitiveField field="profit" value={`¥${row.profit}`} /> }]} /></section>
      <section><Typography.Title level={5}>受影响库存</Typography.Title><Table size="small" rowKey="id" pagination={false} dataSource={impact.inventory || []} columns={[{ title: '仓库', dataIndex: 'warehouse' }, { title: '物料', dataIndex: 'material' }, { title: '当前量', dataIndex: 'quantity' }, { title: '可支撑小时', dataIndex: 'supportHours' }]} /></section>
      <section><Typography.Title level={5}>涉及供应商</Typography.Title><List grid={{ gutter: 12, xs: 1, md: 2 }} dataSource={impact.suppliers || []} renderItem={(supplier: any) => <List.Item><Card size="small" title={supplier.name}><Space direction="vertical"><StatusTag status={supplier.status === '停产' ? 'new' : 'watching'} /><Typography.Text>替代供应商数：{supplier.status === '停产' ? 1 : 0}</Typography.Text><Typography.Text>交期：{supplier.leadTime} 天</Typography.Text><Typography.Text>报价：<SensitiveField field="supplierPrice" value={`¥${supplier.supplierPrice}`} /></Typography.Text></Space></Card></List.Item>} /></section>
    </Space>
  );

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
          <Space direction="vertical">
            <Typography.Title level={3}>{incident.code} {incident.title}</Typography.Title>
            <Space wrap><RiskTag level={incident.level} /><StatusTag status={incident.status} /><span>责任人：{incident.owner}</span><span>创建时间：{incident.createdAt}</span><span>来源风险：{incident.sourceRiskIds.join('、')}</span></Space>
          </Space>
          <Space>
            {access.canManageIncident && <Button type="primary" onClick={() => history.push(`/decision/generate/${incident.id}`)}>生成决策方案</Button>}
            {access.canManageIncident && <><Button onClick={() => setLevelOpen(true)}>升级/降级等级</Button><Button onClick={() => setNoteOpen(true)}>添加备注</Button><Button onClick={async () => { await closeIncident(incident.id); message.success('事件已进入复盘'); await reload(); }}>关闭事件</Button></>}
          </Space>
        </Space>
        <Steps current={stepIndex[incident.status] ?? 0} items={['发现', '评估', '方案', '审批', '执行', '复盘'].map((title) => ({ title }))} style={{ marginTop: 24 }} />
      </Card>
      <Row gutter={16}>
        <Col xs={24} xl={17}>
          <Card>
            <Tabs activeKey={tab} onChange={(key) => { setTab(key); history.replace(`${history.location.pathname}?tab=${key}`); }} items={[
              { key: 'impact', label: '影响范围', children: impactContent },
              { key: 'timeline', label: '时间线', children: <Timeline items={timelineItems} /> },
              { key: 'proposal', label: '关联方案', children: <List dataSource={proposals} locale={{ emptyText: '尚未生成方案' }} renderItem={(item) => <List.Item><Space><Typography.Text>{item.name}</Typography.Text><StatusTag status={item.tag === 'invalid' ? 'rejected' : item.tag === 'recommended' ? 'approved' : 'pending'} /></Space></List.Item>} /> },
              { key: 'task', label: '任务', children: <Table rowKey="id" dataSource={tasks} pagination={false} locale={{ emptyText: '审批通过后自动拆解任务' }} columns={[{ title: '任务', dataIndex: 'title' }, { title: '负责人', dataIndex: 'assignee' }, { title: '状态', dataIndex: 'status', render: (value) => <StatusTag status={value} /> }]} /> },
              { key: 'audit', label: '操作记录', children: <Timeline items={timeline.map((item) => ({ children: `${item.action}：${JSON.stringify(item.detail)}` }))} /> }
            ]} />
          </Card>
        </Col>
        <Col xs={24} xl={7}>
          <Card title="当前状态摘要"><Descriptions column={1} size="small"><Descriptions.Item label="预计损失"><SensitiveField field="cost" value={`¥${incident.loss.toLocaleString()}`} /></Descriptions.Item><Descriptions.Item label="应急成本"><SensitiveField field="cost" value={`¥${incident.cost.toLocaleString()}`} /></Descriptions.Item><Descriptions.Item label="参与人">采购、财务、销售、生产</Descriptions.Item></Descriptions></Card>
          {access.canManageIncident && <Card title="附件区" style={{ marginTop: 16 }}><Upload><Button>上传附件</Button></Upload></Card>}
        </Col>
      </Row>
      <Modal title="升级/降级风险等级" open={levelOpen} onCancel={() => setLevelOpen(false)} onOk={() => form.submit()}><Form form={form} layout="vertical" initialValues={{ level: incident.level }} onFinish={async (values) => { await updateIncident(incident.id, { level: values.level }); setLevelOpen(false); message.success('事件等级已更新'); await reload(); }}><Form.Item name="level" label="风险等级" rules={[{ required: true }]}><Select options={[{ value: 'high', label: '高风险' }, { value: 'medium', label: '中风险' }, { value: 'low', label: '低风险' }]} /></Form.Item></Form></Modal>
      <Modal title="添加事件备注" open={noteOpen} onCancel={() => setNoteOpen(false)} onOk={async () => { const values = await form.validateFields(['note']); await addIncidentNote(incident.id, values.note); setNoteOpen(false); form.resetFields(['note']); message.success('备注已写入时间线'); await reload(); }}><Form form={form} layout="vertical"><Form.Item name="note" label="备注" rules={[{ required: true, message: '请填写备注' }]}><Input.TextArea rows={4} /></Form.Item></Form></Modal>
    </Space>
  );
}
