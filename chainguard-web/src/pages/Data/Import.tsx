import { history, useAccess } from '@umijs/max';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Button, Popconfirm, Tabs, Tag, message } from 'antd';
import { DownloadOutlined, RollbackOutlined } from '@ant-design/icons';
import { ImportWizard } from '@/components';
import { getImportHistory, rollback } from '@/services/data';

export default function DataImport() {
  const access = useAccess();
  const tab = new URLSearchParams(location.search).get('tab') || 'wizard';
  return (
    <PageContainer title="数据导入" subTitle="支持 Excel / CSV，先校验再落库">
      <Tabs activeKey={tab} onChange={(key) => history.replace(`/data/import?tab=${key}`)} items={[
        { key: 'wizard', label: '导入向导', children: access.canImport ? <ImportWizard /> : <Tag>当前账号仅可查看导入历史</Tag> },
        { key: 'history', label: '导入历史', children: <ProTable<any>
          rowKey="id"
          search={false}
          request={async () => ({ ...(await getImportHistory()), success: true })}
          columns={[
            { title: '批次', dataIndex: 'id' }, { title: '数据类型', dataIndex: 'type' },
            { title: '成功', dataIndex: 'success', render: (_, row) => <Tag color="green">{row.success}</Tag> },
            { title: '失败', dataIndex: 'failed', render: (_, row) => <Tag color="red">{row.failed}</Tag> },
            { title: '操作人', dataIndex: 'operator' }, { title: '时间', dataIndex: 'time' },
            { title: '操作', valueType: 'option', render: (_, row) => [<Button key="download" type="link" icon={<DownloadOutlined />}>错误报告</Button>, access.canImport && <Popconfirm key="rollback" title="确认回滚该批次？" onConfirm={async () => { await rollback(row.id); message.success('批次已回滚'); }}><Button type="link" danger icon={<RollbackOutlined />}>回滚</Button></Popconfirm>] }
          ]}
        /> }
      ]} />
    </PageContainer>
  );
}
