import { Access, history, useAccess, useModel } from '@umijs/max';
import { Alert, Button, Card, Col, List, Result, Row, Space, Table, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { useEffect, useMemo, useState } from 'react';
import { KpiCard, RiskTag, SensitiveField, StatusTag } from '@/components';
import { getDashboardAudit, getMyTasks, getPendingApprovals, getTopRisks } from '@/services/dashboard';
import { dashboardConfig } from './dashboardConfig';
import type { DashboardSection } from './dashboardConfig';

export default function DashboardPage() {
  const { initialState } = useModel('@@initialState');
  const access = useAccess();
  const role = initialState?.currentUser?.roleCode || 'scm_lead';
  const config = dashboardConfig[role];
  const [risks, setRisks] = useState<API.Risk[]>([]);
  const [tasks, setTasks] = useState<API.Task[]>([]);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [audits, setAudits] = useState<API.AuditLog[]>([]);
  // 四态补全（05 文档第 4 节）：加载骨架 + 错误重试，接真实后端后即生效
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const load = async () => {
    setLoading(true);
    setError(undefined);
    try {
      const [nextRisks, nextTasks, nextApprovals, nextAudits] = await Promise.all([getTopRisks(), getMyTasks(), getPendingApprovals(), getDashboardAudit()]);
      setRisks(nextRisks); setTasks(nextTasks); setApprovals(nextApprovals); setAudits(nextAudits);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '工作台数据加载失败');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [role]);
  const roleTasks = useMemo(() => tasks.filter((item) => item.roleCode === role).slice(0, 8), [role, tasks]);

  const renderSection = (section: DashboardSection) => {
    if (section === 'riskDistribution') return <Card key={section} title="风险等级分布"><ReactECharts style={{ height: 260 }} option={{ series: [{ type: 'pie', radius: '60%', data: [{ name: '高风险', value: risks.filter((item) => item.level === 'high').length }, { name: '中风险', value: risks.filter((item) => item.level === 'medium').length }, { name: '低风险', value: risks.filter((item) => item.level === 'low').length }] }] }} /></Card>;
    if (section === 'responseTrend' || section === 'costTrend') return <Card key={section} title={section === 'costTrend' ? '应急成本趋势' : '应急响应时长趋势'}><ReactECharts style={{ height: 240 }} option={{ xAxis: { type: 'category', data: ['2月', '3月', '4月', '5月', '6月', '7月'] }, yAxis: { type: 'value' }, series: [{ type: section === 'costTrend' ? 'bar' : 'line', data: section === 'costTrend' ? [12, 14, 9, 18, 16, 12.8] : [8, 6.5, 7, 5.2, 4.8, 5.2] }] }} /></Card>;
    if (section === 'onboarding') return <Card key={section} title="初始化待办"><List dataSource={['导入供应商主数据', '完善审批流设置']} renderItem={(item) => <List.Item actions={[<Button key={item} type="link" onClick={() => history.push(item.includes('导入') ? '/data/import' : '/settings/approval')}>处理</Button>]}>{item}</List.Item>} /></Card>;
    if (section === 'auditFeed') return <Card key={section} title="最近审计动态"><List dataSource={audits} renderItem={(item) => <List.Item>{item.time} {item.action}：{item.targetName}</List.Item>} /></Card>;
    if (section === 'approvalList') return <Card key={section} title="待会签列表"><Table size="small" rowKey="id" pagination={false} dataSource={approvals} columns={[{ title: '审批单', dataIndex: 'id' }, { title: '方案', dataIndex: 'summary' }, { title: '成本影响', render: (_, row) => (row.costImpact === null || row.costImpact === undefined ? '数据缺失' : <SensitiveField field="cost" value={`¥${row.costImpact.toLocaleString()}`} />) }]} /></Card>;
    if (section === 'highRiskTop5' || section === 'riskList' || section === 'supplierRisk' || section === 'inventoryRisk' || section === 'orderRisk' || section === 'materialRisk') return <Card key={section} title={section === 'highRiskTop5' ? '高风险事件 Top5' : section === 'riskList' ? '风险列表 Top8' : section === 'inventoryRisk' ? '库存预警列表' : section === 'orderRisk' ? '订单风险列表' : section === 'materialRisk' ? '物料齐套风险表' : '供应商交期风险表'}><Table size="small" rowKey="id" pagination={false} dataSource={(section === 'highRiskTop5' ? risks.filter((item) => item.level === 'high') : risks).slice(0, 8)} columns={[{ title: '等级', dataIndex: 'level', render: (level) => <RiskTag level={level} /> }, { title: '对象', dataIndex: 'objectName' }, { title: '指数', dataIndex: 'score' }, { title: '状态', dataIndex: 'status', render: (status) => <StatusTag status={status} /> }, { title: '操作', render: (_, record: API.Risk & { incidentId?: string }) => !config.readonly && access.canCreateIncident ? <Button size="small" onClick={() => record.incidentId ? history.push(`/incident/${record.incidentId}`) : history.push('/risk/list')}>{record.incidentId ? '查看关联事件' : '创建事件'}</Button> : null }]} /></Card>;
    if (section === 'supplierAlerts') return <Card key={section} title="供应商异常与库存预警"><List dataSource={risks.slice(0, 3)} renderItem={(item) => <List.Item><Typography.Text>{item.objectName}</Typography.Text><StatusTag status={item.status} /></List.Item>} /></Card>;
    return <Card key={section} title={section === 'customerTasks' ? '客户沟通任务' : '我的任务'}><List dataSource={roleTasks} locale={{ emptyText: '暂无待处理任务' }} renderItem={(item) => <List.Item><Typography.Text>{item.title}</Typography.Text><StatusTag status={item.status} /></List.Item>} /></Card>;
  };

  if (error) return <Result status="500" title="工作台数据加载失败" subTitle={error} extra={<Button type="primary" onClick={load}>重试</Button>} />;
  if (loading) return <Space direction="vertical" size="middle" style={{ width: '100%' }}><Row gutter={[16, 16]}>{[1, 2, 3, 4].map((key) => <Col xs={24} md={12} xl={6} key={key}><Card loading /></Col>)}</Row><Card loading /><Card loading /></Space>;

  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    {initialState?.tenant?.demoDataFlag && <Alert type="warning" showIcon message="当前为示例数据，导入真实数据后可关闭提示。" action={<Button size="small" onClick={() => history.push('/data/import')}>导入真实数据</Button>} />}
    <Space wrap><Access accessible={access.canCreateIncident && !config.readonly}><Button type="primary" icon={<PlusOutlined />} onClick={() => history.push('/risk/list')}>上报异常</Button></Access><Access accessible={access.canApproval}><Button onClick={() => history.push('/decision/approval')}>待我审批</Button></Access><Button onClick={() => history.push('/risk/overview')}>风险总览</Button>{role === 'admin' && <Button onClick={() => history.push('/settings/users')}>邀请成员</Button>}</Space>
    <Row gutter={[16, 16]}>{config.kpis.map((item) => <Col xs={24} md={12} xl={6} key={item.key}>{item.sensitive ? <Card><Typography.Text type="secondary">{item.title}</Typography.Text><Typography.Title level={3}><SensitiveField field={item.sensitive} value={item.value} /></Typography.Title><Typography.Text type="secondary">{item.trend}</Typography.Text></Card> : <KpiCard title={item.title} value={item.value} trend={item.trend} />}</Col>)}</Row>
    <Row gutter={[16, 16]}>{config.second.map((section) => <Col xs={24} xl={config.second.length > 1 ? 12 : 24} key={section}>{renderSection(section)}</Col>)}</Row>
    <Row gutter={[16, 16]}>{config.third.map((section) => <Col xs={24} xl={24} key={section}>{renderSection(section)}</Col>)}</Row>
  </Space>;
}
