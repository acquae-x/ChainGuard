import { history } from '@umijs/max';
import { ProTable } from '@ant-design/pro-components';
import { Button } from 'antd';
import { RiskTag, StatusTag } from '@/components';
import { getIncidents } from '@/services/incident';

export default function IncidentListPage() {
  return <ProTable rowKey="id" request={getIncidents} columns={[{ title: '事件编号', dataIndex: 'code' }, { title: '标题', dataIndex: 'title' }, { title: '等级', dataIndex: 'level', render: (_, row: any) => <RiskTag level={row.level} /> }, { title: '状态', dataIndex: 'status', render: (_, row: any) => <StatusTag status={row.status} /> }, { title: '操作', render: (_, row: any) => <Button type="link" onClick={() => history.push(`/incident/${row.id}`)}>查看</Button> }]} />;
}
