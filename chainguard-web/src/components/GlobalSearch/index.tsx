import { history } from '@umijs/max';
import { AutoComplete, Descriptions, Drawer, Empty, Input, Spin } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useRef, useState } from 'react';
import { getDataTable } from '@/services/data';
import { getIncidents } from '@/services/incident';
import SensitiveField from '@/components/SensitiveField';

type SearchObject = { type: 'material' | 'supplier' | 'order'; title: string; data: Record<string, any> };
type Catalog = { materials: any[]; suppliers: any[]; orders: any[]; incidents: any[] };

const EMPTY_CATALOG: Catalog = { materials: [], suppliers: [], orders: [], incidents: [] };

/**
 * 全局搜索的数据一律来自 service 层（getDataTable / getIncidents），
 * 而 service 层由 dataMode.pick 统一门控：api 模式取后端真实数据，
 * mock 模式才取内置演练数据。
 *
 * 此处**不得**直接 import services/mockData——那样在 api 模式下会把演示物料、
 * 演示供应商当成本租户数据搜出来，与页面上其它列表的真实数据对不上。
 *
 * 后端 /data/{type} 不接受关键词参数且按资料类型做权限校验，因此这里首次搜索
 * 时一次性把可见资料取回来在前端过滤；某一类无权限（403）只丢掉该组，
 * 不影响其余分组——用 allSettled 而不是 all。
 */
export default function GlobalSearch() {
  const [options, setOptions] = useState<any[]>([]);
  const [selected, setSelected] = useState<SearchObject>();
  const [loading, setLoading] = useState(false);
  const catalogRef = useRef<Catalog | null>(null);

  async function loadCatalog(): Promise<Catalog> {
    if (catalogRef.current) return catalogRef.current;
    const [materials, suppliers, orders, incidents] = await Promise.allSettled([
      getDataTable('material'),
      getDataTable('supplier'),
      getDataTable('order'),
      getIncidents(),
    ]);
    const rows = (result: PromiseSettledResult<any>): any[] => {
      if (result.status !== 'fulfilled') return [];
      const value: any = result.value;
      return Array.isArray(value) ? value : (value?.data ?? []);
    };
    const catalog: Catalog = {
      materials: rows(materials),
      suppliers: rows(suppliers),
      orders: rows(orders),
      incidents: rows(incidents),
    };
    catalogRef.current = catalog;
    return catalog;
  }

  const search = async (keyword: string) => {
    const text = keyword.trim().toLowerCase();
    if (!text) { setOptions([]); return; }
    setLoading(true);
    let catalog = EMPTY_CATALOG;
    try {
      catalog = await loadCatalog();
    } catch {
      // 后端整体不可用时黄条已由 request.ts 触发，这里只是搜不出东西，不静默降级到假数据
      catalogRef.current = null;
    } finally {
      setLoading(false);
    }
    // 只按业务标识字段匹配（名称/编号/客户等），避免关键词误命中成本等数值字段
    const group = (label: string, list: any[], type: string, title: (row: any) => string, fields: string[]) => ({
      label,
      options: list
        .filter((row) => fields.some((field) => String(row[field] ?? '').toLowerCase().includes(text)))
        .slice(0, 5)
        .map((row) => ({ value: `${type}:${row.id}`, label: title(row) })),
    });
    setOptions([
      group('物料', catalog.materials, 'material', (row) => `${row.name}（${row.id}）`, ['name', 'id', 'category']),
      group('供应商', catalog.suppliers, 'supplier', (row) => row.name, ['name', 'id']),
      group('订单', catalog.orders, 'order', (row) => `${row.orderNo} / ${row.customer}`, ['orderNo', 'customer', 'id']),
      group('事件', catalog.incidents, 'incident', (row) => `${row.code} ${row.title}`, ['code', 'title', 'id']),
    ].filter((item) => item.options.length));
  };

  const choose = (value: string) => {
    const [type, id] = value.split(':');
    if (type === 'incident') { history.push(`/incident/${id}`); return; }
    const catalog = catalogRef.current ?? EMPTY_CATALOG;
    const list = type === 'material' ? catalog.materials : type === 'supplier' ? catalog.suppliers : catalog.orders;
    const data = list.find((item: any) => item.id === id) as Record<string, any> | undefined;
    if (data) setSelected({ type: type as SearchObject['type'], title: type === 'order' ? data.orderNo : data.name, data });
  };

  const renderValue = (key: string, value: any) => ['cost'].includes(key)
    ? <SensitiveField field="cost" value={`¥${value}`} />
    : key === 'supplierPrice' ? <SensitiveField field="supplierPrice" value={`¥${value}`} />
    : ['amount'].includes(key) ? <SensitiveField field="contract" value={`¥${Number(value).toLocaleString()}`} />
    : key === 'profit' ? <SensitiveField field="profit" value={`¥${Number(value).toLocaleString()}`} />
    : String(value);

  return <>
    <AutoComplete
      style={{ width: 280, maxWidth: '32vw' }}
      options={options}
      onSearch={search}
      onSelect={choose}
      notFoundContent={loading ? <Spin size="small" /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配结果" />}
    >
      <Input prefix={<SearchOutlined />} placeholder="搜物料/供应商/订单/事件编号" />
    </AutoComplete>
    <Drawer title={`${selected?.title || ''} 概要`} open={!!selected} width={420} onClose={() => setSelected(undefined)}>
      {selected && <Descriptions bordered column={1} size="small" items={Object.entries(selected.data).map(([key, value]) => ({ key, label: key, children: renderValue(key, value) }))} />}
    </Drawer>
  </>;
}
