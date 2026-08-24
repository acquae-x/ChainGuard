import { history, useAccess } from '@/runtime';
import { LightFilter, ProFormDateRangePicker, ProFormSelect, ProTable } from '@/components/pro';
import type { ProColumns } from '@/components/pro';
import { Button, Drawer, Form, Input, Modal, Progress, Space, Tag, message } from 'antd';
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ObjectPeek, RiskExplanationDrawer, RiskTag, StatusTag } from '@/components';
import { createIncidentFromRisks, getRisks, ignoreRisk, markRiskWatching } from '@/services/risk';

type RiskFilters = {
  level?: string;
  type?: string;
  status?: string;
  dateRange?: string[];
  material?: string;
  supplier?: string;
  orderNo?: string;
  warehouse?: string;
};

const filterLabels: Record<keyof RiskFilters, string> = {
  level: '等级', type: '类型', status: '状态', dateRange: '时间范围',
  material: '物料', supplier: '供应商', orderNo: '订单号', warehouse: '仓库',
};

export default function RiskListPage() {
  const access = useAccess();
  const [drawer, setDrawer] = useState<API.Risk>();
  const [explainRiskId, setExplainRiskId] = useState<string>();
  const [ignoreTarget, setIgnoreTarget] = useState<API.Risk>();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [filters, setFilters] = useState<RiskFilters>({});
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [ignoreForm] = Form.useForm();
  const [advancedForm] = Form.useForm();
  const actionRef = useRef<any>();

  useEffect(() => { actionRef.current?.reload(); }, [filters]);

  const columns: ProColumns<API.Risk>[] = [
    { title: '风险编号', dataIndex: 'code', copyable: true, width: 180, ellipsis: true },
    { title: '等级', dataIndex: 'level', width: 110, render: (_, row) => <RiskTag level={row.level} /> },
    { title: '类型', dataIndex: 'type', width: 100 },
    { title: '对象', dataIndex: 'objectName', width: 190, ellipsis: true, render: (_, row) => <ObjectPeek type={row.objectType} name={row.objectName} /> },
    { title: '风险指数', dataIndex: 'score', width: 150, render: (_, row) => <Progress percent={row.score} size="small" status={row.score > 85 ? 'exception' : 'active'} /> },
    { title: '触发规则', dataIndex: 'rule', width: 240, ellipsis: true },
    { title: '发现时间', dataIndex: 'foundAt', width: 180, valueType: 'dateTime' },
    { title: '状态', dataIndex: 'status', width: 110, render: (_, row) => <StatusTag status={row.status} /> },
    { title: '操作', valueType: 'option', width: 360, fixed: 'right', render: (_, row) => {
      // A03：解释入口只需 risk:view（列表可见即可解释），不新增权限码。
      const actions: ReactNode[] = [<Button key="explain" type="link" onClick={() => setExplainRiskId(row.id)}>风险解释</Button>];
      if (access.canCreateIncident) actions.push(<Button key="create" type="link" onClick={() => setDrawer(row)}>创建应急事件</Button>);
      if (access.canManageRisk) actions.push(
        <Button key="watch" type="link" onClick={async () => { await markRiskWatching(row.id); actionRef.current?.reload(); message.success('已标记观察'); }}>标记观察</Button>,
        <Button key="ignore" type="link" danger onClick={() => setIgnoreTarget(row)}>忽略</Button>,
      );
      if (row.incidentId) actions.push(<Button key="view" type="link" onClick={() => history.push(`/incident/${row.incidentId}?risk=${row.id}`)}>查看关联事件</Button>);
      return actions;
    } },
  ];

  const removeFilter = (key: keyof RiskFilters) => setFilters((current) => {
    const next = { ...current };
    delete next[key];
    advancedForm.setFieldsValue({ [key]: undefined });
    return next;
  });

  return <>
    <LightFilter<RiskFilters>
      key={JSON.stringify(filters)}
      initialValues={filters}
      onValuesChange={(_, values) => setFilters((current) => ({ ...current, ...values }))}
    >
      <ProFormSelect name="level" label="等级" options={[{ value: 'high', label: '高' }, { value: 'medium', label: '中' }, { value: 'low', label: '低' }]} />
      <ProFormSelect name="type" label="类型" options={['供应', '物流', '需求', '质量', '库存'].map((value) => ({ value, label: value }))} />
      <ProFormSelect name="status" label="状态" options={[{ value: 'new', label: '新发现' }, { value: 'watching', label: '观察中' }, { value: 'incident_created', label: '已建事件' }, { value: 'resolved', label: '已消除' }, { value: 'ignored', label: '已忽略' }]} />
      <ProFormDateRangePicker name="dateRange" label="时间范围" />
    </LightFilter>
    <Space wrap style={{ margin: '12px 0' }}>
      <Button onClick={() => setAdvancedOpen(true)}>高级筛选</Button>
      {(Object.entries(filters) as [keyof RiskFilters, any][]).filter(([, value]) => value && (!Array.isArray(value) || value.length)).map(([key, value]) => (
        <Tag key={key} closable onClose={() => removeFilter(key)}>{filterLabels[key]}：{Array.isArray(value) ? value.join(' ~ ') : value}</Tag>
      ))}
    </Space>
    <ProTable<API.Risk>
      actionRef={actionRef}
      rowKey="id"
      columns={columns}
      scroll={{ x: 1620 }}
      tableLayout="fixed"
      request={async (params) => {
        const query = new URLSearchParams();
        Object.entries(filters).forEach(([key, value]) => value && query.set(key, Array.isArray(value) ? value.join(',') : String(value)));
        // 分页状态也写入 URL，保证浏览器回退/刷新后可恢复（05 文档第 3 节）
        if (params.current && params.current > 1) query.set('current', String(params.current));
        if (params.pageSize && params.pageSize !== 10) query.set('pageSize', String(params.pageSize));
        const nextSearch = query.toString() ? `?${query.toString()}` : '';
        if (history.location.search !== nextSearch) history.replace(`${history.location.pathname}${nextSearch}`);
        return getRisks({ ...params, ...filters });
      }}
      search={false}
      pagination={{ pageSize: 10 }}
      options={{ density: true, setting: true }}
      rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
      tableAlertOptionRender={() => access.canCreateIncident ? <Button disabled={!selectedRowKeys.length} onClick={async () => {
        const created = await createIncidentFromRisks(selectedRowKeys.map(String));
        history.push(`/incident/${created.id}`);
      }}>合并创建一个事件</Button> : null}
    />
    <RiskExplanationDrawer riskId={explainRiskId} open={!!explainRiskId} onClose={() => setExplainRiskId(undefined)} />
    <Drawer title="高级筛选" width={420} open={advancedOpen} onClose={() => setAdvancedOpen(false)}>
      <Form form={advancedForm} layout="vertical" initialValues={filters} onFinish={(values) => { setFilters((current) => ({ ...current, ...values })); setAdvancedOpen(false); }}>
        <Form.Item name="material" label="物料"><Input allowClear /></Form.Item>
        <Form.Item name="supplier" label="供应商"><Input allowClear /></Form.Item>
        <Form.Item name="orderNo" label="订单号"><Input allowClear /></Form.Item>
        <Form.Item name="warehouse" label="仓库"><Input allowClear /></Form.Item>
        <Space><Button onClick={() => { advancedForm.resetFields(); setFilters({}); }}>重置</Button><Button type="primary" htmlType="submit">应用筛选</Button></Space>
      </Form>
    </Drawer>
    <Drawer title="创建应急事件" width={520} open={!!drawer} onClose={() => setDrawer(undefined)}>
      <Form layout="vertical" initialValues={{ title: drawer?.objectName ? `${drawer.objectName}异常` : '', level: drawer?.level }}>
        <Form.Item name="title" label="事件标题"><Input /></Form.Item>
        <Form.Item name="risk" label="来源风险"><Input value={drawer?.code} disabled /></Form.Item>
        <Space><Button onClick={() => setDrawer(undefined)}>取消</Button><Button type="primary" onClick={async () => { const created = await createIncidentFromRisks([drawer!.id]); history.push(`/incident/${created.id}`); }}>生成事件并查看详情</Button></Space>
      </Form>
    </Drawer>
    <Modal title="忽略风险" okText="确定" cancelText="取消" open={!!ignoreTarget} onCancel={() => setIgnoreTarget(undefined)} onOk={async () => {
      const values = await ignoreForm.validateFields();
      await ignoreRisk(ignoreTarget!.id, values.reason);
      setIgnoreTarget(undefined); ignoreForm.resetFields(); actionRef.current?.reload();
      message.success('已忽略风险并写入审计日志');
    }}><Form form={ignoreForm} layout="vertical"><Form.Item name="reason" label="忽略理由" rules={[{ required: true, message: '请填写忽略理由' }]}><Input.TextArea rows={4} /></Form.Item></Form></Modal>
  </>;
}
