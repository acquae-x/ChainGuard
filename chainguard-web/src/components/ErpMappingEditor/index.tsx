// ERP 源字段 → C2 业务实体字段映射编辑器（Phase 5B 收尾批）。
// 保存的映射由下一次 ERP 同步实际消费；本组件不做任何本地兜底映射。
import { Alert, App, Button, Card, Collapse, Descriptions, Drawer, Input, Select, Space, Switch, Table, Tag, Tooltip } from 'antd';
import { DeleteOutlined, PlusOutlined, ReloadOutlined, SafetyOutlined } from '@ant-design/icons';
import { useEffect, useMemo, useState } from 'react';
import {
  getErpMapping,
  getErpMappingSourceFields,
  resetErpMapping,
  saveErpMapping,
  validateErpMapping,
  type ErpMappingResource,
  type ErpMappingRow,
  type ErpMappingView,
} from '@/services/settings';

// 行在编辑期间源/目标字段都可能被改写，用稳定的客户端 key 做 rowKey。
type DraftRow = ErpMappingRow & { key: string };
type RowsByResource = Record<string, DraftRow[]>;
type UnknownByResource = Record<string, 'extra' | 'reject'>;

const UNKNOWN_LABEL: Record<string, string> = {
  extra: '进入 extra（保留原值）',
  reject: '整行拒绝',
};

function fromView(view: ErpMappingView): { rows: RowsByResource; unknown: UnknownByResource } {
  const rows: RowsByResource = {};
  const unknown: UnknownByResource = {};
  view.resources.forEach((resource) => {
    rows[resource.resourceType] = resource.rows.map((row, index) => ({ ...row, key: `${resource.resourceType}-${index}` }));
    unknown[resource.resourceType] = resource.unknownColumns;
  });
  return { rows, unknown };
}

// 只重建 fields / converts / required / unknown_columns，其余契约字段（业务键、聚合口径、
// 敏感列、禁止列）保持后端下发的原值，避免编辑器成为第二套字段口径。
function buildSpec(view: ErpMappingView, rows: RowsByResource, unknown: UnknownByResource) {
  const spec = JSON.parse(JSON.stringify(view.spec || {}));
  Object.entries(rows).forEach(([resourceType, list]) => {
    const rule = spec?.resources?.[resourceType];
    if (!rule) return;
    const base = view.spec?.resources?.[resourceType] || {};
    const fields: Record<string, string> = {};
    const converts: Record<string, any> = {};
    const required: string[] = [];
    list.forEach((row) => {
      const source = (row.sourceField || '').trim();
      const target = (row.targetField || '').trim();
      if (!source || !target) return;
      if (row.kind === 'convert') {
        converts[target] = { ...(base.converts?.[target] || {}), from: source, type: row.convertType || 'string' };
      } else {
        fields[source] = target;
      }
      if (row.required && !required.includes(source)) required.push(source);
    });
    rule.fields = fields;
    rule.converts = converts;
    rule.required = required;
    rule.unknown_columns = unknown[resourceType] || rule.unknown_columns;
  });
  return spec;
}

