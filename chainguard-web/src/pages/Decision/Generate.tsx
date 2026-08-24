import { Access, history, useAccess, useParams } from '@/runtime';
import { PageContainer } from '@/components/pro';
import { Alert, Badge, Button, Card, Collapse, Descriptions, Drawer, Empty, Flex, Form, InputNumber, Radio, Result, Select, Space, Statistic, Table, Tag, Typography, message } from 'antd';
import { AppstoreOutlined, EditOutlined, PlayCircleOutlined, ReloadOutlined, SaveOutlined, SendOutlined, TableOutlined } from '@ant-design/icons';
import { useEffect, useMemo, useState } from 'react';
import { AgentProgress, DecisionTrace, EmptyGuide, RiskTag, SensitiveField, StatusTag } from '@/components';
import { generateProposals, getDecisionReadiness, getDraft, getProposalsForIncident, recalc, saveDraft, submitForApproval, type DecisionReadiness } from '@/services/decision';
import { getIncident } from '@/services/incident';
import { customerLabel, daysLabel, isMissing, moneyLabel, riskLabel, MISSING_TEXT } from '@/utils/proposalMetrics';

// 后端 serialize() 只把列名转驼峰，explanation 里的 JSON 键保持推演产物的原样
// （arbitration_summary / debate_narrative / ...），这里两种写法都认。
const pick = (source: any, ...names: string[]) => {
  for (const name of names) {
    if (source && source[name]) return source[name];
  }
  return undefined;
};

