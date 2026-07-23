import { EyeOutlined } from '@ant-design/icons';
import { Button, Descriptions, Drawer, Space, Table, Tag, Typography } from 'antd';
import { isValidElement, useState } from 'react';
import type { ReactNode } from 'react';

type SupplyRelation = {
  supplierMaterialId?: string;
  materialId?: string;
  materialName?: string;
  supplierRank?: number | null;
  leadTimeHours?: number | null;
  supplierPrice?: number | null;
  availableEmergencyQty?: number | null;
  qualified?: boolean;
  isDefault?: boolean;
};

function displayValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return '—';
  if (isValidElement(value)) return value;
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string' || typeof value === 'number') return value;
  if (Array.isArray(value)) return `${value.length} 项`;
  return <Typography.Text type="secondary">结构化数据</Typography.Text>;
}

export default function ObjectPeek({ type, name, data }: { type: string; name: string; data?: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const content = data || { 编号: `${type}-${name}`, 状态: <Tag color="green">正常</Tag>, 负责人: '系统示例' };
  const relations = Array.isArray(content.relations) ? content.relations as SupplyRelation[] : [];
  const summary = Object.entries(content).filter(([key]) => key !== 'relations');
  return (
    <>
      <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => setOpen(true)}>{name}</Button>
      <Drawer title={`${type}概要`} width="min(760px, 100vw)" open={open} onClose={() => setOpen(false)}>
        <Descriptions column={1} bordered size="small">
          {summary.map(([key, value]) => <Descriptions.Item key={key} label={key}>{displayValue(value)}</Descriptions.Item>)}
        </Descriptions>
        {relations.length > 0 && <section aria-label="供货关系明细" style={{ marginTop: 20 }}>
          <Typography.Title level={5}>供货关系明细</Typography.Title>
          <Table<SupplyRelation>
            size="small"
            pagination={false}
            rowKey={(row) => row.supplierMaterialId || `${row.materialId}-${row.supplierRank}`}
            dataSource={relations}
            scroll={{ x: 760 }}
            columns={[
              { title: '物料', key: 'material', fixed: 'left', width: 150, render: (_, row) => row.materialName || row.materialId || '—' },
              { title: '排名', dataIndex: 'supplierRank', width: 70, render: displayValue },
              { title: '交期', dataIndex: 'leadTimeHours', width: 90, render: (value) => value == null ? '—' : `${value} 小时` },
              { title: '采购价', dataIndex: 'supplierPrice', width: 100, render: (value) => value == null ? '—' : `¥${value}` },
              { title: '可用应急量', dataIndex: 'availableEmergencyQty', width: 110, render: displayValue },
              { title: '合格', dataIndex: 'qualified', width: 70, render: (value) => <Tag color={value ? 'green' : 'red'}>{value ? '是' : '否'}</Tag> },
              { title: '关系', dataIndex: 'isDefault', width: 90, render: (value) => value ? <Tag color="blue">默认主供</Tag> : '备选' },
            ]}
          />
        </section>}
        <Space style={{ marginTop: 16 }}>
          <Button type="primary">查看完整详情</Button>
          <Button onClick={() => setOpen(false)}>关闭</Button>
        </Space>
      </Drawer>
    </>
  );
}
