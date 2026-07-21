import { PageContainer } from '@ant-design/pro-components';
import { Alert, App, Button, Card, Col, Descriptions, Form, Input, InputNumber, Row, Space, Table, Tag } from 'antd';
import { ApiOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { getErpIntegration, getErpSyncHistory, saveErpIntegration, syncSavedErpIntegration, testSavedErpIntegration, type ErpIntegrationConfig } from '@/services/settings';
import ErpMappingEditor from '@/components/ErpMappingEditor';
import SsoConfigCard from '@/components/SsoConfigCard';

export default function Integration() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [config, setConfig] = useState<ErpIntegrationConfig>();
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string[]>(['material']);
  const load = async () => {
    setLoading(true);
    try {
      const [saved, jobs] = await Promise.all([getErpIntegration(), getErpSyncHistory()]);
      setConfig(saved); setHistory(jobs);
      form.setFieldsValue({ baseUrl: saved.baseUrl, connectionParams: saved.connectionParams || {} });
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  const save = async () => {
    const values = await form.validateFields();
    const saved = await saveErpIntegration(values);
    setConfig(saved); form.setFieldValue('apiKey', undefined); message.success('ERP 配置已保存；凭证不会再次显示。');
  };
  const test = async () => {
    const saved = await testSavedErpIntegration(); setConfig(saved); message.success('ERP 健康检查和资源目录读取成功。');
  };
  const sync = async () => {
    if (!selected.length) { message.warning('请选择至少一个同步对象。'); return; }
    await syncSavedErpIntegration(selected); message.success('ERP 手动同步已完成。'); await load();
  };
  const status = config?.lastTestStatus;
  return <PageContainer title="系统集成" subTitle="ERP 最小集成 · 企业单点登录">
    <Alert showIcon type="info" style={{ marginBottom: 16 }} message="字段映射即时生效" description="内置映射来自 ChainGuard/config/erp_mapping.yaml；在下方保存自定义映射后，本租户的下一次 ERP 同步即按新映射执行，同步历史会记录所用映射版本。CSV 导入仍使用内置映射。" />
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={12}><Card title={<Space><ApiOutlined />ERP 连接配置</Space>} loading={loading} extra={<Tag color={config?.credentialConfigured ? 'green' : 'default'}>{config?.credentialMasked || '未配置凭证'}</Tag>}>
        {/* 后端按密文前缀判断该凭证是否仍是旧派生方案（见 security/encryption.py 的
            needs_rewrap）。不在界面提示的话，管理员无从得知需要重新保存一次，
            存量密文会永远停留在已淘汰的 KDF 上。重新保存即完成升级。 */}
        {config?.credentialNeedsRewrap && <Alert showIcon type="warning" style={{ marginBottom: 16 }}
          message="凭证使用旧版加密方案"
          description="该凭证是用已淘汰的密钥派生方案加密的。请在下方重新填写一次认证令牌并保存，即可升级为当前方案；在此之前它仍可正常解密使用。" />}
        <Form form={form} layout="vertical">
          <Form.Item name="baseUrl" label="ERP Base URL" rules={[{ required: true, type: 'url', message: '请输入 http:// 或 https:// 地址' }]}><Input placeholder="http://127.0.0.1:8765" /></Form.Item>
          <Form.Item name="apiKey" label="认证令牌" extra="保存后只显示脱敏配置状态；留空不会覆盖已保存的令牌。"><Input.Password autoComplete="new-password" placeholder={config?.credentialConfigured ? '已配置（如需更换请输入新令牌）' : '可选：Bearer token'} /></Form.Item>
          <Row gutter={12}><Col span={12}><Form.Item name={['connectionParams', 'timeoutSeconds']} label="超时（秒）"><InputNumber min={1} max={30} style={{ width: '100%' }} placeholder="8" /></Form.Item></Col><Col span={12}><Form.Item name={['connectionParams', 'pageSize']} label="分页大小"><InputNumber min={1} max={1000} style={{ width: '100%' }} placeholder="500" /></Form.Item></Col></Row>
          <Space><Button type="primary" onClick={save}>保存配置</Button><Button disabled={!config?.configured} onClick={test}>测试连接</Button></Space>
        </Form>
      </Card></Col>
      <Col xs={24} xl={12}><Card title="连通状态与资源目录" loading={loading}><Descriptions size="small" column={1} items={[{ key: 'status', label: '最近测试', children: <Tag color={status === 'available' ? 'green' : status === 'unavailable' ? 'red' : 'default'}>{status === 'available' ? '可用' : status === 'unavailable' ? '不可用' : '未测试'}</Tag> }, { key: 'time', label: '最近测试时间', children: config?.lastTestAt ? new Date(config.lastTestAt).toLocaleString() : '-' }, { key: 'reason', label: '失败原因', children: config?.lastTestError || '-' }]} />
        <Table size="small" rowKey="resource" pagination={false} dataSource={config?.availableResources || []} columns={[{ title: '资源', dataIndex: 'resource' }, { title: '目录记录数', dataIndex: 'recordCount' }]} />
      </Card></Col>
      <Col span={24}><Card title="手动同步" extra={<Button type="primary" disabled={!config?.configured || !selected.length} onClick={sync}>开始同步</Button>}><Space wrap>{['material', 'supplier', 'supplier_material', 'customer', 'order', 'order_line', 'inventory'].map((type) => <Tag.CheckableTag key={type} checked={selected.includes(type)} onChange={(checked) => setSelected((current) => checked ? [...current, type] : current.filter((item) => item !== type))}>{type}</Tag.CheckableTag>)}</Space></Card></Col>
      <Col span={24}><ErpMappingEditor onSaved={load} /></Col>
      <Col span={24}><SsoConfigCard /></Col>
      <Col span={24}><Card title="ERP 同步历史" loading={loading}><Table rowKey="id" size="small" dataSource={history} pagination={false} columns={[{ title: '时间', dataIndex: 'updatedAt', render: (value) => value ? new Date(value).toLocaleString() : '-' }, { title: '触发人', dataIndex: 'operator' }, { title: '对象', dataIndex: ['options', 'types'], render: (value) => Array.isArray(value) ? value.join(', ') : '-' }, { title: '所用映射', render: (_, row) => row.options?.mappingSource === 'tenant' ? <Tag color="blue">{`自定义 v${row.options?.mappingVersion}`}</Tag> : <Tag>内置</Tag> }, { title: '映射修改人/时间', render: (_, row) => row.options?.mappingSource === 'tenant' ? `${row.options?.mappingUpdatedBy || '-'} / ${row.options?.mappingUpdatedAt ? new Date(row.options.mappingUpdatedAt).toLocaleString() : '-'}` : '-' }, { title: '成功/失败', render: (_, row) => `${row.successRows ?? row.success ?? 0} / ${row.rejectedRows ?? row.failed ?? 0}` }, { title: '状态', dataIndex: 'status', render: (value) => <Tag color={value === 'succeeded' ? 'green' : value === 'failed' ? 'red' : 'blue'}>{value}</Tag> }, { title: '错误摘要', dataIndex: ['result', 'errorSummary'], render: (value) => value || '-' }]} /></Card></Col>
    </Row>
  </PageContainer>;
}