export default function ErpMappingEditor({ onSaved }: { onSaved?: () => void }) {
  const { message, modal } = App.useApp();
  const [view, setView] = useState<ErpMappingView>();
  const [rows, setRows] = useState<RowsByResource>({});
  const [unknown, setUnknown] = useState<UnknownByResource>({});
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [verdict, setVerdict] = useState<{ valid: boolean; errors: string[]; warnings: string[] }>();
  const [catalog, setCatalog] = useState<{ resource: string; fields: any[]; sampledRows: number }>();
  // 受控展开：面板在数据到达前就已挂载，defaultActiveKey 不会再生效。
  const [activeKeys, setActiveKeys] = useState<string[]>([]);

  const load = async () => {
    setLoading(true);
    try {
      const next = await getErpMapping();
      setView(next);
      const initial = fromView(next);
      setRows(initial.rows);
      setUnknown(initial.unknown);
      setActiveKeys((current) => (current.length ? current : next.resources.slice(0, 1).map((item) => item.resourceType)));
      setDirty(false);
      setVerdict(undefined);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const draftSpec = useMemo(() => (view ? buildSpec(view, rows, unknown) : {}), [view, rows, unknown]);

  const patchRow = (resourceType: string, index: number, patch: Partial<ErpMappingRow>) => {
    setRows((current) => ({
      ...current,
      [resourceType]: (current[resourceType] || []).map((row, position) => (position === index ? { ...row, ...patch } : row)),
    }));
    setDirty(true);
    setVerdict(undefined);
  };

  const addRow = (resourceType: string) => {
    setRows((current) => ({
      ...current,
      [resourceType]: [...(current[resourceType] || []), {
        key: `${resourceType}-new-${Date.now()}`,
        sourceField: '', targetField: '', kind: 'field', convertType: null,
        required: false, businessKey: false, sensitive: false,
      }],
    }));
    setDirty(true);
    setVerdict(undefined);
  };

  const removeRow = (resourceType: string, index: number) => {
    setRows((current) => ({ ...current, [resourceType]: (current[resourceType] || []).filter((_, position) => position !== index) }));
    setDirty(true);
    setVerdict(undefined);
  };

  const validate = async () => {
    setBusy(true);
    try {
      const result = await validateErpMapping(draftSpec);
      setVerdict(result);
      if (result.valid) message.success(result.warnings.length ? '结构校验通过，但存在危险映射提示。' : '映射校验通过。');
      else message.error('映射校验未通过，请先修复错误。');
    } finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true);
    try {
      const result = await validateErpMapping(draftSpec);
      setVerdict(result);
      if (!result.valid) { message.error('映射校验未通过，未保存。'); return; }
      const confirmed = !result.warnings.length || await new Promise<boolean>((resolve) => {
        modal.confirm({
          title: '存在危险映射，确认保存？',
          content: <ul style={{ paddingLeft: 18, margin: 0 }}>{result.warnings.map((item) => <li key={item}>{item}</li>)}</ul>,
          okText: '确认保存', cancelText: '返回修改',
          onOk: () => resolve(true), onCancel: () => resolve(false),
        });
      });
      if (!confirmed) return;
      const saved = await saveErpMapping(draftSpec);
      setView(saved);
      const initial = fromView(saved);
      setRows(initial.rows); setUnknown(initial.unknown); setDirty(false);
      message.success(`映射已保存为 v${saved.version}，下一次 ERP 同步开始生效。`);
      onSaved?.();
    } finally { setBusy(false); }
  };

  const reset = async () => {
    modal.confirm({
      title: '恢复内置映射？',
      content: '将停用本租户的自定义映射，下一次 ERP 同步改用随产品交付的 config/erp_mapping.yaml。',
      okText: '恢复内置映射', cancelText: '取消',
      onOk: async () => {
        const restored = await resetErpMapping();
        setView(restored);
        const initial = fromView(restored);
        setRows(initial.rows); setUnknown(initial.unknown); setDirty(false); setVerdict(undefined);
        message.success('已恢复内置映射。');
        onSaved?.();
      },
    });
  };

  const openCatalog = async (resourceType: string) => {
    try {
      setCatalog(await getErpMappingSourceFields(resourceType));
    } catch {
      // 失败原因由请求层统一提示（未保存连接 / 未通过连通测试 / ERP 不可用），此处不静默兜底。
    }
  };

  const columnsFor = (resource: ErpMappingResource) => [
    {
      title: '源字段', dataIndex: 'sourceField', width: 200,
      render: (value: string, _row: DraftRow, index: number) => (
        <Input size="small" value={value} placeholder="ERP 源列名"
          aria-label={`${resource.label} 第 ${index + 1} 行源字段`}
          onChange={(event) => patchRow(resource.resourceType, index, { sourceField: event.target.value })} />
      ),
    },
    {
      title: '目标字段（C2 实体列）', dataIndex: 'targetField', width: 220,
      render: (value: string, row: DraftRow, index: number) => (
        <Space size={4}>
          <Select size="small" style={{ width: 160 }} value={value || undefined} showSearch placeholder="选择目标列"
            options={resource.targetColumns.map((column) => ({ value: column.name, label: `${column.name}（${column.type}）` }))}
            onChange={(next) => patchRow(resource.resourceType, index, { targetField: next })} />
          {row.businessKey ? <Tag color="blue">业务键</Tag> : null}
        </Space>
      ),
    },
    {
      title: '必填', dataIndex: 'required', width: 80, align: 'center' as const,
      render: (value: boolean, _row: DraftRow, index: number) => (
        <Switch size="small" checked={value} onChange={(next) => patchRow(resource.resourceType, index, { required: next })} />
      ),
    },
    {
      title: '转换规则', dataIndex: 'convertType', width: 170,
      render: (value: string | null, row: DraftRow, index: number) => (
        <Select size="small" style={{ width: 150 }} value={row.kind === 'convert' ? value || 'string' : '__direct__'}
          options={[{ value: '__direct__', label: '直存（不转换）' },
            ...(view?.conversionTypes || []).map((type) => ({ value: type, label: type }))]}
          onChange={(next) => patchRow(resource.resourceType, index, next === '__direct__'
            ? { kind: 'field', convertType: null }
            : { kind: 'convert', convertType: next })} />
      ),
    },
    {
      title: '', dataIndex: 'operation', width: 60, align: 'center' as const,
      render: (_value: unknown, row: DraftRow, index: number) => (
        <Space size={4}>
          {row.sensitive ? <Tooltip title="命中敏感列，同步时整行会被拒绝"><SafetyOutlined style={{ color: '#cf1322' }} /></Tooltip> : null}
          <Button size="small" type="text" danger icon={<DeleteOutlined />} aria-label="删除映射行"
            onClick={() => removeRow(resource.resourceType, index)} />
        </Space>
      ),
    },
  ];

  const provenance = view?.source === 'tenant'
    ? `租户自定义 v${view?.version}`
    : '随产品交付的内置映射文件';

  return (
    <Card
      title="ERP 字段映射"
      loading={loading}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} disabled={busy}>重新加载</Button>
          <Button onClick={validate} loading={busy}>校验映射</Button>
          <Button danger onClick={reset} disabled={busy || view?.source !== 'tenant'}>恢复内置映射</Button>
          <Button type="primary" onClick={save} loading={busy} disabled={!dirty}>保存映射</Button>
        </Space>
      }
    >
      <Descriptions size="small" column={{ xs: 1, md: 2, xl: 4 }} style={{ marginBottom: 12 }} items={[
        { key: 'source', label: '当前生效映射', children: <Tag color={view?.source === 'tenant' ? 'blue' : 'default'}>{provenance}</Tag> },
        { key: 'time', label: '最后修改时间', children: view?.updatedAt ? new Date(view.updatedAt).toLocaleString() : '—（未修改过）' },
        { key: 'by', label: '最后修改人', children: view?.updatedBy || '—' },
        { key: 'file', label: '内置映射文件', children: view?.filePath },
      ]} />

      {view && !view.usable ? (
        <Alert showIcon type="error" style={{ marginBottom: 12 }} message="当前映射不可用，ERP 同步已被阻止"
          description={<>
            <div>{view.degradeReason}</div>
            <ul style={{ paddingLeft: 18, marginBottom: 0 }}>{view.errors.slice(0, 8).map((item) => <li key={item}>{item}</li>)}</ul>
            <div>系统不会回退到硬编码映射；请修复后保存，或恢复内置映射。</div>
          </>} />
      ) : null}

      {verdict && verdict.errors.length ? (
        <Alert showIcon type="error" style={{ marginBottom: 12 }} message="映射校验未通过（未保存）"
          description={<ul style={{ paddingLeft: 18, marginBottom: 0 }}>{verdict.errors.map((item) => <li key={item}>{item}</li>)}</ul>} />
      ) : null}

      {(verdict?.warnings.length || view?.warnings.length) ? (
        <Alert showIcon type="warning" style={{ marginBottom: 12 }} message="危险映射提示"
          description={<ul style={{ paddingLeft: 18, marginBottom: 0 }}>
            {(verdict?.warnings || view?.warnings || []).map((item) => <li key={item}>{item}</li>)}
          </ul>} />
      ) : null}

      {dirty ? <Alert showIcon type="info" style={{ marginBottom: 12 }} message="映射已修改但尚未保存；未保存的修改不会影响任何同步。" /> : null}

      <Collapse
        accordion={false}
        activeKey={activeKeys}
        onChange={(keys) => setActiveKeys(Array.isArray(keys) ? keys : [keys])}
        items={(view?.resources || []).map((resource) => ({
          key: resource.resourceType,
          label: (
            <Space wrap>
              <strong>{resource.label}</strong>
              <Tag>{resource.sourceTable} → {resource.targetTable}</Tag>
              <Tag color="default">{resource.aggregation}</Tag>
              <Tag color={unknown[resource.resourceType] === 'reject' ? 'orange' : 'green'}>
                未声明列：{UNKNOWN_LABEL[unknown[resource.resourceType]] || unknown[resource.resourceType]}
              </Tag>
              {resource.forbiddenColumns.length ? <Tag color="red">禁止列：{resource.forbiddenColumns.join(', ')}</Tag> : null}
            </Space>
          ),
          children: (
            <>
              <Space wrap style={{ marginBottom: 8 }}>
                <span>未声明源列处理：</span>
                <Select size="small" style={{ width: 200 }} value={unknown[resource.resourceType]}
                  aria-label={`${resource.label} 未声明列处理`}
                  options={[{ value: 'extra', label: UNKNOWN_LABEL.extra }, { value: 'reject', label: UNKNOWN_LABEL.reject }]}
                  onChange={(next) => { setUnknown((current) => ({ ...current, [resource.resourceType]: next })); setDirty(true); setVerdict(undefined); }} />
                <Button size="small" icon={<PlusOutlined />} onClick={() => addRow(resource.resourceType)}>新增字段映射</Button>
                <Button size="small" onClick={() => openCatalog(resource.resourceType)}>读取 ERP 源字段</Button>
              </Space>
              <Table<DraftRow>
                size="small" pagination={false} rowKey="key"
                dataSource={rows[resource.resourceType] || []} columns={columnsFor(resource)} scroll={{ x: 'max-content' }} />
            </>
          ),
        }))}
      />

      <Drawer title={`ERP 源字段目录：${catalog?.resource || ''}`} width={420} open={Boolean(catalog)} onClose={() => setCatalog(undefined)}>
        <Alert showIcon type="info" style={{ marginBottom: 12 }} message={`采样 ${catalog?.sampledRows || 0} 行真实 ERP 数据得到的源字段`} />
        <Table size="small" pagination={false} rowKey="name" dataSource={catalog?.fields || []} columns={[
          { title: '源字段', dataIndex: 'name' },
          { title: '样例值', dataIndex: 'sample', render: (value: string | null, row: any) => row.sensitive ? <Tag color="red">敏感列（不展示）</Tag> : value ?? '-' },
          { title: '已映射', dataIndex: 'mapped', render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '已映射' : '未映射'}</Tag> },
        ]} />
      </Drawer>
    </Card>
  );
}
