import { history } from '@/runtime';
import { PageContainer, ProTable } from '@/components/pro';
import { Button, Tag } from 'antd';
import { EyeOutlined, PlusOutlined } from '@ant-design/icons';
import { RiskTag, SensitiveField } from '@/components';
import { getProposals } from '@/services/decision';
import { daysLabel, isMissing, moneyLabel, riskLabel, MISSING_TEXT } from '@/utils/proposalMetrics';

export default function DecisionList() {
  return (
    <PageContainer title="方案列表" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => history.push('/incident/list')}>从事件生成方案</Button>}>
      <ProTable<API.Proposal>
        rowKey="id"
        request={getProposals}
        columns={[
          { title: '方案编号', dataIndex: 'id', copyable: true },
          { title: '方案名称', dataIndex: 'name' },
          { title: '标签', dataIndex: 'tag', valueType: 'select', valueEnum: { recommended: { text: '推荐' }, alternative: { text: '备选' }, invalid: { text: '不可行' } }, render: (_, row) => <Tag color={row.tag === 'recommended' ? 'gold' : row.tag === 'invalid' ? 'red' : 'default'}>{row.tag === 'recommended' ? '推荐' : row.tag === 'invalid' ? '不可行' : '备选'}</Tag> },
          { title: '总成本', dataIndex: 'totalCost', search: false, render: (_, row) => isMissing(row.totalCost) ? MISSING_TEXT : <SensitiveField field="cost" value={moneyLabel(row.totalCost)} /> },
          { title: '交期影响', dataIndex: 'leadTimeImpact', search: false, renderText: (value) => daysLabel(value as number | null) },
          { title: '剩余风险', dataIndex: 'residualRisk', valueType: 'select', render: (_, row) => isMissing(row.residualRisk) ? riskLabel(row.residualRisk) : <RiskTag level={row.residualRisk} /> },
          { title: '操作', valueType: 'option', render: (_, row) => <Button type="link" icon={<EyeOutlined />} onClick={() => history.push(`/decision/generate/${row.incidentId}?readonly=1`)}>查看对比</Button> }
        ]}
      />
    </PageContainer>
  );
}
