import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Select, Tag, message } from 'antd';
import { ROLE_LABELS } from '@/constants/status';

export default function Scopes() {
  const data = Object.entries(ROLE_LABELS).map(([code, name]) => ({ code, name, scope: ['admin', 'boss', 'scm_lead', 'finance', 'auditor'].includes(code) ? 'all' : 'custom' }));
  return <PageContainer title="数据权限" subTitle="能力权限决定能做什么，数据范围决定能看哪些记录"><ProTable search={false} rowKey="code" dataSource={data} columns={[{ title: '角色', dataIndex: 'name' }, { title: '代码', dataIndex: 'code', render: (_, row) => <Tag>{row.code}</Tag> }, { title: '数据范围', dataIndex: 'scope', render: (_, row) => <Select defaultValue={row.scope} style={{ width: 160 }} options={[{ label: '全企业', value: 'all' }, { label: '本部门', value: 'dept' }, { label: '本人负责', value: 'own' }, { label: '自定义', value: 'custom' }]} onChange={() => message.success('数据范围已更新')} /> }, { title: '字段权限', render: () => '按角色字段白名单控制' }]} /></PageContainer>;
}
