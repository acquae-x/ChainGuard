import { history, useAccess, useParams } from '@umijs/max';
import { Button, Card, Col, Descriptions, Empty, Form, Input, List, Modal, Result, Row, Select, Space, Steps, Table, Tabs, Timeline, Typography, Upload, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { ImpactScopePanel, RiskExplanationDrawer, RiskTag, SensitiveField, StatusTag } from '@/components';
import { addIncidentNote, closeIncident, getImpact, getIncident, getTimeline, updateIncident } from '@/services/incident';
import { getTasks } from '@/services/task';
import { getProposalsForIncident } from '@/services/decision';

const stepIndex: Record<string, number> = { new: 0, evaluating: 1, planning: 2, approving: 3, executing: 4, reviewing: 5, closed: 5 };

export default function IncidentDetailPage() {
  const { id = 'inc-supplier-shutdown' } = useParams();
  const access = useAccess();
  const [incident, setIncident] = useState<API.Incident>();
  const [loaded, setLoaded] = useState(false);
  const [impact, setImpact] = useState<any>();
  const [impactError, setImpactError] = useState<string>();
  const [timeline, setTimeline] = useState<API.AuditLog[]>([]);
  const [tasks, setTasks] = useState<API.Task[]>([]);
  const [proposals, setProposals] = useState<API.Proposal[]>([]);
  const [tab, setTab] = useState(new URLSearchParams(location.search).get('tab') || 'impact');
  const [explainRiskId, setExplainRiskId] = useState<string>();
  const [levelOpen, setLevelOpen] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [form] = Form.useForm();

  // 事件详情由多个互相独立的端点拼成，各端点的权限门禁并不相同（任务需 task:*，
  // 方案需 decision:view）。任一侧栏数据 403 都不得中断整页初始化——尤其不能让
  // 「没有任务权限」把影响范围面板一起拖成白屏。故每路请求单独降级：拿不到就用空值渲染。
  const settle = <T,>(promise: Promise<T>, fallback: T) => promise.catch(() => fallback);

  const reload = async () => {
    const [nextIncident, nextImpact, nextTimeline, nextTasks, nextProposals] = await Promise.all([
      settle<API.Incident | undefined>(getIncident(id), undefined),
      // 影响范围取不到时不能退化成空对象——那会渲染成「共波及 0 个业务对象」，
      // 把「没查到」说成「查过了，是 0」。走 error 分支如实说加载失败。
      getImpact(id).then((value) => { setImpactError(undefined); return value; }).catch((err: any) => { setImpactError(err?.message || '影响范围加载失败'); return undefined; }),
      settle<API.AuditLog[]>(getTimeline(id), []),
      // 无任务读取权限时根本不发请求，避免必然 403 的调用连带弹出全局错误提示
      access.canTask ? settle<{ data: API.Task[] }>(getTasks(), { data: [] }) : Promise.resolve({ data: [] as API.Task[] }),
      settle<API.Proposal[]>(getProposalsForIncident(id), []),
    ]);
    setIncident(nextIncident);
    setImpact(nextImpact);
    setTimeline(nextTimeline || []);
    setTasks((nextTasks?.data || []).filter((task) => task.source === nextIncident?.code));
    setProposals(nextProposals || []);
    setLoaded(true);
  };

  useEffect(() => { reload(); }, [id]);
  const timelineItems = useMemo(() => timeline.map((item) => ({ children: `${item.time} ${item.action}：${item.targetName}${item.detail.note ? `（${item.detail.note}）` : ''}` })), [timeline]);
  if (!loaded) return <Card loading />;
  if (!incident) return <Result status="404" title="事件不存在" subTitle="该事件可能已失效或演示数据已重置。" extra={<Button type="primary" onClick={() => history.push('/incident/list')}>返回事件列表</Button>} />;

  // A04：影响范围整体由后端沿 C2 实体真实外键算出。此处**不再**有任何本地推算或写死的
  // 字面量——旧版的「客户等级 A」「预计延误 2 天」「替代供应商数 1」都是编造的影响结论。
  const impactContent = <ImpactScopePanel data={impact} error={impactError} testIdPrefix="incident-impact-scope" />;

  // 任务页签跟随 task:* 权限：无权限的角色不展示空表格，也不会去请求 /tasks。
  const tabItems = [
    { key: 'impact', label: '影响范围', children: impactContent },
    // Timeline 在 items 为空时什么都不画，页签看起来像加载失败；给一个明确空态。
    { key: 'timeline', label: '时间线', children: timelineItems.length ? <Timeline items={timelineItems} /> : <Empty description="暂无时间线记录：该事件尚未产生可留痕的操作" /> },
    { key: 'proposal', label: '关联方案', children: <List dataSource={proposals} locale={{ emptyText: '尚未生成方案' }} renderItem={(item: API.Proposal) => <List.Item><Space><Typography.Text>{item.name}</Typography.Text><StatusTag status={item.tag === 'invalid' ? 'rejected' : item.tag === 'recommended' ? 'approved' : 'pending'} /></Space></List.Item>} /> },
    ...(access.canTask ? [{ key: 'task', label: '任务', children: <Table rowKey="id" dataSource={tasks} pagination={false} locale={{ emptyText: '审批通过后自动拆解任务' }} columns={[{ title: '任务', dataIndex: 'title' }, { title: '负责人', dataIndex: 'assignee' }, { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag status={value} /> }]} /> }] : []),
    { key: 'audit', label: '操作记录', children: timeline.length ? <Timeline items={timeline.map((item) => ({ children: `${item.action}：${JSON.stringify(item.detail)}` }))} /> : <Empty description="暂无操作记录" /> },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <RiskExplanationDrawer riskId={explainRiskId} open={!!explainRiskId} onClose={() => setExplainRiskId(undefined)} />
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
          <Space direction="vertical">
            <Typography.Title level={3}>{incident.code} {incident.title}</Typography.Title>
            <Space wrap>
              <RiskTag level={incident.level} /><StatusTag status={incident.status} />
              <span>责任人：{incident.owner}</span><span>创建时间：{incident.createdAt}</span>
              {/* A03：来源风险每条都能直接看解释，复用同一抽屉。 */}
              <span>来源风险：</span>
              {incident.sourceRiskIds.map((riskId) => (
                <Button key={riskId} type="link" size="small" style={{ padding: '0 4px' }} onClick={() => setExplainRiskId(riskId)}>{riskId}</Button>
              ))}
            </Space>
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
            <Tabs activeKey={tabItems.some((item) => item.key === tab) ? tab : 'impact'} onChange={(key) => { setTab(key); history.replace(`${history.location.pathname}?tab=${key}`); }} items={tabItems} />
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
