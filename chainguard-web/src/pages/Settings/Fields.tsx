import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Button, Card, Drawer, Flex, Form, Input, Select, Space, Switch, Tag, message } from 'antd';
import { LockOutlined, PlusOutlined, StopOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { DynamicField } from '@/components';
import type { DynamicSchema } from '@/components/DynamicField';
import { disableField, getFieldSchema, saveField } from '@/services/settings';

const systemFields = [{ name: 'name', label: '名称', type: 'text', system: true }, { name: 'code', label: '编号', type: 'text', system: true }];

export default function Fields() {
  const [objectType, setObjectType] = useState('supplier');
  const [fields, setFields] = useState<any[]>(systemFields);
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<DynamicSchema>({ name: 'customField', label: '自定义字段', type: 'text' });
  useEffect(() => { getFieldSchema(objectType).then((items) => setFields([...systemFields, ...items])); }, [objectType]);
  return <PageContainer title="自定义字段" subTitle={`当前 ${fields.filter((item) => !item.system).length}/20 个`} extra={<Space><Select value={objectType} onChange={setObjectType} options={[{ label: '物料', value: 'material' }, { label: '供应商', value: 'supplier' }, { label: '客户', value: 'customer' }, { label: '订单', value: 'order' }]} /><Button type="primary" icon={<PlusOutlined />} disabled={fields.length - systemFields.length >= 20} onClick={() => setOpen(true)}>新建字段</Button></Space>}>
    <ProTable search={false} rowKey="name" dataSource={fields} columns={[{ title: '字段名称', dataIndex: 'label' }, { title: '字段代码', dataIndex: 'name' }, { title: '类型', dataIndex: 'type', render: (_, row) => <Tag>{row.type}</Tag> }, { title: '属性', render: (_, row) => row.system ? <Tag icon={<LockOutlined />}>系统字段</Tag> : <Space>{row.required && <Tag>必填</Tag>}{row.riskFactor && <Tag color="orange">参与风险计算</Tag>}</Space> }, { title: '操作', valueType: 'option', render: (_, row) => row.system ? '-' : <Button type="link" danger icon={<StopOutlined />} onClick={async () => { await disableField(row.name); message.success('字段已停用，历史数据保留'); }}>停用</Button> }]} />
    <Drawer width={720} title="新建自定义字段" open={open} onClose={() => setOpen(false)}><Flex gap={24} align="start"><Form style={{ flex: 1 }} layout="vertical" initialValues={{ type: 'text' }} onValuesChange={(_, values) => setPreview({ name: 'customField', label: values.label || '自定义字段', type: values.type || 'text', required: values.required })} onFinish={async (values) => { await saveField(values); message.success('字段已保存并记录审计'); setOpen(false); }}><Form.Item name="label" label="字段名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="type" label="字段类型"><Select options={[{ label: '单行文本', value: 'text' }, { label: '数字', value: 'number' }, { label: '日期', value: 'date' }, { label: '单选', value: 'select' }, { label: '多选', value: 'multiSelect' }, { label: '金额', value: 'money' }]} /></Form.Item><Form.Item name="required" label="是否必填" valuePropName="checked"><Switch /></Form.Item><Form.Item name="risk" label="参与风险计算" valuePropName="checked"><Switch /></Form.Item><Form.Item name="list" label="列表默认显示" valuePropName="checked"><Switch /></Form.Item><Form.Item name="sensitive" label="敏感字段" valuePropName="checked"><Switch /></Form.Item><Button block type="primary" htmlType="submit">保存字段</Button></Form><Card title="表单预览" style={{ flex: 1 }}><Form layout="vertical"><DynamicField schema={preview} /></Form></Card></Flex></Drawer>
  </PageContainer>;
}
