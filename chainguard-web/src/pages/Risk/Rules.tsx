import { useAccess } from '@/runtime';
import { ProTable } from '@/components/pro';
import { Switch, Tag, message } from 'antd';
import { getRules, updateRule } from '@/services/risk';

export default function RiskRulesPage() {
  const access = useAccess();
  return (
    <ProTable
      rowKey="id"
      search={false}
      request={async () => ({ ...(await getRules()), success: true })}
      columns={[
        { title: '规则名称', dataIndex: 'name' },
        { title: '阈值', dataIndex: 'threshold' },
        { title: '启用', dataIndex: 'enabled', render: (_, row: any) => access.canManageRisk ? <Switch defaultChecked={row.enabled} onChange={async (enabled) => { await updateRule({ ...row, enabled }); message.success('规则已更新并写入审计'); }} /> : <Tag color={row.enabled ? 'green' : 'default'}>{row.enabled ? '已启用' : '已停用'}</Tag> }
      ]}
    />
  );
}
