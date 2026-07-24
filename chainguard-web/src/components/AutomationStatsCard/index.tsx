import { Card, Col, List, Row, Statistic, Typography } from 'antd';
import type { AutomationStats } from '@/services/dashboard';

type Props = {
  stats: AutomationStats;
};

export default function AutomationStatsCard({ stats }: Props) {
  return <Card title="人机分工">
    <Row gutter={[16, 16]}>
      <Col xs={24} md={8}><Statistic data-testid="automation-rate" title="自动化率" value={stats.automationRate} formatter={() => `${(stats.automationRate * 100).toFixed(1)}%`} /></Col>
      <Col xs={12} md={8}><Statistic title="自动放行" value={stats.autoApproved} suffix="条" /></Col>
      <Col xs={12} md={8}><Statistic title="升级人工" value={stats.escalated} suffix="条" /></Col>
    </Row>
    <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 8 }}>
      基于 {stats.totalDecisions} 条租户决策审计记录统计；命中以下任一规则即升级人工处理。
    </Typography.Paragraph>
    <List
      size="small"
      locale={{ emptyText: '暂无决策审计记录' }}
      dataSource={stats.escalationRules}
      renderItem={(rule) => <List.Item key={rule.code}>{rule.description}</List.Item>}
    />
  </Card>;
}
