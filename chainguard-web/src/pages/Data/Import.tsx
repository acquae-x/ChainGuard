import { history, useAccess, useLocation } from '@umijs/max';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Button, Grid, Popconfirm, Table, Tabs, Tag, Typography, message } from 'antd';
import { DownloadOutlined, RollbackOutlined } from '@ant-design/icons';
import { ImportWizard } from '@/components';
import { getImportHistory, rollback } from '@/services/data';
import type { ImportTableReport, NormalizedImportHistoryJob } from '@/services/importHistory';

const reportColumns = [
  { title: '资料表', key: 'table', render: (_: unknown, row: ImportTableReport) => row.label !== '-' ? row.label : row.table },
  { title: '源行', dataIndex: 'sourceRows' },
  { title: '成功', dataIndex: 'successRows' },
  { title: '拒绝', dataIndex: 'rejectedRows' },
  { title: '新增', dataIndex: 'inserted' },
  { title: '更新', dataIndex: 'updated' },
];

export default function DataImport() {
  const access = useAccess();
  const screens = Grid.useBreakpoint();
  const { search } = useLocation();
  const requestedTab = new URLSearchParams(search).get('tab');
  const tab = requestedTab === 'history' ? 'history' : 'wizard';
  return (
    <PageContainer title="数据导入" subTitle={screens.sm ? "支持混合文件夹 / ZIP、表格、文档图片和 ERP" : undefined}>
      {!screens.sm && <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>支持混合文件夹 / ZIP、表格、文档图片和 ERP</Typography.Text>}
      <Tabs activeKey={tab} onChange={(key) => history.push(`/data/import?tab=${key}`)} items={[
        { key: 'wizard', label: '导入向导', children: access.canImport ? <ImportWizard /> : <Tag>当前账号仅可查看导入历史</Tag> },
        { key: 'history', label: '导入历史', children: <ProTable<NormalizedImportHistoryJob>
          rowKey="id"
          search={false}
          request={async () => ({ ...(await getImportHistory()), success: true })}
          expandable={{
            rowExpandable: (row) => row.reports.length > 0,
            expandedRowRender: (row) => <Table<ImportTableReport>
              aria-label={`${row.id} 逐表导入报告`}
              rowKey={(report) => `${report.table}-${report.label}`}
              size="small"
              pagination={false}
              dataSource={row.reports}
              columns={reportColumns}
              scroll={{ x: 680 }}
            />,
          }}
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
