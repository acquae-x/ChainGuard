import { DatePicker, Form, Input, InputNumber, Select, Switch, Typography } from 'antd';

export type DynamicSchema = {
  name: string;
  label: string;
  type: 'text' | 'number' | 'date' | 'select' | 'multiSelect' | 'money' | 'boolean';
  required?: boolean;
  options?: { label: string; value: string }[];
};

export default function DynamicField({ schema, value, readonly = false }: { schema: DynamicSchema; value?: unknown; readonly?: boolean }) {
  if (readonly || value !== undefined) {
    return <Typography.Text>{Array.isArray(value) ? value.join('、') : String(value ?? '-')}</Typography.Text>;
  }
  const rules = schema.required ? [{ required: true, message: `请输入${schema.label}` }] : undefined;
  const common = { name: schema.name, label: schema.label, rules };

  if (schema.type === 'number' || schema.type === 'money') {
    return <Form.Item {...common}><InputNumber min={0} precision={schema.type === 'money' ? 2 : 0} style={{ width: '100%' }} prefix={schema.type === 'money' ? '¥' : undefined} /></Form.Item>;
  }
  if (schema.type === 'date') {
    return <Form.Item {...common}><DatePicker style={{ width: '100%' }} /></Form.Item>;
  }
  if (schema.type === 'select' || schema.type === 'multiSelect') {
    return <Form.Item {...common}><Select mode={schema.type === 'multiSelect' ? 'multiple' : undefined} options={schema.options || []} /></Form.Item>;
  }
  if (schema.type === 'boolean') {
    return <Form.Item {...common} valuePropName="checked"><Switch /></Form.Item>;
  }
  return <Form.Item {...common}><Input /></Form.Item>;
}
