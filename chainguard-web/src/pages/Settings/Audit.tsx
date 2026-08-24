import { useAccess } from '@/runtime';
import { PageContainer, ProTable } from '@/components/pro';
import { Button, Descriptions, Drawer, Tag } from 'antd';
import { DownloadOutlined, EyeOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { ROLE_LABELS } from '@/constants/status';
import { getAuditLogs } from '@/services/settings';

export default function Audit() {
  const access = useAccess();
  const [current, setCurrent] = useState<API.AuditLog>();
  return (
    <PageContainer title="审计日志" subTitle="关键业务动作、权限与敏感字段访问均留痕" extra={access.canExportAudit && <Button icon={<DownloadOutlined />}>导出审计日志</Button>}>
      <ProTable<API.AuditLog> rowKey="id" request={getAuditLogs} columns={[
        { title: '时间', dataIndex: 'time', valueType: 'dateTime' }, { title: '操作人', dataIndex: 'userName' },
        { title: '角色', dataIndex: 'roleCode', valueType: 'select', valueEnum: Object.fromEntries(Object.entries(ROLE_LABELS).map(([key, text]) => [key, { text }])), render: (_, row) => <Tag>{ROLE_LABELS[row.roleCode]}</Tag> },
        { title: '动作', dataIndex: 'action' }, { title: '对象类型', dataIndex: 'targetType' }, { title: '对象', dataIndex: 'targetName' }, { title: 'IP', dataIndex: 'ip', search: false },
        { title: '详情', valueType: 'option', render: (_, row) => <Button type="link" icon={<EyeOutlined />} onClick={() => setCurrent(row)}>查看</Button> }
      ]} />
      <Drawer title="审计详情" open={!!current} width={520} onClose={() => setCurrent(undefined)}>
        {current && <Descriptions bordered column={1} items={[
          { key: 'time', label: '时间', children: current.time }, { key: 'user', label: '操作人', children: `${current.userName}（${ROLE_LABELS[current.roleCode]}）` },
          { key: 'action', label: '动作', children: current.action }, { key: 'target', label: '对象', children: `${current.targetType} / ${current.targetName}` },
          { key: 'ip', label: 'IP', children: current.ip }, { key: 'detail', label: '变更详情', children: <pre>{JSON.stringify(current.detail, null, 2)}</pre> }
        ]} />}
      </Drawer>
    </PageContainer>
  );
}
