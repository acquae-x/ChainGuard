import { PageContainer } from '@ant-design/pro-components';
import { Alert, App, Button, Card, Col, Descriptions, Input, Popconfirm, Row, Space, Switch, Table, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { confirmCalibrationGovernance, getCalibrationGovernance, getRiskRules, updateRiskRule, type RiskRule } from '@/services/settings';

const labels: Record<string, string> = { shortage_urgency: '缺货紧急度', order_importance: '订单重要性', transit_delay: '在途延误', external_event: '外部事件' };
const thresholdLabels: Record<string, string> = { yellow_support_hours: '黄色预警支撑时长（小时）', red_support_hours: '红色预警支撑时长（小时）', inventory_risk_trigger: '库存风险触发分' };
// drift_monitor 的 recommended_action 枚举，原样透出会在整页中文里蹦出一个 none。
const RECOMMENDED_ACTION_LABELS: Record<string, string> = { none: '无需操作', recalibrate: '建议重新校准', review_rollback: '建议复核并考虑回滚' };

function compareRows(snapshot: any) {
  const expert = snapshot?.comparison?.expert || {};
  const suggested = snapshot?.comparison?.suggested || {};
  const expertWarning = expert.thresholds?.inventory_warning || {};
  const suggestedWarning = suggested.thresholds?.inventory_warning || {};
  return [
    ...Object.keys(thresholdLabels).map((key) => ({ key: `t-${key}`, type: '阈值', name: thresholdLabels[key], expert: expertWarning[key], suggested: suggestedWarning[key], unit: key.includes('hours') ? '小时' : '分' })),
    ...Object.keys(labels).map((key) => ({ key: `w-${key}`, type: '权重', name: labels[key], expert: expert.riskWeights?.[key], suggested: suggested.riskWeights?.[key], unit: '' })),
  ];
}

export default function Thresholds() {
  const { message } = App.useApp();
  const [snapshot, setSnapshot] = useState<any>();
  const [loading, setLoading] = useState(true);
  const load = async () => { setLoading(true); try { setSnapshot(await getCalibrationGovernance()); } catch { /* request layer already reports API error */ } finally { setLoading(false); } };
  useEffect(() => { load(); }, []);
  const confirm = async () => {
    await confirmCalibrationGovernance(snapshot.recommendationId);
    message.success('校准建议已确认，后续真实租户决策将读取新的已批准配置');
    await load();
  };
  // 风险规则（GET/PUT /risk-rules）此前没有任何界面入口，规则只能改库。
  const [rules, setRules] = useState<RiskRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(true);
  const loadRules = async () => {
    setRulesLoading(true);
    try { setRules((await getRiskRules()).data || []); } catch { /* request layer already reports API error */ } finally { setRulesLoading(false); }
  };
  useEffect(() => { loadRules(); }, []);
  const saveRule = async (rule: RiskRule, patch: Partial<RiskRule>) => {
    setRules((items) => items.map((item) => (item.id === rule.id ? { ...item, ...patch } : item)));
    try {
      await updateRiskRule(rule.id, { ...rule, ...patch });
      message.success('风险规则已保存');
    } catch (error: any) {
      message.error(error?.message || '风险规则保存失败');
      await loadRules();
    }
  };

  const drift = snapshot?.drift;
  const effectiveRows = snapshot?.sample?.effectiveRows || 0;
  const range = snapshot?.sample?.timeRange || {};
  return <PageContainer title="风险阈值" subTitle="校准治理面板">
    <Alert showIcon type="info" style={{ marginBottom: 16 }} message="数据驱动建议不会自动生效" description={snapshot?.calculation?.approvalGate || '加载校准治理数据中。'} />
    {drift?.driftDetected && <Alert showIcon type={drift.severity === 'critical' ? 'error' : 'warning'} style={{ marginBottom: 16 }} message={`漂移${drift.severity === 'critical' ? '严重超限' : '超限'}`} description={`成功率较基线下降 ${(Number(drift.successRateDrop || 0) * 100).toFixed(1)}%；已通过站内通知提醒管理员。`} />}
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={16}><Card title="数据驱动建议 vs 专家默认值" loading={loading} extra={<Space><Tag color={snapshot?.comparison?.active?.approved ? 'green' : 'gold'}>{snapshot?.comparison?.active?.approved ? '当前已有已批准配置' : '尚未确认，不影响决策'}</Tag>{effectiveRows >= 5 && <Popconfirm title="确认应用本次校准建议？" description="确认后将写入新的租户阈值和权重版本；未确认建议不会影响决策。" okText="确认应用" cancelText="取消" onConfirm={confirm}><Button type="primary">人工确认并应用</Button></Popconfirm>}</Space>}>
        <Table size="small" pagination={false} dataSource={compareRows(snapshot)} columns={[{ title: '类型', dataIndex: 'type', width: 76 }, { title: '参数', dataIndex: 'name' }, { title: '专家默认值', dataIndex: 'expert', render: (value, row) => `${value ?? '-'}${row.unit}` }, { title: '数据驱动建议', dataIndex: 'suggested', render: (value, row) => <Typography.Text strong={value !== row.expert}>{value ?? '-'}{row.unit}</Typography.Text> }]} />
      </Card></Col>
      <Col xs={24} xl={8}><Card title="样本与计算说明" loading={loading}><Descriptions size="small" column={1} items={[{ key: 'sample', label: '有效样本', children: `${effectiveRows} / ${snapshot?.sample?.totalRows || 0} 条` }, { key: 'confidence', label: '置信度', children: <Space><Tag color={effectiveRows >= 20 ? 'green' : 'orange'}>{snapshot?.sample?.confidence?.score || 0}%</Tag>{snapshot?.sample?.confidence?.note}</Space> }, { key: 'range', label: '数据时间范围', children: range.from && range.to ? `${range.from} ～ ${range.to}` : '未提供业务时间，使用导入留痕时间' }, { key: 'weights', label: '权重计算', children: snapshot?.calculation?.weightNote || '-' }, { key: 'trigger', label: '触发阈值计算', children: snapshot?.calculation?.trigger?._note || '-' }]} /></Card></Col>
      <Col span={24}><Card title="风险规则" loading={rulesLoading} extra={<Button onClick={loadRules}>刷新</Button>}>
        <Table size="small" rowKey="id" pagination={false} dataSource={rules} locale={{ emptyText: '暂无风险规则' }} columns={[
          { title: '规则名称', dataIndex: 'name' },
          { title: '阈值', dataIndex: 'threshold', render: (_, row) => <Input defaultValue={row.threshold} style={{ maxWidth: 160 }} onBlur={(event) => { const value = event.target.value; if (value !== row.threshold) saveRule(row, { threshold: value }); }} /> },
          { title: '启用', dataIndex: 'enabled', render: (_, row) => <Switch checked={row.enabled} onChange={(checked) => saveRule(row, { enabled: checked })} /> },
        ]} />
      </Card></Col>
      <Col span={24}><Card title="漂移体检" loading={loading}><Descriptions size="small" column={{ xs: 1, md: 3 }} items={[{ key: 'status', label: '体检结果', children: <Tag color={drift?.driftDetected ? 'red' : 'green'}>{drift?.driftDetected ? '超限' : '正常'}</Tag> }, { key: 'rate', label: '当前成功率', children: `${(Number(drift?.successRate || 0) * 100).toFixed(1)}%` }, { key: 'reason', label: '超限原因', children: drift?.findings?.join('；') || '-' }, { key: 'notify', label: '本次 D3 通知', children: `${drift?.notificationCount || 0} 位管理员` }, { key: 'action', label: '建议操作', children: RECOMMENDED_ACTION_LABELS[drift?.recommendedAction as string] || drift?.recommendedAction || '无需操作' }, { key: 'threshold', label: '漂移阈值', children: `预警 ${(Number(drift?.thresholds?.warnDrop || 0) * 100).toFixed(0)}% / 严重 ${(Number(drift?.thresholds?.criticalDrop || 0) * 100).toFixed(0)}%` }]} /></Card></Col>
    </Row>
  </PageContainer>;
}
