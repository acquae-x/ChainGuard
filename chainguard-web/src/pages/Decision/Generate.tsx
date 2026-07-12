import { Access, history, useAccess, useParams } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { Alert, Badge, Button, Card, Collapse, Descriptions, Drawer, Empty, Flex, Form, InputNumber, Radio, Result, Select, Space, Statistic, Table, Tag, Typography, message } from 'antd';
import { AppstoreOutlined, EditOutlined, PlayCircleOutlined, ReloadOutlined, SaveOutlined, SendOutlined, TableOutlined } from '@ant-design/icons';
import { useEffect, useMemo, useState } from 'react';
import { AgentProgress, EmptyGuide, RiskTag, SensitiveField, StatusTag } from '@/components';
import { generateProposals, getDraft, getProposalsForIncident, recalc, saveDraft, submitForApproval } from '@/services/decision';
import { getIncident } from '@/services/incident';

export default function DecisionGenerate() {
  const { incidentId = 'inc-supplier-shutdown' } = useParams<{ incidentId: string }>();
  const access = useAccess();
  // 02 文档审批矩阵：方案由供应链负责人提交（approval:submit_high）；boss 直接在审批中心批准，不做提交人
  const canSubmitApproval = access.canSubmitHigh;
  const readonly = access.readonly || new URLSearchParams(location.search).get('readonly') === '1';
  const [running, setRunning] = useState(false);
  const [generated, setGenerated] = useState(false);
  const [view, setView] = useState<'card' | 'table'>('card');
  const [selected, setSelected] = useState<string>();
  const [editing, setEditing] = useState<API.Proposal>();
  const [modified, setModified] = useState<Record<string, boolean>>({});
  const [proposals, setProposals] = useState<API.Proposal[]>([]);
  const [incident, setIncident] = useState<API.Incident>();
  const [error, setError] = useState<string>();

  const loadExisting = async () => {
    setError(undefined);
    try {
      const items = await getProposalsForIncident(incidentId);
      setProposals(items);
      setGenerated(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '方案加载失败');
    }
  };

  useEffect(() => {
    getIncident(incidentId).then(setIncident).catch((reason) => setError(reason instanceof Error ? reason.message : '事件加载失败'));
    if (readonly) loadExisting();
    // 恢复上次保存的草稿选择（mock 服务端保存，非 localStorage）
    getDraft(incidentId).then((draft) => { if (draft?.proposalId) setSelected(draft.proposalId); });
  }, [incidentId, readonly]);

  const start = async () => {
    setRunning(true);
    setGenerated(false);
    setError(undefined);
    try {
      setProposals(await generateProposals(incidentId));
    } catch (reason) {
      setRunning(false);
      setError(reason instanceof Error ? reason.message : '方案生成失败');
    }
  };

  const compareRows = useMemo(() => [
    { key: 'cost', metric: '总成本', ...Object.fromEntries(proposals.map((item) => [item.id, item.totalCost])) },
    { key: 'lead', metric: '交期影响', ...Object.fromEntries(proposals.map((item) => [item.id, `${item.leadTimeImpact} 天`])) },
    { key: 'risk', metric: '剩余风险', ...Object.fromEntries(proposals.map((item) => [item.id, item.residualRisk === 'low' ? '低' : item.residualRisk === 'medium' ? '中' : '高'])) },
    { key: 'customer', metric: '客户影响', ...Object.fromEntries(proposals.map((item) => [item.id, `${item.customerImpact} 单 / 高等级 ${item.highValueCustomers}`])) }
  ], [proposals]);

  const renderProposal = (proposal: API.Proposal) => {
    const invalid = proposal.tag === 'invalid';
    const active = selected === proposal.id;
    return (
      <Badge.Ribbon key={proposal.id} text={proposal.tag === 'recommended' ? '推荐' : invalid ? '不可行' : '备选'} color={proposal.tag === 'recommended' ? 'gold' : invalid ? 'red' : 'default'}>
        <Card
          hoverable={!invalid}
          onClick={() => !invalid && setSelected(proposal.id)}
          style={{ borderColor: active ? '#1B4F9C' : undefined, opacity: invalid ? 0.62 : 1, height: '100%' }}
          title={<Space><Radio checked={active} disabled={invalid} />{proposal.name}{modified[proposal.id] && <Tag color="orange">已修改，待重算</Tag>}</Space>}
          extra={<Access accessible={access.canModifyDecision && !readonly && !invalid}><Button type="text" icon={<EditOutlined />} onClick={(event) => { event.stopPropagation(); setEditing(proposal); }}>调整</Button></Access>}
        >
          <Flex gap={20} wrap="wrap">
            <Statistic title="总成本" value={proposal.totalCost} formatter={() => <SensitiveField field="cost" value={`¥${proposal.totalCost.toLocaleString()}`} />} />
            <Statistic title="交期影响" value={proposal.leadTimeImpact} suffix="天" />
            <Statistic title="客户影响" value={proposal.customerImpact} suffix="单" />
            <div><Typography.Text type="secondary">剩余风险</Typography.Text><div style={{ marginTop: 8 }}><RiskTag level={proposal.residualRisk} /></div></div>
          </Flex>
          <Collapse ghost style={{ marginTop: 16 }} items={[
            { key: 'views', label: '五视角明细', children: Object.entries(proposal.views).map(([name, value]) => <Descriptions key={name} size="small" column={1} items={[{ key: name, label: name, children: value }]} />) },
            { key: 'ai', label: 'AI 解释与证据', children: <><Typography.Paragraph>{proposal.reason}</Typography.Paragraph><Space><Tag>EXP-019</Tag><Tag>高等级客户交付约束</Tag></Space></> }
          ]} />
          {invalid && <Alert type="error" showIcon message="违反硬约束" description={proposal.reason} />}
        </Card>
      </Badge.Ribbon>
    );
  };

  const feasible = proposals.filter((item) => item.tag !== 'invalid');
  const invalid = proposals.filter((item) => item.tag === 'invalid');
  const selectedProposal = proposals.find((item) => item.id === selected);

  if (error) return <PageContainer title="方案生成与对比" subTitle={incident?.code || incidentId}><Result status="500" title="方案服务暂时不可用" subTitle={error} extra={<Button type="primary" onClick={readonly ? loadExisting : start}>重试</Button>} /></PageContainer>;

  return (
    <PageContainer title="方案生成与对比" subTitle={incident?.code || incidentId} extra={<Radio.Group value={view} onChange={(event) => setView(event.target.value)} optionType="button" options={[{ label: <><AppstoreOutlined /> 卡片</>, value: 'card' }, { label: <><TableOutlined /> 对比表</>, value: 'table' }]} />}>
      <Collapse items={[{ key: 'summary', label: incident?.title || '加载事件摘要...', children: incident && <Descriptions column={{ xs: 1, md: 4 }} items={[{ key: 'risk', label: '风险等级', children: <RiskTag level={incident.level} /> }, { key: 'owner', label: '负责人', children: incident.owner }, { key: 'loss', label: '预计损失', children: <SensitiveField field="cost" value={`¥${incident.loss.toLocaleString()}`} /> }, { key: 'status', label: '状态', children: <StatusTag status={incident.status} /> }]} /> }]} />
      <Card style={{ marginTop: 16 }}>
        {!running && !generated && !readonly && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未生成应急方案"><Button type="primary" icon={<PlayCircleOutlined />} onClick={start}>生成方案</Button></Empty>}
        {running && <AgentProgress running onFinish={() => { setRunning(false); setGenerated(true); message.success('已生成 3 个候选方案'); }} />}
        {generated && <Alert type="success" showIcon message="多 Agent 推演完成" description={readonly ? '当前为只读推演，写操作已隐藏。' : '采购、物流、财务、销售、生产约束已汇总，可选择方案并提交审批。'} action={!readonly && <Button icon={<ReloadOutlined />} onClick={start}>重新生成</Button>} />}
      </Card>
      {generated && !proposals.length && <Card style={{ marginTop: 16 }}><EmptyGuide title="暂无可展示方案" description="当前事件尚未形成可用方案。" actionText={readonly ? undefined : '重新生成'} onAction={start} /></Card>}
      {generated && view === 'card' && <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16, marginTop: 16 }}>{feasible.map(renderProposal)}</div>
        {!!invalid.length && <Collapse style={{ marginTop: 16 }} items={[{ key: 'invalid', label: `查看不可行方案（${invalid.length}）`, children: <div style={{ maxWidth: 520 }}>{invalid.map(renderProposal)}</div> }]} />}
      </>}
      {generated && view === 'table' && <Card style={{ marginTop: 16 }}><Table pagination={false} dataSource={compareRows} columns={[{ title: '指标', dataIndex: 'metric', fixed: 'left' }, ...proposals.map((item) => ({ title: item.name, dataIndex: item.id, render: (value: unknown, row: { key: string }) => row.key === 'cost' ? <SensitiveField field="cost" value={`¥${Number(value).toLocaleString()}`} /> : String(value ?? '') }))]} scroll={{ x: 760 }} /></Card>}
      {generated && !readonly && <Card style={{ marginTop: 16, position: 'sticky', bottom: 12, zIndex: 2 }}><Flex justify="space-between" align="center" wrap="wrap" gap={12}><Typography.Text>{selectedProposal ? `已选择：${selectedProposal.name}` : '请选择一项可行方案'}</Typography.Text><Space><Button icon={<SaveOutlined />} onClick={async () => { await saveDraft(incidentId, selected); message.success('草稿已保存，再次进入本页自动恢复'); }}>保存草稿</Button><Access accessible={canSubmitApproval}><Button type="primary" icon={<SendOutlined />} disabled={!selected} onClick={async () => { await submitForApproval(selected!); message.success('已提交审批'); history.push('/decision/approval?tab=pending'); }}>提交审批</Button></Access></Space></Flex></Card>}
      <Drawer width={440} title={`调整方案：${editing?.name || ''}`} open={!!editing && !readonly} onClose={() => setEditing(undefined)} destroyOnClose>
        <Form layout="vertical" initialValues={{ supplier: '宁波微电科技', quantity: 6000, transport: 'air', ratio: 60 }} onValuesChange={() => editing && setModified((value) => ({ ...value, [editing.id]: true }))} onFinish={async (values) => { if (!editing) return; const updated = await recalc(editing.id, values) as Partial<API.Proposal>; setProposals((items) => items.map((item) => item.id === editing.id ? { ...item, ...updated, modified: true } : item)); setModified((value) => ({ ...value, [editing.id]: false })); setEditing(undefined); message.success('重算完成，指标与修改痕迹已更新'); }}>
          <Form.Item name="supplier" label="替代供应商"><Select options={[{ label: '宁波微电科技', value: '宁波微电科技' }, { label: '无锡华芯', value: '无锡华芯' }]} /></Form.Item>
          <Form.Item name="quantity" label="采购量"><InputNumber min={1} style={{ width: '100%' }} addonAfter="件" /></Form.Item>
          <Form.Item name="transport" label="运输方式"><Select options={[{ label: '空运', value: 'air' }, { label: '公路加急', value: 'road' }, { label: '铁路', value: 'rail' }]} /></Form.Item>
          <Form.Item name="ratio" label="首批比例"><InputNumber min={10} max={100} style={{ width: '100%' }} addonAfter="%" /></Form.Item>
          <Button block type="primary" htmlType="submit" icon={<ReloadOutlined />}>重算方案</Button>
        </Form>
      </Drawer>
    </PageContainer>
  );
}
