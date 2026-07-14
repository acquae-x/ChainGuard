import { DownloadOutlined } from '@ant-design/icons';
import { Alert, Button, Collapse, Descriptions, Drawer, Empty, Grid, Space, Tag, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { exportDecisionDetail, getDecisionDetail } from '@/services/decision';
import { SensitiveField } from '@/components';

const ROLE_LABELS: Record<string, string> = { procurement: '采购', logistics: '物流', finance: '财务' };

export default function DecisionTrace({ incidentId, open, onClose }: { incidentId: string; open: boolean; onClose: () => void }) {
  const [detail, setDetail] = useState<any>();
  const screens = Grid.useBreakpoint();
  // 评审修复：无推演数据（历史/演示单）时显示空态，而不是永远停在"加载中"
  useEffect(() => { if (open) getDecisionDetail(incidentId).then(setDetail).catch(() => setDetail({ __missing: true })); }, [open, incidentId]);
  // P2-13：导出失败留在当前上下文提示，不允许 Promise 拒绝冒泡成整页错误
  const doExport = async (format: 'json' | 'pdf') => {
    try {
      await exportDecisionDetail(incidentId, format);
    } catch (reason) {
      message.error(reason instanceof Error && reason.message ? reason.message : '导出失败，请稍后重试');
    }
  };
  const proposals = detail?.proposals || [];
  const pareto = detail?.game_analysis?.pareto || {};
  const paretoPoints = pareto.points || [];
  const frontier = pareto.frontier || [];
  const sensitivity = detail?.sensitivity || [];
  const constraints = detail?.constraint_analysis || {};
  const optimalCombo = constraints.optimal_combo || {};
  const violations: any[] = Array.isArray(constraints.constraint_violations) ? constraints.constraint_violations : [];
  const recommendedChanges: any[] = Array.isArray(constraints.recommended_changes) ? constraints.recommended_changes : [];
  const feasibleCount = constraints.feasible_count;
  const optimalUtility = constraints.optimal_system_utility;
  const feasiblePoints = paretoPoints.filter((item: any) => item.feasible);
  // P2-14：图表必须有文字替代摘要（无障碍/空态兜底）
  const paretoSummary = paretoPoints.length
    ? `共 ${paretoPoints.length} 个策略组合，其中 ${feasiblePoints.length} 个可行；最优组合系统效用 ${typeof optimalUtility === 'number' ? optimalUtility.toFixed(2) : optimalUtility ?? '数据缺失'}。`
    : '暂无策略组合数据。';
  const sensitivitySummary = sensitivity.length
    ? `库存水平从 ${sensitivity[0]?.param_value} 到 ${sensitivity[sensitivity.length - 1]?.param_value}，风险指数从 ${sensitivity[0]?.inventory_risk_index} 变化到 ${sensitivity[sensitivity.length - 1]?.inventory_risk_index}。`
    : '暂无敏感性数据。';
  const paretoOption = {
    tooltip: { trigger: 'item', formatter: (item: any) => `${item.data?.label || ''}<br/>成本倍数：${item.value[0]}<br/>系统效用：${item.value[1]}` },
    grid: { left: screens.sm ? 48 : 36, right: screens.sm ? 28 : 16, top: 36, bottom: 48, containLabel: true },
    xAxis: { type: 'value', name: '成本倍数', nameLocation: 'middle', nameGap: 28 }, yAxis: { type: 'value', name: '系统效用' },
    series: [
      { type: 'scatter', name: '策略组合', data: paretoPoints.map((item: any) => ({ value: [item.cost_multiplier, item.system_utility], label: item.label, itemStyle: { color: item.is_optimal ? '#ff4d4f' : item.feasible ? '#52c41a' : '#bfbfbf' } })) },
      { type: 'line', name: 'Pareto 前沿', data: frontier.map((item: any) => [item.cost_multiplier, item.system_utility]), lineStyle: { type: 'dashed', color: '#52c41a' }, symbol: 'none' },
    ],
  };
  const sensitivityOption = {
    tooltip: { trigger: 'axis' }, grid: { left: screens.sm ? 48 : 36, right: screens.sm ? 28 : 16, top: 36, bottom: 48, containLabel: true }, xAxis: { type: 'category', name: '库存', nameLocation: 'middle', nameGap: 28, data: sensitivity.map((item: any) => item.param_value) }, yAxis: { type: 'value', name: '风险指数' },
    series: [{ type: 'line', smooth: true, data: sensitivity.map((item: any) => item.inventory_risk_index), itemStyle: { color: '#1677ff' } }],
  };
  const asText = (value: any): string => (value === undefined || value === null || value === '' ? '数据缺失' : typeof value === 'object' ? JSON.stringify(value) : String(value));
  return <Drawer title="完整推演" open={open} onClose={onClose} width={screens.md ? 760 : '100%'} rootStyle={{ maxWidth: '100vw' }} styles={{ body: { minWidth: 0, padding: screens.sm ? 24 : 12 } }}>
    <div style={{ width: '100%', minWidth: 0, maxWidth: '100%' }}>
    {!detail ? <Typography.Text>加载推演数据...</Typography.Text> : detail.__missing ? <Empty description="该审批单没有完整推演数据（历史或演示数据单）；新生成的方案会自动携带推演。" /> : <>
      <Space wrap style={{ marginBottom: 16 }}><Button icon={<DownloadOutlined />} onClick={() => doExport('json')}>导出 JSON</Button><Button icon={<DownloadOutlined />} onClick={() => doExport('pdf')}>导出 PDF</Button></Space>
      <Collapse defaultActiveKey={['score', 'constraints']} items={[
        { key: 'score', label: '1. 评分与冲突', children: <><Descriptions size="small" column={1} items={[{ key: 'conflict', label: '冲突检测', children: detail.conflict?.has_conflict ? '检测到方案资源冲突' : '未检测到阻断冲突' }]} /><Space wrap style={{ width: '100%' }}>{proposals.map((item: any, index: number) => { const cost = item.total_cost ?? item.cost; return <Tag style={{ maxWidth: '100%', whiteSpace: 'normal', wordBreak: 'break-word', lineHeight: 1.6 }} key={item.proposal_title || item.proposal_name || item.name || index}>{item.proposal_title || item.proposal_name || item.name || `方案${index + 1}`}：{cost !== undefined && cost !== null ? <SensitiveField field="cost" value={`¥${cost}`} /> : '成本数据缺失'}</Tag>; })}</Space></> },
        { key: 'debate', label: '2. 辩论过程', children: <Typography.Paragraph>{detail.rebuttal?.suggested_revision || detail.debate_result?.summary || '各角色意见已汇总并进入仲裁。'}</Typography.Paragraph> },
        { key: 'arbitration', label: '3. 仲裁结论与推导', children: (() => {
          // 评审修复：expected_effect 是对象（React error #31 元凶），任何字段渲染前都做类型归一
          const effectLabels: Record<string, string> = { supply_continuity: '供应连续性', delivery_risk: '交付风险', cost_risk: '成本风险', customer_impact: '客户影响' };
          const effectText = (value: any): string => value === undefined || value === null ? '数据缺失' : typeof value === 'object' ? Object.entries(value).map(([k, v]) => `${effectLabels[k] || k}：${typeof v === 'object' ? JSON.stringify(v) : v}`).join('；') : String(value);
          return <Descriptions column={1} size="small" items={[
            { key: 'strategy', label: '推荐策略', children: effectText(detail.arbitration?.final_strategy ?? detail.arbitration?.final_decision_title) },
            { key: 'effect', label: '预期效果', children: effectText(detail.arbitration?.expected_effect) },
            { key: 'score', label: '综合评分', children: detail.arbitration?.final_score ?? '数据缺失' },
          ]} />;
        })() },
        // P1-5：第 4 节改为结构化摘要 + 图表前置，禁止把 constraint_analysis 原始 JSON 当主展示
        { key: 'constraints', label: '4. 约束分析与推荐调整', children: <>
          <Typography.Text strong>敏感性：库存水平 vs 风险指数</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 4 }}>{sensitivitySummary}</Typography.Paragraph>
          {sensitivity.length ? <ReactECharts option={sensitivityOption} style={{ height: 260, width: '100%' }} /> : <Empty description="暂无敏感性数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          <Typography.Text strong>策略组合 Pareto 前沿</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 4 }}>{paretoSummary}</Typography.Paragraph>
          {paretoPoints.length ? <ReactECharts option={paretoOption} style={{ height: 300, width: '100%' }} /> : <Empty description="暂无策略组合数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          <Descriptions column={1} size="small" style={{ marginTop: 12 }} items={[
            { key: 'feasible', label: '可行组合数', children: feasibleCount !== undefined && feasibleCount !== null ? `${feasibleCount} 个` : '数据缺失' },
            { key: 'optimal', label: '最优组合', children: Object.keys(optimalCombo).length ? Object.entries(optimalCombo).map(([role, strategy]) => `${ROLE_LABELS[role] || role}：${asText(strategy)}`).join('；') : '数据缺失' },
            { key: 'utility', label: '最优系统效用', children: typeof optimalUtility === 'number' ? optimalUtility.toFixed(2) : asText(optimalUtility) },
          ]} />
          <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>约束违反</Typography.Text>
          {violations.length
            ? <ul style={{ margin: '4px 0 0', paddingInlineStart: 20 }}>{violations.map((item, index) => <li key={index}><Typography.Text>{asText(item)}</Typography.Text></li>)}</ul>
            : <Typography.Paragraph type="secondary">未发现约束违反。</Typography.Paragraph>}
          <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>推荐调整</Typography.Text>
          {recommendedChanges.length
            ? <ul style={{ margin: '4px 0 0', paddingInlineStart: 20 }}>{recommendedChanges.map((item, index) => <li key={index}><Typography.Text>{asText(item)}</Typography.Text></li>)}</ul>
            : <Typography.Paragraph type="secondary">{detail.arbitration?.manual_confirmation_points?.length ? `请核对执行确认点：${detail.arbitration.manual_confirmation_points.join('；')}` : '暂无推荐调整。'}</Typography.Paragraph>}
          {!Object.keys(constraints).length && <Alert type="info" showIcon style={{ marginTop: 12 }} message="本次推演未产出约束分析数据。" />}
        </> },
      ]} />
    </>}
    </div>
  </Drawer>;
}