/** 关键因素来自本方案的推演产物：规则仲裁、多智能体博弈、约束求解各出一句。 */
const explanationLines = (proposal: API.Proposal): string[] => {
  const explanation = (proposal as any).explanation || {};
  return [
    pick(explanation, 'arbitration_summary', 'arbitrationSummary'),
    pick(explanation, 'debate_narrative', 'debateNarrative'),
    pick(explanation, 'constraint_narrative', 'constraintNarrative'),
  ].filter(Boolean) as string[];
};

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
  const [traceOpen, setTraceOpen] = useState(false);
  // 决策就绪度：推演前先问后端"这个事件的数据够不够"，避免用户对着缺数据的事件生成方案。
  const [readiness, setReadiness] = useState<DecisionReadiness>();

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
    // 就绪度失败不阻断页面：拿不到就当作未知，不伪造"就绪"
    getDecisionReadiness(incidentId).then(setReadiness).catch(() => setReadiness(undefined));
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

  // 同一口径：缺失指标显示"数据缺失"，不伪装成 0
  const compareRows = useMemo(() => [
    { key: 'cost', metric: '总成本', ...Object.fromEntries(proposals.map((item) => [item.id, item.totalCost])) },
    { key: 'lead', metric: '交期影响', ...Object.fromEntries(proposals.map((item) => [item.id, daysLabel(item.leadTimeImpact)])) },
    { key: 'risk', metric: '剩余风险', ...Object.fromEntries(proposals.map((item) => [item.id, riskLabel(item.residualRisk)])) },
    { key: 'customer', metric: '客户影响', ...Object.fromEntries(proposals.map((item) => [item.id, customerLabel(item.customerImpact, item.highValueCustomers)])) }
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
            <Statistic title="总成本" value={isMissing(proposal.totalCost) ? MISSING_TEXT : proposal.totalCost} formatter={() => isMissing(proposal.totalCost) ? <Typography.Text type="secondary">{MISSING_TEXT}</Typography.Text> : <SensitiveField field="cost" value={moneyLabel(proposal.totalCost)} />} />
            <Statistic title="交期影响" value={daysLabel(proposal.leadTimeImpact)} />
            <Statistic title="客户影响" value={isMissing(proposal.customerImpact) ? MISSING_TEXT : `${proposal.customerImpact} 单`} />
            <div><Typography.Text type="secondary">剩余风险</Typography.Text><div style={{ marginTop: 8 }}>{isMissing(proposal.residualRisk) ? <Typography.Text type="secondary">{MISSING_TEXT}</Typography.Text> : <RiskTag level={proposal.residualRisk} />}</div></div>
          </Flex>
          {proposal.historyExperience?.matched && <Alert style={{ marginTop: 16 }} type="info" showIcon message={`引用历史经验（${proposal.historyExperience.count}）`} description={<Space direction="vertical" size={2}>{proposal.historyExperience.conclusions.slice(0, 2).map((item) => <span key={item}>关键结论：{item}</span>)}<Typography.Text type="secondary">来源：{proposal.historyExperience.sources.join('、')}</Typography.Text></Space>} />}
          {!proposal.historyExperience?.matched && <Typography.Text type="secondary" style={{ display: 'block', marginTop: 16 }}>历史经验：暂无同租户相似经验，本次按当前真实数据独立推演。</Typography.Text>}
          <Collapse ghost style={{ marginTop: 16 }} items={[
            { key: 'views', label: '五视角明细', children: Object.entries(proposal.views).map(([name, value]) => <Descriptions key={name} size="small" column={1} items={[{ key: name, label: name, children: value }]} />) },
            // 证据链必须来自本方案自身的推演产物。此前这里写死了 <Tag>EXP-019</Tag>，
            // 那是演示租户 seed 出来的一张经验卡，对任何租户的任何方案都照样显示——
            // 与「任何数字可复算/可追溯」的承诺直接冲突。
            { key: 'ai', label: 'AI 解释：结论 → 关键因素 → 证据链', children: <Space direction="vertical" size={4} style={{ display: 'flex' }}>
              <Typography.Paragraph style={{ marginBottom: 0 }}>{proposal.reason}</Typography.Paragraph>
              {explanationLines(proposal).map((line) => <Typography.Text key={line} type="secondary">{line}</Typography.Text>)}
              <Space wrap>
                {(pick((proposal as any).explanation, 'dataMissing', 'data_missing') || []).map((item: string) => <Tag key={item} color="orange">降级项：{item}</Tag>)}
                <Tag>{pick((proposal as any).explanation, 'llm_used', 'llmUsed') ? `LLM 生成（${pick((proposal as any).explanation, 'model_name', 'modelName') || '未标注模型'}）` : '规则模板生成，未调用 LLM'}</Tag>
              </Space>
            </Space> }
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
      {readiness && !readiness.ready && (
        <Alert
          style={{ marginTop: 16 }}
          type="error"
          showIcon
          message="决策数据不完整，推演已被阻断"
          description={
            <Space direction="vertical" size={2}>
              {readiness.blocking.map((item) => (
                <span key={item.code}>
                  {item.code}：{item.message}
                </span>
              ))}
              <Typography.Text type="secondary">补齐上述数据后即可生成方案。</Typography.Text>
            </Space>
          }
        />
      )}
      {readiness?.ready && readiness.degraded?.length > 0 && (
        <Alert
          style={{ marginTop: 16 }}
          type="warning"
          showIcon
          message={`数据质量：${readiness.level}，部分字段为估算值`}
          description={
            <Space direction="vertical" size={2}>
              <span>降级项：{readiness.degraded.join('、')}</span>
              <Typography.Text type="secondary">推演结果仍可用，但相关指标的精度受影响，审批时请留意。</Typography.Text>
            </Space>
          }
        />
      )}
      <Card style={{ marginTop: 16 }}>
        {!running && !generated && !readonly && (access.canModifyDecision
          ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未生成应急方案"><Button type="primary" icon={<PlayCircleOutlined />} onClick={start} disabled={readiness ? !readiness.ready : false}>生成方案</Button></Empty>
          : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前角色无生成方案权限，请由供应链负责人生成后在此查看" />)}
        {running && <AgentProgress running onFinish={() => { setRunning(false); setGenerated(true); message.success('已生成 3 个候选方案'); }} />}
        {generated && <Alert type="success" showIcon message="多 Agent 推演完成" description={readonly ? '当前为只读推演，写操作已隐藏。' : '采购、物流、财务、销售、生产约束已汇总，可选择方案并提交审批。'} action={!readonly && access.canModifyDecision && <Button icon={<ReloadOutlined />} onClick={start}>重新生成</Button>} />}
      </Card>
      {generated && !proposals.length && <Card style={{ marginTop: 16 }}><EmptyGuide title="暂无可展示方案" description="当前事件尚未形成可用方案。" actionText={readonly || !access.canModifyDecision ? undefined : '重新生成'} onAction={start} /></Card>}
      {generated && <Button style={{ marginTop: 16 }} onClick={() => setTraceOpen(true)}>查看完整推演</Button>}
      {generated && view === 'card' && <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(340px, 100%), 1fr))', gap: 16, marginTop: 16, paddingInlineEnd: 8 }}>{feasible.map(renderProposal)}</div>
        {!!invalid.length && <Collapse style={{ marginTop: 16 }} items={[{ key: 'invalid', label: `查看不可行方案（${invalid.length}）`, children: <div style={{ maxWidth: 520, paddingInlineEnd: 8 }}>{invalid.map(renderProposal)}</div> }]} />}
      </>}
      {generated && view === 'table' && <Card style={{ marginTop: 16 }}><Table pagination={false} dataSource={compareRows} columns={[{ title: '指标', dataIndex: 'metric', fixed: 'left' }, ...proposals.map((item) => ({ title: item.name, dataIndex: item.id, render: (value: unknown, row: { key: string }) => row.key === 'cost' ? (isMissing(value) ? MISSING_TEXT : <SensitiveField field="cost" value={moneyLabel(value as number)} />) : String(value ?? MISSING_TEXT) }))]} scroll={{ x: 760 }} /></Card>}
      {generated && !readonly && <Card style={{ marginTop: 16, position: 'sticky', bottom: 12, zIndex: 2 }}><Flex justify="space-between" align="center" wrap="wrap" gap={12}><Typography.Text>{selectedProposal ? `已选择：${selectedProposal.name}` : '请选择一项可行方案'}</Typography.Text><Space><Button icon={<SaveOutlined />} onClick={async () => { try { await saveDraft(incidentId, selected); message.success('草稿已保存，再次进入本页自动恢复'); } catch (reason) { message.error(reason instanceof Error ? reason.message : '草稿保存失败'); } }}>保存草稿</Button><Access accessible={canSubmitApproval}><Button type="primary" icon={<SendOutlined />} disabled={!selected} onClick={async () => { try { await submitForApproval(selected!); message.success('已提交审批'); history.push('/decision/approval?tab=pending'); } catch (reason) { message.error(reason instanceof Error ? reason.message : '提交审批失败'); } }}>提交审批</Button></Access></Space></Flex></Card>}
      <Drawer width={440} title={`调整方案：${editing?.name || ''}`} open={!!editing && !readonly} onClose={() => setEditing(undefined)} destroyOnHidden>
        <Form layout="vertical" initialValues={{ supplier: '宁波微电科技', quantity: 6000, transport: 'air', ratio: 60 }} onValuesChange={() => editing && setModified((value) => ({ ...value, [editing.id]: true }))} onFinish={async (values) => { if (!editing) return; const updated = await recalc(editing.id, values) as Partial<API.Proposal>; setProposals((items) => items.map((item) => item.id === editing.id ? { ...item, ...updated, modified: true } : item)); setModified((value) => ({ ...value, [editing.id]: false })); setEditing(undefined); message.success('重算完成，指标与修改痕迹已更新'); }}>
          <Form.Item name="supplier" label="替代供应商"><Select options={[{ label: '宁波微电科技', value: '宁波微电科技' }, { label: '无锡华芯', value: '无锡华芯' }]} /></Form.Item>
          <Form.Item name="quantity" label="采购量"><InputNumber min={1} style={{ width: '100%' }} addonAfter="件" /></Form.Item>
          <Form.Item name="transport" label="运输方式"><Select options={[{ label: '空运', value: 'air' }, { label: '公路加急', value: 'road' }, { label: '铁路', value: 'rail' }]} /></Form.Item>
          <Form.Item name="ratio" label="首批比例"><InputNumber min={10} max={100} style={{ width: '100%' }} addonAfter="%" /></Form.Item>
          <Button block type="primary" htmlType="submit" icon={<ReloadOutlined />}>重算方案</Button>
        </Form>
      </Drawer>
      <DecisionTrace incidentId={incidentId} open={traceOpen} onClose={() => setTraceOpen(false)} />
    </PageContainer>
  );
}
