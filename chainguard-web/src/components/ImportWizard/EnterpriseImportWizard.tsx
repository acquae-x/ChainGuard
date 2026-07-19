import {
  ApiOutlined,
  FileZipOutlined,
  FileExcelOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  ScanOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { useModel } from '@umijs/max';
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Form,
  Grid,
  Input,
  Progress,
  Row,
  Select,
  Space,
  Steps,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { InputHTMLAttributes, ReactNode } from 'react';
import {
  confirmAndExecuteRecognizedJob,
  getEnterpriseImportCatalog,
  preflightRecognizedJob,
  previewErp,
  syncErp,
  testErpConnection,
  uploadBatchForRecognition,
  uploadForRecognition,
} from '@/services/enterpriseImport';
import type { ClassifiedFile, EnterpriseImportJob, ImportCatalogType, ImportMode } from '@/services/enterpriseImport';
import { getEnterpriseFieldMapping } from '@/services/data';
import { normalizeImportHistoryJob } from '@/services/importHistory';
import type { ImportRowRejection, ImportTableReport } from '@/services/importHistory';

const channelCards: Array<{ value: ImportMode; title: string; description: string; icon: ReactNode }> = [
  { value: 'structured', title: 'CSV / Excel', description: '上传表格，自动识别资料类型、映射字段并校验落库', icon: <FileExcelOutlined /> },
  { value: 'ocr', title: 'PDF / Word / 图片', description: 'OCR/文本提取后必须人工确认；熟悉模板只减少确认项', icon: <ScanOutlined /> },
  { value: 'erp', title: 'ERP 接口', description: '连接 ERP，读取资料目录，确认范围后同步', icon: <ApiOutlined /> },
];

const permissionDomains: Record<string, string[]> = {
  'data:import:own': ['supplier', 'supplier_material', 'supplier_performance', 'purchase_order', 'purchase_order_line'],
  'data:import:inventory': ['warehouse', 'inventory', 'inventory_snapshot', 'inventory_movement', 'shipment'],
  'data:import:order': ['customer', 'order', 'order_line'],
  'data:import:material': ['material', 'production_plan', 'quality_inspection'],
};

const reportColumns = [
  { title: '资料表', key: 'table', render: (_: unknown, row: ImportTableReport) => row.label !== '-' ? row.label : row.table },
  { title: '源行', dataIndex: 'sourceRows' },
  { title: '成功', dataIndex: 'successRows' },
  { title: '拒绝', dataIndex: 'rejectedRows' },
  { title: '新增', dataIndex: 'inserted' },
  { title: '更新', dataIndex: 'updated' },
];

const rejectionColumns = [
  { title: '源行', dataIndex: 'row', width: 80, render: (value: number | null) => value ?? '-' },
  { title: '拒绝原因', dataIndex: 'reason' },
  { title: '修复建议', dataIndex: 'suggestion' },
  { title: '源数据', dataIndex: 'source', render: (value: Record<string, unknown>) => <Typography.Text code>{JSON.stringify(value)}</Typography.Text> },
];

export default function EnterpriseImportWizard(_props: { embedded?: boolean } = {}) {
  const { message } = App.useApp();
  const screens = Grid.useBreakpoint();
  const { initialState } = useModel('@@initialState');
  const batchInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const permissions = initialState?.currentUser?.permissions || [];
  const [catalog, setCatalog] = useState<ImportCatalogType[]>([]);
  const [mode, setMode] = useState<ImportMode>('mixed');
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<ClassifiedFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [erpForm] = Form.useForm();
  const [erpConnected, setErpConnected] = useState(false);
  const [erpPreview, setErpPreview] = useState<any[]>([]);
  const [selectedErpTypes, setSelectedErpTypes] = useState<string[]>([]);
  const [erpConfirmed, setErpConfirmed] = useState(false);
  const [erpConnectionValues, setErpConnectionValues] = useState<{ baseUrl: string; apiKey?: string }>();
  const [results, setResults] = useState<EnterpriseImportJob[]>([]);

  useEffect(() => {
    getEnterpriseImportCatalog()
      .then((result) => setCatalog(result.types))
      .catch(() => message.error('导入类型目录加载失败'));
  }, [message]);

  const allowedTypes = useMemo(() => {
    if (permissions.includes('data:import')) return catalog;
    const allowed = new Set<string>();
    permissions.forEach((permission) => (permissionDomains[permission] || []).forEach((value) => allowed.add(value)));
    return catalog.filter((item) => allowed.has(item.value));
  }, [catalog, permissions]);

  const typeOptions = useMemo(() => allowedTypes.map((item) => ({ label: `${item.label} · ${item.group}`, value: item.value })), [allowedTypes]);
  const normalizedResults = useMemo(() => results.map(normalizeImportHistoryJob), [results]);
  const steps = useMemo(() => [
    { title: '选通道' },
    { title: mode === 'erp' ? '连接 ERP' : '上传' },
    { title: mode === 'erp' ? '选择范围' : '自动识别' },
    { title: '人工确认' },
    { title: '执行结果' },
  ], [mode]);

  const resetChannel = (next: ImportMode) => {
    setMode(next);
    setFiles([]);
    setErpConnected(false);
    setErpPreview([]);
    setSelectedErpTypes([]);
    setErpConfirmed(false);
    setErpConnectionValues(undefined);
    setResults([]);
  };

  const ingestFiles = async (selected: File[]) => {
    if (!selected.length) return;
    setLoading(true);
    try {
      const isBatch = mode === 'mixed' || selected.length > 1 || selected[0].name.toLowerCase().endsWith('.zip');
      const classified = isBatch
        ? (await uploadBatchForRecognition(selected)).files
        : [await uploadForRecognition(selected[0], mode as 'structured' | 'ocr')];
      setFiles(classified);
      setStep(2);
      message.success(`已上传并识别 ${classified.length} 个文件`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '上传与识别失败');
    } finally {
      setLoading(false);
    }
  };

  const runPreflight = async () => {
    if (files.some((file) => !file.selectedType)) {
      message.warning('请先确认每个文件的资料类型');
      return;
    }
    setLoading(true);
    try {
      const next = await Promise.all(files.map(async (file) => {
        const job = await preflightRecognizedJob(file.jobId);
        const previewRows = Array.isArray((job.result?.normalized as { previewRows?: unknown[] } | undefined)?.previewRows)
          ? (job.result?.normalized as { previewRows: Array<Record<string, unknown>> }).previewRows
          : [];
        const sourceFields = previewRows.length ? Object.keys(previewRows[0]) : [];
        const mapping = file.mode === 'ocr' && file.selectedType
          ? await getEnterpriseFieldMapping(file.selectedType, sourceFields)
          : { fields: [], matches: [] };
        return {
          ...file,
          recognition: job.result?.recognition || file.recognition,
          preflight: job.result,
          mappingFields: mapping.fields,
          fieldMapping: Object.fromEntries(mapping.matches.map((match) => [match.source, match.target])),
        };
      }));
      setFiles(next);
      setStep(3);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '预检失败');
    } finally {
      setLoading(false);
    }
  };

  const executeFiles = async () => {
    const unconfirmedOcr = files.some((file) => file.mode === 'ocr' && !file.manualConfirmed);
    const blocked = files.some((file) => file.preflight?.canProceed === false);
    const incompleteMapping = files.find((file) => file.mode === 'ocr' && (file.mappingFields || [])
      .filter((field) => field.required)
      .some((field) => !Object.values(file.fieldMapping || {}).includes(field.key)));
    if (unconfirmedOcr) return message.warning('OCR/文档文件必须逐项完成人工确认');
    if (incompleteMapping) return message.warning(`${incompleteMapping.fileName} 尚未映射全部必填目标字段`);
    if (blocked) return message.error('存在未提取或预检不通过的文件，不能执行');
    setLoading(true);
    try {
      const completed: EnterpriseImportJob[] = [];
      for (const file of files) {
        try {
          completed.push(await confirmAndExecuteRecognizedJob(file));
        } catch (error) {
          completed.push({
            id: file.jobId,
            status: 'failed',
            result: { success: 0, failed: 1, message: error instanceof Error ? error.message : '执行失败' },
          });
        }
      }
      setResults(completed);
      setStep(4);
      if (completed.some((item) => {
        const normalized = normalizeImportHistoryJob(item);
        return item.status === 'failed' || normalized.rejectedRows > 0;
      })) message.warning('批量导入已完成，部分文件或行被拒绝，请展开查看报告');
      else message.success('导入执行完成');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '导入执行失败');
    } finally {
      setLoading(false);
    }
  };

  const testErp = async () => {
    const values = await erpForm.validateFields();
    setLoading(true);
    try {
      await testErpConnection(values);
      setErpConnected(true);
      message.success('ERP 连接测试通过');
    } catch (error) {
      setErpConnected(false);
      message.error(error instanceof Error ? error.message : 'ERP 连接失败');
    } finally {
      setLoading(false);
    }
  };

  const loadErpCatalog = async () => {
    const values = await erpForm.validateFields();
    setLoading(true);
    try {
      const types = allowedTypes.map((item) => item.value);
      const result = await previewErp({ ...values, types });
      setErpConnectionValues(values);
      setErpPreview(result.resources || []);
      setSelectedErpTypes((result.resources || []).filter((item: any) => item.rows > 0).map((item: any) => item.type));
      setStep(2);
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'ERP 目录读取失败');
    } finally {
      setLoading(false);
    }
  };

  const executeErp = async () => {
    if (!erpConfirmed) return message.warning('请先人工确认 ERP 同步范围');
    if (!erpConnectionValues) return message.error('ERP 连接信息已失效，请返回连接步骤重新验证');
    setLoading(true);
    try {
      const result = await syncErp({ ...erpConnectionValues, types: selectedErpTypes });
      setResults([result]);
      setStep(4);
      message.success('ERP 同步完成');
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'ERP 同步失败');
    } finally {
      setLoading(false);
    }
  };

  const next = async () => {
    if (step === 0) return setStep(1);
    if (step === 1 && mode === 'erp') return loadErpCatalog();
    if (step === 2 && mode !== 'erp') return runPreflight();
    if (step === 2 && mode === 'erp') return setStep(3);
    if (step === 3) return mode === 'erp' ? executeErp() : executeFiles();
  };

  const fileColumns = [
    { title: '文件', dataIndex: 'fileName' },
    { title: '通道', dataIndex: 'mode', render: (value: string) => <Tag color={value === 'ocr' ? 'orange' : 'blue'}>{value === 'ocr' ? 'OCR 文档' : '表格'}</Tag> },
    {
      title: '识别结果（需人工确认）',
      key: 'type',
      width: 300,
      render: (_: unknown, row: ClassifiedFile) => <Select
        showSearch
        value={row.selectedType}
        placeholder="待人工指定"
        style={{ width: '100%' }}
        options={typeOptions}
        onChange={(value) => setFiles((current) => current.map((item) => item.jobId === row.jobId ? { ...item, selectedType: value, fieldMapping: undefined, mappingFields: undefined } : item))}
      />,
    },
    {
      title: '置信度与依据', key: 'confidence', width: 260,
      render: (_: unknown, row: ClassifiedFile) => <Space direction="vertical" size={2} style={{ width: '100%' }}>
        <Progress percent={Math.round((row.recognition?.confidence || 0) * 100)} size="small" status={(row.recognition?.confidence || 0) >= 0.55 ? 'success' : 'exception'} />
        <Typography.Text type="secondary">{row.recognition?.reasons?.join('；')}</Typography.Text>
      </Space>,
    },
  ];

  return <section aria-label="企业数据导入" style={{ width: '100%', maxWidth: '100%', minWidth: 0, boxSizing: 'border-box' }}>
    <Steps current={step} items={steps} size="small" responsive={false} direction={screens.xl ? 'horizontal' : 'vertical'} style={{ marginBottom: 24 }} />

    {step === 0 && <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Title level={5} style={{ margin: 0 }}>直接上传，系统会识别文件格式和业务类型</Typography.Title>
      <Card
        hoverable
        onClick={() => resetChannel('mixed')}
        style={{ borderColor: mode === 'mixed' ? '#1677ff' : undefined, background: mode === 'mixed' ? '#f0f7ff' : undefined }}
      >
        <Row align="middle" justify="space-between" gutter={[16, 16]}>
          <Col xs={24} xl={18} style={{ minWidth: 0 }}>
            <Space align="start" style={{ width: '100%', minWidth: 0 }}>
              <Typography.Title level={3} style={{ margin: 0, color: '#1677ff' }}><FileZipOutlined /></Typography.Title>
              <Space direction="vertical" size={3} style={{ minWidth: 0 }}>
                <Typography.Text strong style={{ fontSize: 16 }}>智能混合导入：文件夹 / ZIP</Typography.Text>
                <Typography.Text type="secondary">同一个文件夹或压缩包可同时包含 CSV、Excel、PDF、Word 和图片；系统逐文件识别并自动分流。</Typography.Text>
                <Space wrap><Tag color="blue">表格校验</Tag><Tag color="orange">OCR 人工确认</Tag><Tag>低置信度待指定</Tag></Space>
              </Space>
            </Space>
          </Col>
          <Col xs={24} xl={6} style={{ textAlign: screens.xl ? 'right' : 'left' }}>
            <Button type="primary" icon={<FolderOpenOutlined />} onClick={(event) => { event.stopPropagation(); resetChannel('mixed'); setStep(1); }}>直接上传</Button>
          </Col>
        </Row>
      </Card>
      <Typography.Text strong>也可以按固定来源导入</Typography.Text>
      <Row gutter={[16, 16]}>
        {channelCards.map((channel) => <Col xs={24} md={12} xl={8} key={channel.value}>
          <Card
            hoverable
            onClick={() => resetChannel(channel.value)}
            style={{ height: '100%', borderColor: mode === channel.value ? '#1677ff' : undefined }}
          >
            <Space align="start" style={{ width: '100%', minWidth: 0 }}>
              <Typography.Title level={3} style={{ margin: 0, color: mode === channel.value ? '#1677ff' : undefined }}>{channel.icon}</Typography.Title>
              <Space direction="vertical" size={2} style={{ minWidth: 0 }}>
                <Typography.Text strong>{channel.title}</Typography.Text>
                <Typography.Text type="secondary">{channel.description}</Typography.Text>
              </Space>
            </Space>
          </Card>
        </Col>)}
      </Row>
      <Alert type="info" showIcon message={`已配置 ${allowedTypes.length} 类真实业务资料；识别 Agent 只提供建议，最终类型必须由人工确认。`} />
    </Space>}

    {step === 1 && mode !== 'erp' && <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Upload.Dragger
        accept={mode === 'mixed' ? '.csv,.xlsx,.pdf,.doc,.docx,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.zip' : mode === 'structured' ? '.csv,.xlsx,.zip' : '.pdf,.doc,.docx,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.zip'}
        showUploadList={false}
        disabled={loading}
        beforeUpload={(file) => { void ingestFiles([file as File]); return false; }}
      >
        <p><InboxOutlined /></p>
        <p>{mode === 'mixed' ? '拖入混合 ZIP / 多个文件，或使用下方按钮选择' : mode === 'structured' ? '上传 CSV / Excel，或包含多类资料的 ZIP' : '上传 PDF / Word / 图片，或包含多份文档的 ZIP'}</p>
        <Typography.Text type="secondary">上传后由识别 Agent 自动分类，再由你确认；不会直接落库。</Typography.Text>
      </Upload.Dragger>
      <Space wrap>
        <Button icon={<FileZipOutlined />} onClick={() => batchInput.current?.click()}>选择 ZIP / 多个文件</Button>
        <Button icon={<FolderOpenOutlined />} onClick={() => folderInput.current?.click()}>选择整个文件夹</Button>
        <Typography.Text type="secondary">文件夹内支持表格、文档和图片混合，系统会逐文件分流。</Typography.Text>
      </Space>
      <input
        hidden ref={batchInput} type="file" multiple
        accept={mode === 'mixed' ? '.csv,.xlsx,.pdf,.doc,.docx,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.zip' : mode === 'structured' ? '.csv,.xlsx,.zip' : '.pdf,.doc,.docx,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.zip'}
        onChange={(event) => { void ingestFiles(Array.from(event.target.files || [])); event.target.value = ''; }}
      />
      <input
        hidden ref={folderInput} type="file" multiple
        {...({ webkitdirectory: '', directory: '' } as InputHTMLAttributes<HTMLInputElement>)}
        onChange={(event) => { void ingestFiles(Array.from(event.target.files || [])); event.target.value = ''; }}
      />
    </Space>}

    {step === 1 && mode === 'erp' && <Space direction="vertical" size="middle" style={{ width: '100%', maxWidth: 680 }}>
      <Alert type="info" showIcon message="ERP 密钥仅用于本次请求，不写入导入任务、日志或数据库。" />
      <Form form={erpForm} layout="vertical" initialValues={{ baseUrl: 'http://127.0.0.1:9000' }}>
        <Form.Item name="baseUrl" label="ERP API 地址" rules={[{ required: true, message: '请输入 ERP API 地址' }]}>
          <Input placeholder="https://erp.example.com" />
        </Form.Item>
        <Form.Item name="apiKey" label="API Key（可选）"><Input.Password placeholder="仅在本次连接中使用" /></Form.Item>
      </Form>
      <Button loading={loading} onClick={testErp} icon={<ApiOutlined />}>测试连接</Button>
      {erpConnected && <Alert type="success" showIcon message="连接已验证，可以读取资料目录" />}
    </Space>}

    {step === 2 && mode !== 'erp' && <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Alert type="warning" showIcon message="识别结果不会自动生效" description="请逐项确认或纠正资料类型。低置信度文件已明确标出，不会猜测后直接导入。" />
      <Table rowKey="jobId" dataSource={files} columns={fileColumns} pagination={{ pageSize: 10 }} scroll={{ x: 900 }} />
    </Space>}

    {step === 2 && mode === 'erp' && <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Alert type="info" showIcon message={`ERP 共识别 ${erpPreview.length} 类资料，请选择本次同步范围。`} />
      <Table
        rowKey="type" dataSource={erpPreview} pagination={false}
        rowSelection={{ selectedRowKeys: selectedErpTypes, onChange: (keys) => setSelectedErpTypes(keys.map(String)) }}
        columns={[
          { title: '资料类型', dataIndex: 'label' },
          { title: '源行数', dataIndex: 'rows' },
          { title: '处理方式', key: 'kind', render: (_: unknown, row: any) => catalog.find((item) => item.value === row.type)?.entity ? <Tag color="blue">实体落库</Tag> : <Tag>源审计</Tag> },
        ]}
      />
    </Space>}

    {step === 3 && mode !== 'erp' && <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Alert icon={<SafetyCertificateOutlined />} type="warning" showIcon message="执行前人工确认" description="表格需确认识别类型；OCR/Word/图片无论是否为熟悉模板，都必须人工确认。历史模板只会把完整复核缩减为差异复核。" />
      <Table
        rowKey="jobId" dataSource={files} pagination={false} scroll={{ x: 900 }}
        columns={[
          { title: '文件', dataIndex: 'fileName' },
          { title: '已确认类型', key: 'type', render: (_: unknown, row: ClassifiedFile) => catalog.find((item) => item.value === row.selectedType)?.label || row.selectedType },
          { title: '预检', key: 'preflight', render: (_: unknown, row: ClassifiedFile) => row.preflight?.canProceed === false ? <Tag color="red">阻断</Tag> : <Tag color="green">通过</Tag> },
          { title: '复核级别', key: 'review', render: (_: unknown, row: ClassifiedFile) => row.mode !== 'ocr' ? <Tag>类型确认</Tag> : <Tag color="orange">{row.preflight?.manualReview?.confirmationLevel === 'light' ? '熟悉模板 · 差异复核' : '首次模板 · 完整复核'}</Tag> },
          {
            title: '人工确认', key: 'confirm', render: (_: unknown, row: ClassifiedFile) => row.mode === 'ocr'
              ? <Checkbox disabled={row.preflight?.canProceed === false} checked={!!row.manualConfirmed} onChange={(event) => setFiles((current) => current.map((item) => item.jobId === row.jobId ? { ...item, manualConfirmed: event.target.checked } : item))}>已核对原文、类型和关键字段</Checkbox>
              : <Typography.Text type="success">已确认分类</Typography.Text>,
          },
        ]}
      />
      {files.filter((file) => file.mode === 'ocr').map((file) => {
        const previewRows = Array.isArray((file.preflight?.normalized as { previewRows?: unknown[] } | undefined)?.previewRows)
          ? (file.preflight?.normalized as { previewRows: Array<Record<string, unknown>> }).previewRows
          : [];
        const sourceFields = previewRows.length ? Object.keys(previewRows[0]) : [];
        const mappedTargets = Object.values(file.fieldMapping || {}).filter(Boolean);
        const missingRequired = (file.mappingFields || []).filter((field) => field.required && !mappedTargets.includes(field.key));
        return <Card key={`${file.jobId}-mapping`} size="small" title={`${file.fileName} · 字段映射`}>
          <Space direction="vertical" size="small" style={{ width: '100%' }}>
            <Typography.Text type="secondary">已识别 {sourceFields.length} 个源字段。系统按现有别名规则给出建议，请逐项核对；“必填”目标必须完成映射。</Typography.Text>
            {missingRequired.length > 0 && <Alert type="error" showIcon message={`缺少必填映射：${missingRequired.map((field) => `${field.label} (${field.key})`).join('、')}`} />}
            {!file.mappingFields?.length && <Alert type="warning" showIcon message="当前资料类型尚无可用的前端字段定义，请改选受支持的资料类型或人工处理。" />}
            <Table
              aria-label={`${file.fileName} 字段映射`}
              rowKey="source"
              size="small"
              pagination={false}
              dataSource={sourceFields.map((source) => ({ source, sample: previewRows[0]?.[source] }))}
              columns={[
                { title: '识别到的源字段', dataIndex: 'source' },
                { title: '样例值', dataIndex: 'sample', render: (value: unknown) => String(value ?? '') },
                {
                  title: '目标字段', key: 'target', width: 320,
                  render: (_: unknown, row: { source: string }) => <Select
                    aria-label={`${row.source} 目标字段`}
                    allowClear
                    placeholder="不导入此字段"
                    value={file.fieldMapping?.[row.source]}
                    style={{ width: '100%' }}
                    options={(file.mappingFields || []).map((field) => ({
                      value: field.key,
                      label: `${field.label} (${field.key})${field.required ? ' · 必填' : ''}`,
                      disabled: mappedTargets.includes(field.key) && file.fieldMapping?.[row.source] !== field.key,
                    }))}
                    onChange={(value) => setFiles((current) => current.map((item) => item.jobId === file.jobId
                      ? { ...item, fieldMapping: { ...item.fieldMapping, [row.source]: value } }
                      : item))}
                  />,
                },
              ]}
              scroll={{ x: 720 }}
            />
          </Space>
        </Card>;
      })}
    </Space>}

    {step === 3 && mode === 'erp' && <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Descriptions bordered size="small" column={2} items={[
        { key: 'types', label: '同步类型', children: selectedErpTypes.length },
        { key: 'rows', label: '预计源行数', children: erpPreview.filter((item) => selectedErpTypes.includes(item.type)).reduce((sum, item) => sum + item.rows, 0) },
      ]} />
      <Checkbox checked={erpConfirmed} onChange={(event) => setErpConfirmed(event.target.checked)}>我已核对 ERP 地址、资料类型和预计行数，确认执行本次同步</Checkbox>
    </Space>}

    {step === 4 && <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Alert
        type={normalizedResults.every((item) => item.status === 'succeeded' && item.rejectedRows === 0) ? 'success' : 'warning'}
        showIcon
        message="导入批次执行完成"
        description={normalizedResults.some((item) => item.rejectedRows > 0) ? '存在被拒绝的数据行，请展开对应批次查看逐表报告。' : undefined}
      />
      <Table
        rowKey="id"
        dataSource={normalizedResults}
        pagination={false}
        expandable={{
          rowExpandable: (row) => row.reports.length > 0 || row.rejections.length > 0,
          expandedRowRender: (row) => <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {row.reports.length > 0 && <Table<ImportTableReport>
              aria-label={`${row.id} 逐表导入报告`}
              rowKey={(report) => `${report.table}-${report.label}`}
              size="small"
              pagination={false}
              dataSource={row.reports}
              columns={reportColumns}
              scroll={{ x: 680 }}
            />}
            {row.rejections.length > 0 && <Table<ImportRowRejection>
              aria-label={`${row.id} 逐行拒绝明细`}
              rowKey={(rejection, index) => `${rejection.row ?? 'unknown'}-${index}`}
              size="small"
              pagination={false}
              dataSource={row.rejections}
              columns={rejectionColumns}
              scroll={{ x: 900 }}
            />}
          </Space>,
        }}
        columns={[
        { title: '批次号', dataIndex: 'id' },
        { title: '状态', dataIndex: 'status', render: (value: string) => <Tag color={value === 'succeeded' ? 'green' : 'red'}>{value}</Tag> },
        { title: '成功', dataIndex: 'successRows' },
        { title: '拒绝', dataIndex: 'rejectedRows', render: (value: number) => <Tag color={value > 0 ? 'red' : 'default'}>{value}</Tag> },
        { title: '说明', dataIndex: 'message' },
      ]} />
    </Space>}

    <Space style={{ marginTop: 24 }} wrap>
      <Button disabled={step === 0 || loading} onClick={() => setStep((value) => Math.max(0, value - 1))}>上一步</Button>
      {step < 4 && <Button
        type="primary" loading={loading} onClick={() => void next()}
        disabled={(step === 1 && mode !== 'erp') || (step === 1 && mode === 'erp' && !erpConnected) || (step === 2 && mode === 'erp' && !selectedErpTypes.length)}
      >{step === 3 ? '确认并执行' : '下一步'}</Button>}
      {step === 4 && <Button type="primary" onClick={() => { setStep(0); resetChannel(mode); }}>继续导入</Button>}
    </Space>
  </section>;
}
