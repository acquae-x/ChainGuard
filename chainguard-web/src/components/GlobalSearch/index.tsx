import { history } from '@umijs/max';
import { AutoComplete, Descriptions, Drawer, Input } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { materials, orders, suppliers } from '@/services/mockData';
import { workflowStore } from '@/services/workflowStore';
import SensitiveField from '@/components/SensitiveField';

type SearchObject = { type: 'material' | 'supplier' | 'order'; title: string; data: Record<string, any> };

export default function GlobalSearch() {
  const [options, setOptions] = useState<any[]>([]);
  const [selected, setSelected] = useState<SearchObject>();
  const buildOptions = (keyword: string) => {
    const text = keyword.trim().toLowerCase();
    if (!text) return [];
    // 只按业务标识字段匹配（名称/编号/客户等），避免关键词误命中成本等数值字段
    const group = (label: string, rows: any[], type: string, title: (row: any) => string, fields: string[]) => ({ label, options: rows.filter((row) => fields.some((field) => String(row[field] ?? '').toLowerCase().includes(text))).slice(0, 5).map((row) => ({ value: `${type}:${row.id}`, label: title(row) })) });
    return [group('物料', materials, 'material', (row) => `${row.name}（${row.id}）`, ['name', 'id', 'category']), group('供应商', suppliers, 'supplier', (row) => row.name, ['name', 'id']), group('订单', orders, 'order', (row) => `${row.orderNo} / ${row.customer}`, ['orderNo', 'customer', 'id']), group('事件', workflowStore.listIncidents(), 'incident', (row) => `${row.code} ${row.title}`, ['code', 'title', 'id'])].filter((item) => item.options.length);
  };
  const choose = (value: string) => {
    const [type, id] = value.split(':');
    if (type === 'incident') { history.push(`/incident/${id}`); return; }
    const rows = type === 'material' ? materials : type === 'supplier' ? suppliers : orders;
    const data = rows.find((item) => item.id === id) as Record<string, any> | undefined;
    if (data) setSelected({ type: type as SearchObject['type'], title: type === 'order' ? data.orderNo : data.name, data });
  };
  const renderValue = (key: string, value: any) => ['cost'].includes(key) ? <SensitiveField field="cost" value={`¥${value}`} /> : key === 'supplierPrice' ? <SensitiveField field="supplierPrice" value={`¥${value}`} /> : ['amount'].includes(key) ? <SensitiveField field="contract" value={`¥${Number(value).toLocaleString()}`} /> : key === 'profit' ? <SensitiveField field="profit" value={`¥${Number(value).toLocaleString()}`} /> : String(value);
  return <><AutoComplete style={{ width: 280, maxWidth: '32vw' }} options={options} onSearch={(value) => setOptions(buildOptions(value))} onSelect={choose}><Input prefix={<SearchOutlined />} placeholder="搜物料/供应商/订单/事件编号" /></AutoComplete><Drawer title={`${selected?.title || ''} 概要`} open={!!selected} width={420} onClose={() => setSelected(undefined)}>{selected && <Descriptions bordered column={1} size="small" items={Object.entries(selected.data).map(([key, value]) => ({ key, label: key, children: renderValue(key, value) }))} />}</Drawer></>;
}
