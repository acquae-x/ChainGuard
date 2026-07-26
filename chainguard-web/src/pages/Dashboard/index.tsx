import { Access, history, useAccess, useModel } from '@umijs/max';
import { Alert, Button, Card, Col, Empty, List, Result, Row, Space, Table, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { useEffect, useMemo, useState } from 'react';
import { AutomationStatsCard, KpiCard, NodeHealthPanel, RiskTag, SensitiveField, StatusTag } from '@/components';
import { getAutomationStats, getDashboardAudit, getKpis, getMyTasks, getPendingApprovals, getTopRisks } from '@/services/dashboard';
import type { AutomationStats } from '@/services/dashboard';
import { getOnboardingStatus } from '@/services/onboarding';
import type { OnboardingStatus } from '@/services/onboarding';
import { MISSING_TEXT } from '@/utils/proposalMetrics';
import { dashboardConfig } from './dashboardConfig';
import type { DashboardSection } from './dashboardConfig';

const ONBOARDING_ENTITY_KEYS: Record<string, string[]> = {
  material: ['material'],
  supplier: ['supplier', 'supplierMaterial'],
  inventory: ['inventory'],
  customer: ['customer', 'order', 'orderLine'],
};

export default function DashboardPage() {
  const { initialState } = useModel('@@initialState');
  const access = useAccess();
  const role = initialState?.currentUser?.roleCode || 'scm_lead';
  const config = dashboardConfig[role];
  const [risks, setRisks] = useState<API.Risk[]>([]);
  const [tasks, setTasks] = useState<API.Task[]>([]);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [audits, setAudits] = useState<API.AuditLog[]>([]);
  const [kpiData, setKpiData] = useState<Record<string, number>>({});
  const [kpiSeries, setKpiSeries] = useState<{ monthlySeries?: any[]; responseSeries?: any[] }>({});
  const [automationStats, setAutomationStats] = useState<AutomationStats>();
  const [onboarding, setOnboarding] = useState<OnboardingStatus>();
  // 四态补全（05 文档第 4 节）：加载骨架 + 错误重试，接真实后端后即生效
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const load = async () => {
    setLoading(true);
    setError(undefined);
    try {
      const [nextRisks, nextTasks, nextApprovals, nextAudits, nextKpis, nextAutomationStats] = await Promise.all([getTopRisks(), getMyTasks(), getPendingApprovals(), getDashboardAudit(), getKpis(), getAutomationStats()]);
      setRisks(nextRisks); setTasks(nextTasks); setApprovals(nextApprovals); setAudits(nextAudits); setKpiData((nextKpis || {}) as Record<string, number>);
      setKpiSeries({ monthlySeries: (nextKpis as any)?.monthlySeries, responseSeries: (nextKpis as any)?.responseSeries });
      setAutomationStats(nextAutomationStats);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '工作台数据加载失败');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [role]);
  // C3 entry is advisory, not a second permission gate.  The backend derives
  // it from tenant-scoped C2 entities, so tenants with data are never blocked.
  useEffect(() => { getOnboardingStatus().then(setOnboarding).catch(() => undefined); }, []);
  const roleTasks = useMemo(() => tasks.filter((item) => item.roleCode === role).slice(0, 8), [role, tasks]);
  // recommendedData 的一条建议往往覆盖多张实体表（如「供应商与供料关系」= supplier + supplierMaterial），
  // 任一张为空就说明这条还没做完。
  const onboardingTodos = useMemo(() => {
    const real = onboarding?.entitySummary?.realCounts || {};
    return (onboarding?.recommendedData || [])
      .filter((item) => item.required)
      .filter((item) => (ONBOARDING_ENTITY_KEYS[item.type] || [item.type]).some((key) => !real[key]))
      .map((item) => ({ key: item.type, label: `导入${item.label}`, path: '/data/import' }));
  }, [onboarding]);

  // 可计数 KPI 用真实 API 数据覆盖硬编码演示值，保证与列表/图表一致。
  const KPI_SOURCE: Record<string, string> = { risk: 'riskCount', high: 'highRiskCount', approval: 'pendingApprovals', countersign: 'countersign', incident: 'incidentCount', overdue: 'overdueTasks', late: 'overdueTasks', mine: 'myTasks', task: 'myTasks', member: 'memberCount', onboarding: 'onboardingPending', import: 'weeklyImports', failed: 'failedImports', arrival: 'arrivalDelays', loss: 'avoidedLoss', saving: 'netBenefit', cost: 'emergencyCost' };
  const kpiValue = (item: { key: string; value: number | string }) => {
    const field = KPI_SOURCE[item.key];
    return field && kpiData[field] !== undefined ? kpiData[field] : item.value;
  };
  // 金额类 KPI 过去直接渲染配置里的 ¥ 字面量，完全不看后端。现在同样走 KPI_SOURCE；
  // 后端在无事件或无字段权限时返回 null，这里如实显示"数据缺失"，不回落成 0。
  const sensitiveValue = (item: { key: string }) => {
    const raw = kpiData[KPI_SOURCE[item.key]];
    return raw === undefined || raw === null ? MISSING_TEXT : `¥${Number(raw).toLocaleString()}`;
  };

  const renderSection = (section: DashboardSection) => {
    // C02：管理者的供应链节点健康概览。C03：一线角色的「我的节点」明细。
    // 两者是同一个面板的两种数据范围，范围由后端按既有权限码派生，前端不做权限判断。
    if (section === 'nodeHealth') return <Card key={section} title="供应链节点健康"><NodeHealthPanel mode="overview" /></Card>;
    if (section === 'myNodes') return <Card key={section} title="我的节点"><NodeHealthPanel mode="mine" testIdPrefix="my-nodes" /></Card>;
    if (section === 'riskDistribution') return <Card key={section} title="风险等级分布"><ReactECharts style={{ height: 260 }} option={{ series: [{ type: 'pie', radius: '60%', data: [{ name: '高风险', value: risks.filter((item) => item.level === 'high').length }, { name: '中风险', value: risks.filter((item) => item.level === 'medium').length }, { name: '低风险', value: risks.filter((item) => item.level === 'low').length }] }] }} /></Card>;
    // 两张趋势图改由 /dashboard/kpis 的真实月度聚合驱动；原先是与租户无关的写死数组。
    if (section === 'costTrend' || section === 'responseTrend') {
      const isCost = section === 'costTrend';
      const points: any[] = (isCost ? kpiSeries.monthlySeries : kpiSeries.responseSeries) || [];
      return <Card key={section} title={isCost ? '应急成本趋势' : '应急响应时长趋势'}>
        {points.length === 0
          ? <Empty description={isCost ? '暂无事件成本记录' : '暂无已完成审批，无法统计响应时长'} />
          : <ReactECharts style={{ height: 240 }} option={{
              tooltip: { trigger: 'axis' },
              xAxis: { type: 'category', data: points.map((item) => item.month) },
              yAxis: { type: 'value' },
              series: isCost
                ? [{ name: '应急成本', type: 'bar', data: points.map((item) => item.emergencyCost) }, { name: '避免损失', type: 'bar', data: points.map((item) => item.avoidedLoss) }]
                : [{ name: '平均响应时长(小时)', type: 'line', data: points.map((item) => item.avgResponseHours) }],
            }} />}
      </Card>;
    }
    // 待办按 /onboarding/status 的真实实体计数派生：原先是写死的两条，
    // 供应商数据早已导入时仍在催「导入供应商主数据」，且与向导页「已准备完成」矛盾。
    if (section === 'onboarding') return <Card key={section} title="初始化待办"><List dataSource={onboardingTodos} locale={{ emptyText: '必需资料已齐备，无待办事项' }} renderItem={(item) => <List.Item actions={[<Button key={item.key} type="link" onClick={() => history.push(item.path)}>处理</Button>]}>{item.label}</List.Item>} /></Card>;
    if (section === 'auditFeed') return <Card key={section} title="最近审计动态"><List dataSource={audits} renderItem={(item) => <List.Item>{item.time} {item.action}：{item.targetName}</List.Item>} /></Card>;
    if (section === 'approvalList') return <Card key={section} title="待会签列表"><Table size="small" rowKey="id" pagination={false} dataSource={approvals} columns={[{ title: '审批单', dataIndex: 'id' }, { title: '方案', dataIndex: 'summary' }, { title: '成本影响', render: (_, row) => (row.costImpact === null || row.costImpact === undefined ? '数据缺失' : <SensitiveField field="cost" value={`¥${row.costImpact.toLocaleString()}`} />) }]} /></Card>;
    if (section === 'highRiskTop5' || section === 'riskList' || section === 'supplierRisk' || section === 'inventoryRisk' || section === 'orderRisk' || section === 'materialRisk') return <Card key={section} style={{ minWidth: 0, maxWidth: '100%' }} title={section === 'highRiskTop5' ? '高风险事件 Top5' : section === 'riskList' ? '风险列表 Top8' : section === 'inventoryRisk' ? '库存预警列表' : section === 'orderRisk' ? '订单风险列表' : section === 'materialRisk' ? '物料齐套风险表' : '供应商交期风险表'}><Table size="small" rowKey="id" pagination={false} scroll={{ x: 'max-content' }} dataSource={(section === 'highRiskTop5' ? risks.filter((item) => item.level === 'high') : risks).slice(0, 8)} columns={[{ title: '等级', dataIndex: 'level', render: (level) => <RiskTag level={level} /> }, { title: '对象', dataIndex: 'objectName' }, { title: '指数', dataIndex: 'score' }, { title: '状态', dataIndex: 'status', render: (status) => <StatusTag status={status} /> }, { title: '操作', render: (_, record: API.Risk & { incidentId?: string }) => !config.readonly && access.canCreateIncident ? <Button size="small" onClick={() => record.incidentId ? history.push(`/incident/${record.incidentId}`) : history.push('/risk/list')}>{record.incidentId ? '查看关联事件' : '创建事件'}</Button> : null }]} /></Card>;
    if (section === 'supplierAlerts') return <Card key={section} title="供应商异常与库存预警"><List dataSource={risks.slice(0, 3)} renderItem={(item) => <List.Item><Typography.Text>{item.objectName}</Typography.Text><StatusTag status={item.status} /></List.Item>} /></Card>;
    return <Card key={section} title={section === 'customerTasks' ? '客户沟通任务' : '我的任务'}><List dataSource={roleTasks} locale={{ emptyText: '暂无待处理任务' }} renderItem={(item) => <List.Item><Typography.Text>{item.title}</Typography.Text><StatusTag status={item.status} /></List.Item>} /></Card>;
  };

  if (error) return <Result status="500" title="工作台数据加载失败" subTitle={error} extra={<Button type="primary" onClick={load}>重试</Button>} />;
  if (loading) return <Space direction="vertical" size="middle" style={{ width: '100%' }}><Row gutter={[16, 16]}>{[1, 2, 3, 4].map((key) => <Col xs={24} md={12} xl={6} key={key}><Card loading /></Col>)}</Row><Card loading /><Card loading /></Space>;

  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    {onboarding?.guideVisible && <Alert type="info" showIcon message="开始准备真实业务数据" description="当前租户还没有 C2 业务实体数据。导入物料、供应商、库存和订单后即可进入真实决策链路。" action={<Button size="small" type="primary" onClick={() => history.push('/onboarding')}>查看引导</Button>} />}
    {(onboarding?.entitySummary.hasDemoData || initialState?.tenant?.demoDataFlag) && <Alert type="warning" showIcon message="当前租户包含演示数据" description="演示数据具有来源标记；它不是 run_demo，也不会写入其他租户。导入真实数据前请确认避免混合使用。" action={<Button size="small" onClick={() => history.push('/data/import')}>查看数据导入</Button>} />}
    <Space wrap><Access accessible={access.canCreateIncident && !config.readonly}><Button type="primary" icon={<PlusOutlined />} onClick={() => history.push('/risk/list')}>上报异常</Button></Access><Access accessible={access.canApproval}><Button onClick={() => history.push('/decision/approval')}>待我审批</Button></Access><Button onClick={() => history.push('/risk/overview')}>风险总览</Button>{role === 'admin' && <Button onClick={() => history.push('/settings/users')}>邀请成员</Button>}</Space>
    <Row gutter={[16, 16]}>{config.kpis.map((item) => <Col xs={24} md={12} xl={6} key={item.key}>{item.sensitive ? <Card><Typography.Text type="secondary">{item.title}</Typography.Text><Typography.Title level={3}><SensitiveField field={item.sensitive} value={sensitiveValue(item)} /></Typography.Title><Typography.Text type="secondary">{item.trend}</Typography.Text></Card> : <KpiCard title={item.title} value={kpiValue(item)} trend={item.trend} />}</Col>)}</Row>
    {automationStats && <AutomationStatsCard stats={automationStats} />}
    <Row gutter={[16, 16]}>{config.second.map((section) => <Col xs={24} xl={config.second.length > 1 ? 12 : 24} key={section}>{renderSection(section)}</Col>)}</Row>
    <Row gutter={[16, 16]}>{config.third.map((section) => <Col xs={24} xl={24} key={section}>{renderSection(section)}</Col>)}</Row>
  </Space>;
}
