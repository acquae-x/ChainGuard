import { useAccess } from '@umijs/max';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Button, Drawer, Form, Input, Space, message } from 'antd';
import { DownloadOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useRef, useState } from 'react';
import { ObjectPeek, SensitiveField, StatusTag } from '@/components';
import { createRecord, getDataTable } from '@/services/data';
import { formatSupportHours } from './presentation';

type DataType = 'material' | 'supplier' | 'customer' | 'order' | 'inventory';

const config: Record<DataType, { title: string; key: string; name: string; columns: any[] }> = {
  material: { title: '物料管理', key: 'id', name: 'name', columns: [{ title: '物料编号', dataIndex: 'id' }, { title: '物料名称', dataIndex: 'name' }, { title: '分类', dataIndex: 'category' }, { title: '库存', dataIndex: 'stock' }, { title: '安全库存', dataIndex: 'safety' }, { title: '成本', dataIndex: 'cost', render: (_: any, row: any) => <SensitiveField field="cost" value={`¥${row.cost}`} /> }] },
  supplier: { title: '供应商管理', key: 'id', name: 'name', columns: [{ title: '供应商编号', dataIndex: 'id' }, { title: '供应商', dataIndex: 'name' }, { title: '状态', dataIndex: 'status' }, { title: '交期', dataIndex: 'leadTime', renderText: (value: number) => `${value} 天` }, { title: '采购价', dataIndex: 'supplierPrice', render: (_: any, row: any) => <SensitiveField field="supplierPrice" value={`¥${row.supplierPrice}`} /> }] },
  customer: { title: '客户管理', key: 'id', name: 'name', columns: [{ title: '客户编号', dataIndex: 'id' }, { title: '客户名称', dataIndex: 'name' }, { title: '客户等级', dataIndex: 'customerLevel', render: (_: any, row: any) => <SensitiveField field="customerLevel" value={row.customerLevel} /> }, { title: '合同', dataIndex: 'contract', render: (_: any, row: any) => <SensitiveField field="contract" value={row.contract} /> }, { title: '负责人', dataIndex: 'owner' }] },
  order: { title: '订单管理', key: 'id', name: 'orderNo', columns: [{ title: '订单号', dataIndex: 'orderNo' }, { title: '客户', dataIndex: 'customer' }, { title: '交付日', dataIndex: 'dueAt', valueType: 'date' }, { title: '金额', dataIndex: 'amount', render: (_: any, row: any) => <SensitiveField field="contract" value={`¥${row.amount.toLocaleString()}`} /> }, { title: '利润', dataIndex: 'profit', render: (_: any, row: any) => <SensitiveField field="profit" value={`¥${row.profit.toLocaleString()}`} /> }, { title: '状态', dataIndex: 'status', render: (_: any, row: any) => <StatusTag status={row.status} /> }] },
  inventory: { title: '库存管理', key: 'id', name: 'material', columns: [{ title: '库存编号', dataIndex: 'id' }, { title: '仓库', dataIndex: 'warehouse' }, { title: '物料', dataIndex: 'material' }, { title: '可用数量', dataIndex: 'quantity' }, { title: '可支撑', dataIndex: 'supportHours', renderText: formatSupportHours }, { title: '状态', dataIndex: 'status', render: (_: any, row: any) => <StatusTag status={row.status} /> }] }
};

export default function TablePage({ type }: { type: DataType }) {
  const access = useAccess();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const actionRef = useRef<any>();
  const meta = config[type];
  return (
    <PageContainer title={meta.title} extra={<Space>{access.canImport && <Button icon={<UploadOutlined />} href="/data/import">导入</Button>}{access.canExportData && <Button icon={<DownloadOutlined />}>导出</Button>}{!access.readonly && <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建</Button>}</Space>}>
      <ProTable<any>
        actionRef={actionRef}
        rowKey={meta.key}
        request={() => getDataTable(type)}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        // 原先这里还有一列"质量评分"，render 忽略行数据恒定输出 88——后端
        // /data/{type} 压根没有 qualityScore 字段。整列删除，不做假打分。
        columns={[...meta.columns, { title: '操作', valueType: 'option', render: (_: any, row: any) => <ObjectPeek type={meta.title.replace('管理', '')} name={row[meta.name]} data={row} /> }]}
      />
      <Drawer title={`新建${meta.title.replace('管理', '')}`} open={open} onClose={() => setOpen(false)} width={440}>
        <Form form={form} layout="vertical" onFinish={async (values) => { await createRecord(type, values); message.success('已保存并写入审计日志'); form.resetFields(); setOpen(false); actionRef.current?.reload(); }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="remark" label="备注"><Input.TextArea rows={4} /></Form.Item>
          <Button block type="primary" htmlType="submit">保存</Button>
        </Form>
      </Drawer>
    </PageContainer>
  );
}
