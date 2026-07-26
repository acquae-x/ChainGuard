import ReactECharts from 'echarts-for-react';
import { useAccess, useModel } from '@umijs/max';
import { Button, Card, Col, Empty, Row, Space, Table, Typography, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { KpiCard, RiskTag, StatusTag } from '@/components';
import { getRiskMatrix, getRisks, recomputeRisks } from '@/services/risk';
import { getKpis } from '@/services/dashboard';
import { palette } from '@/theme';

const LEVEL_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低' };

export default function RiskOverviewPage() {
  const access = useAccess();
  const { initialState } = useModel('@@initialState');
  const [risks, setRisks] = useState<API.Risk[]>([]);
  const [matrix, setMatrix] = useState<any[]>([]);
  const [todayRiskCount, setTodayRiskCount] = useState(0);
  const [scanning, setScanning] = useState(false);
  const load = useCallback(() => {
    getRisks().then((res) => setRisks(res.data));
    getRiskMatrix().then(setMatrix);
    getKpis().then((payload: any) => setTodayRiskCount(Number(payload?.todayRiskCount || 0)));
  }, []);
  useEffect(() => { load(); }, [load]);
  // A03：按当前租户实体重算库存风险。同步单次，仅 risk:manage 可见。
  const rescan = async () => {
    setScanning(true);
    try {
      const result: any = await recomputeRisks();
      const skipped = Number(result?.skippedCount || 0);
      message.success(
        `重新扫描完成：新增 ${result?.created ?? 0}，更新 ${result?.updated ?? 0}，`
        + `消除 ${result?.resolved ?? 0}，复发 ${result?.recurred ?? 0}，未变化 ${result?.unchanged ?? 0}`
        + (skipped ? `；${skipped} 个物料因数据不足未计算` : ''),
      );
      load();
    } catch (error: any) {
      message.error(error?.message || '重新扫描失败');
    } finally {
      setScanning(false);
    }
  };
  // KPI 从真实风险数据计算，不再硬编码
  const kpis = useMemo(() => [
    { title: '高风险数', value: risks.filter((item) => item.level === 'high').length },
    { title: '中风险数', value: risks.filter((item) => item.level === 'medium').length },
    { title: '低风险数', value: risks.filter((item) => item.level === 'low').length },
    { title: `今日新增（${initialState?.tenant?.timezone || 'UTC'}）`, value: todayRiskCount },
  ], [initialState?.tenant?.timezone, risks, todayRiskCount]);
  // 类型分布由真实数据聚合
  const typeData = useMemo(() => {
    const counts = new Map<string, number>();
    risks.forEach((item) => counts.set(item.type || '未分类', (counts.get(item.type || '未分类') || 0) + 1));
    return [...counts.entries()].map(([name, value]) => ({ name, value }));
  }, [risks]);
  const matrixPoints = matrix.filter((item) => Array.isArray(item?.value));
  const maxImpact = Math.max(3, ...matrixPoints.map((item) => Number(item.value[0]) || 0));
  // 图表文字替代摘要
  const matrixSummary = matrixPoints.length
    ? `共 ${matrixPoints.length} 个风险点：${matrixPoints.map((item) => `${item.name}（${LEVEL_LABELS[item.level] || item.level}，评分 ${item.value[2]}）`).join('、')}。`
    : '暂无风险矩阵数据。';
  const typeSummary = typeData.length
    ? `按类型：${typeData.map((item) => `${item.name} ${item.value} 项`).join('、')}。`
    : '暂无类型分布数据。';
  // 坐标轴必须是数值轴（此前缺 type:'value'，散点全部无法落点）；气泡大小做上限裁剪
  const matrixOption = {
    color: palette.chart,
    tooltip: { trigger: 'item', formatter: (item: any) => `${item.data?.name || ''}<br/>影响：${item.value?.[0]}<br/>概率：${item.value?.[1]}<br/>评分：${item.value?.[2]}` },
    grid: { left: 48, right: 24, top: 32, bottom: 40 },
    xAxis: { type: 'value', name: '影响', min: 0, max: maxImpact + 1 },
    yAxis: { type: 'value', name: '概率', min: 0, max: 10 },
    series: [{ type: 'scatter', symbolSize: (value: any) => Math.min(Math.max(Number(value?.[2]) / 4, 10), 36), data: matrixPoints.map((item) => ({ name: item.name, value: item.value })) }],
  };
  const pieOption = {
    color: palette.chart,
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [{ type: 'pie', radius: '60%', data: typeData, label: { formatter: '{b}: {c}' } }],
  };
  return (
    <div>
      {access.canManageRisk ? (
        <Space style={{ marginBottom: 16 }}>
          <Button type="primary" loading={scanning} onClick={rescan}>重新扫描风险</Button>
          <Typography.Text type="secondary">按当前租户的物料、库存、订单与供应商数据重算库存风险</Typography.Text>
        </Space>
      ) : null}
      <Row gutter={[16, 16]}>{kpis.map((item) => <Col xs={24} md={12} xl={6} key={item.title}><KpiCard title={item.title} value={item.value} /></Col>)}</Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={14}>
          <Card title="风险矩阵图">
            {matrixPoints.length ? <ReactECharts style={{ height: 320, width: '100%' }} option={matrixOption} notMerge /> : <Empty description="暂无风险矩阵数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: '60px 0' }} />}
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>{matrixSummary}</Typography.Paragraph>
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card title="按类型分布">
            {typeData.length ? <ReactECharts style={{ height: 320, width: '100%' }} option={pieOption} notMerge /> : <Empty description="暂无类型分布数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: '60px 0' }} />}
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>{typeSummary}</Typography.Paragraph>
          </Card>
        </Col>
      </Row>
      <Card title="最新风险" style={{ marginTop: 16 }}>
        <Table rowKey="id" dataSource={risks} pagination={false} columns={[{ title: '等级', dataIndex: 'level', render: (v) => <RiskTag level={v} /> }, { title: '对象', dataIndex: 'objectName' }, { title: '状态', dataIndex: 'status', render: (v) => <StatusTag status={v} /> }]} />
      </Card>
    </div>
  );
}
