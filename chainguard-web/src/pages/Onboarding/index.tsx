import { history, useAccess } from '@/runtime';
import { Alert, App, Button, Card, Descriptions, Result, Space, Spin, Steps, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { ImportWizard } from '@/components';
import { getOnboardingStatus, injectDemoDataset, saveProgress } from '@/services/onboarding';
import type { OnboardingStatus } from '@/services/onboarding';

const progressSteps = ['了解数据要求', '通过真实导入准备数据', '进入真实决策链路'];

export default function OnboardingPage() {
  const access = useAccess();
  const { message, modal } = App.useApp();
  const [status, setStatus] = useState<OnboardingStatus>();
  const [view, setView] = useState<'overview' | 'import'>('overview');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [injecting, setInjecting] = useState(false);

  const reload = async () => {
    setLoading(true); setError(undefined);
    try { setStatus(await getOnboardingStatus()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '初始化状态加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void reload(); }, []);

  const enterSystem = async () => {
    await saveProgress({ lastStep: 'deferred', dismissed: true });
    history.push('/dashboard');
  };
  const confirmDemo = () => modal.confirm({
    title: '确认注入演示数据集？',
    content: '这会只向当前租户写入标记为“演示数据”的物料、供应商、库存和订单样例。不会调用 run_demo，也不会影响其他租户。已有业务数据的租户不能注入。',
    okText: '确认注入演示数据', okButtonProps: { danger: true }, cancelText: '返回真实导入',
    onOk: async () => {
      setInjecting(true);
      try { const result = await injectDemoDataset(); setStatus(result.status); message.success('演示数据集已注入当前租户'); }
      finally { setInjecting(false); }
    },
  });

  if (loading) return <Spin tip="正在读取当前租户的真实数据状态" />;
  if (error) return <Result status="error" title="无法读取初始化状态" subTitle={error} extra={<Button onClick={() => void reload()}>重试</Button>} />;
  if (!status) return null;
  if (!status.guideVisible) return <Result
    status="success"
    title={status.phase === 'demo_ready' ? '演示数据已准备完成' : '真实业务数据已准备完成'}
    subTitle={status.phase === 'demo_ready' ? '所有演示记录均带有来源标记。导入真实数据前请先确认数据治理策略，避免混合使用。' : status.entitySummary.decisionReady ? '已满足 C1 真实决策的最小数据链路，可创建事件并生成方案。' : '已检测到当前租户的业务数据；可继续补充缺少的数据类型。'}
    extra={<Space><Button type="primary" onClick={() => history.push('/dashboard')}>进入工作台</Button><Button onClick={() => history.push('/data/import')}>继续导入</Button></Space>}
  />;

  return <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 1080 }}>
    <Space style={{ justifyContent: 'space-between', width: '100%' }} wrap>
      <div><Typography.Title level={2} style={{ marginBottom: 4 }}>从真实业务数据开始</Typography.Title><Typography.Text type="secondary">当前租户尚无业务实体数据。完成导入后，风险与决策只会使用本租户的真实数据。</Typography.Text></div>
      <Button onClick={() => void enterSystem()}>稍后再说，进入工作台</Button>
    </Space>
    <Steps current={view === 'import' ? 1 : 0} items={progressSteps.map((title) => ({ title }))} />
    {view === 'overview' && <>
      <Alert type="info" showIcon message="推荐按依赖顺序导入" description="先物料，再供应商及供料关系、库存、客户、订单和订单行。这样可直接进入 C1 的真实租户决策链路。" />
      <Descriptions bordered column={{ xs: 1, md: 2 }} items={status.recommendedData.map((item) => ({ key: item.type, label: item.label, children: <Space direction="vertical" size={0}><Tag color={item.required ? 'blue' : 'default'}>{item.required ? '推荐优先导入' : '可选'}</Tag><Typography.Text>{item.template}</Typography.Text><Typography.Text type="secondary">关键字段：{item.fields.join('、')}</Typography.Text></Space> }))} />
      {access.canImport ? <Space wrap><Button type="primary" onClick={() => { setView('import'); void saveProgress({ lastStep: 'real_import' }); }}>开始真实导入</Button><Button danger loading={injecting} onClick={confirmDemo}>改为注入演示数据集</Button></Space> : <Alert type="warning" showIcon message="你没有数据导入权限" description="你可以查看所需资料和当前进度；请联系企业管理员、供应链负责人或对应资料域的管理员完成导入。" />}
      <Alert type="warning" showIcon message="演示数据绝不会自动注入" description="只有你点击“改为注入演示数据集”并在第二次确认后，系统才会写入当前租户；已有业务数据时该操作会被后端拒绝。" />
    </>}
    {view === 'import' && <Card title="真实业务数据导入" extra={<Button onClick={() => setView('overview')}>返回数据要求</Button>}><Alert type="info" showIcon message="复用企业数据导入流程" description="上传、预检、人工确认和执行全部由现有 C2 导入向导完成；本页不会创建旁路导入。" style={{ marginBottom: 16 }} /><ImportWizard embedded onCompleted={() => void reload()} /></Card>}
  </Space>;
}
