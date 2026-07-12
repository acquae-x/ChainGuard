import { DownloadOutlined, InboxOutlined } from '@ant-design/icons';
import { history, useModel } from '@umijs/max';
import { Alert, Button, Checkbox, Descriptions, Radio, Result, Select, Space, Steps, Table, Tag, Typography, Upload, message } from 'antd';
import type { UploadProps } from 'antd';
import { useMemo, useState } from 'react';
import * as XLSX from 'xlsx';
import { EmptyGuide } from '@/components';
import {
  commitImport,
  getFieldMapping,
  getImportTemplate,
  parseFile,
  preflightUpload,
  validateRows
} from '@/services/data';
import type {
  ImportCommitResult,
  ImportField,
  ImportType,
  ImportValidationResult,
  ParsedImportFile
} from '@/services/data';

const typeOptions: Array<{ label: string; value: ImportType }> = [
  { label: '物料', value: 'material' },
  { label: '供应商', value: 'supplier' },
  { label: '客户', value: 'customer' },
  { label: '订单', value: 'order' },
  { label: '库存', value: 'inventory' }
];

// 02 文档能力矩阵「导入数据」：admin/scm_lead 全域；buyer 本域(供应商)；warehouse 库存；sales 订单；planner 物料
const importScopeMap: Record<string, ImportType[]> = {
  'data:import': ['material', 'supplier', 'customer', 'order', 'inventory'],
  'data:import:own': ['supplier'],
  'data:import:inventory': ['inventory'],
  'data:import:order': ['order'],
  'data:import:material': ['material']
};

const errorLabels: Record<string, string> = {
  required: '必填缺失',
  type: '类型错误',
  enum: '枚举非法',
  duplicate: '重复行'
};

export default function ImportWizard({ embedded = false }: { embedded?: boolean }) {
  const { initialState } = useModel('@@initialState');
  const permissions = initialState?.currentUser?.permissions || [];
  const allowedTypes = useMemo(() => {
    const allowed = new Set<ImportType>();
    permissions.forEach((code) => (importScopeMap[code] || []).forEach((item) => allowed.add(item)));
    return typeOptions.filter((option) => allowed.has(option.value));
  }, [permissions]);
  const [step, setStep] = useState(0);
  const [type, setType] = useState<ImportType>(allowedTypes[0]?.value || 'supplier');
  const [parsed, setParsed] = useState<ParsedImportFile>();
  const [fields, setFields] = useState<ImportField[]>([]);
  const [mapping, setMapping] = useState<Record<string, string | undefined>>({});
  const [confidence, setConfidence] = useState<Record<string, number>>({});
  const [validation, setValidation] = useState<ImportValidationResult>();
  const [result, setResult] = useState<ImportCommitResult>();
  const [preflightReport, setPreflightReport] = useState<any>();
  const [duplicatePolicy, setDuplicatePolicy] = useState<'skip' | 'overwrite' | 'merge'>('skip');
  const [onlyValidRows, setOnlyValidRows] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [lastFile, setLastFile] = useState<File>();
  const items = useMemo(() => ['选类型', '上传', '字段映射', '校验预览', '结果报告'].map((title) => ({ title })), []);

  const resetFileState = () => {
    setParsed(undefined);
    setFields([]);
    setMapping({});
    setConfidence({});
    setValidation(undefined);
    setResult(undefined);
  };

  const loadFile = async (file: File) => {
    setLoading(true);
    setLastFile(file);
    setError(undefined);
    try {
      // A1: API 模式直接展示后端 preflight，容量/格式的最终口径不再由浏览器单独裁决。
      const serverPreflight = await preflightUpload(file, type);
      setPreflightReport(serverPreflight?.result);
      if (/\.(pdf|png|jpe?g)$/i.test(file.name)) {
        // 非表格文件不应交给 SheetJS；服务端预检已完成 OCR/视觉级联或给出待人工处理标记。
        setParsed({ fileName: file.name, headers: [], rows: [], total: 0 });
        setFields([]);
        setMapping({});
        setConfidence({});
        setValidation({ total: 0, success: 0, failed: 0, validRows: [], mappedRows: [], errors: [], errorSummary: {} });
        setStep(3);
        message.info(serverPreflight?.status === 'manual_required' ? '文件已进入 staging，等待人工处理' : '文件已由服务端归一化，正在展示预检结果');
        return;
      }
      const parsedFile = await parseFile(file);
      const mappingResult = await getFieldMapping(type, parsedFile.headers);
      setParsed(parsedFile);
      setFields(mappingResult.fields);
      setMapping(Object.fromEntries(mappingResult.matches.map((match) => [match.source, match.target])));
      setConfidence(Object.fromEntries(mappingResult.matches.map((match) => [match.source, match.confidence])));
      setStep(2);
      message.success(`已解析 ${parsedFile.total} 行，字段已自动预匹配`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '文件解析失败');
    } finally {
      setLoading(false);
    }
  };

  const uploadProps: UploadProps = {
    accept: '.xlsx,.csv,.pdf,.png,.jpg,.jpeg',
    maxCount: 1,
    showUploadList: false,
    beforeUpload: async (file) => {
      if (file.size > 10 * 1024 * 1024) {
        message.error('文件不能超过 10MB');
        return Upload.LIST_IGNORE;
      }
      await loadFile(file as File);
      return false;
    }
  };

  const downloadTemplate = async () => {
    const template = await getImportTemplate(type);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(template.rows), template.sheetName);
    XLSX.writeFile(workbook, template.fileName);
  };

  const useExampleFile = async () => {
    const template = await getImportTemplate(type);
    const rows = [...template.rows, { ...template.rows[0] }];
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(rows), template.sheetName);
    const content = XLSX.write(workbook, { type: 'array', bookType: 'xlsx' });
    await loadFile(new File([content], `${type}-example.xlsx`, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }));
  };

  const mappedTargets = Object.values(mapping).filter(Boolean);
  const missingRequired = fields.filter((field) => field.required && !mappedTargets.includes(field.key));
  const errorsByRow = useMemo(() => {
    const grouped = new Map<number, string[]>();
    validation?.errors.forEach((error) => grouped.set(error.row, [...(grouped.get(error.row) || []), error.message]));
    return grouped;
  }, [validation]);

  const validate = async () => {
    if (!parsed) return;
    setLoading(true);
    try {
      const nextValidation = await validateRows(parsed.rows, mapping, fields);
      setValidation(nextValidation);
      setStep(3);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '数据校验失败');
    } finally {
      setLoading(false);
    }
  };

  const commit = async (force = false) => {
    if (!validation) return;
    setLoading(true);
    try {
      const res = await commitImport({ type, validation, onlyValidRows, duplicatePolicy, file: lastFile, force });
      // 服务端预检未通过：中止并展示报告，等待用户显式确认"仍要导入"
      if (res.preflightBlocked) {
        setPreflightReport(res.preflightReport ?? {});
        message.warning('服务端预检未通过，请查看预检报告后再决定是否继续');
        return;
      }
      setPreflightReport(undefined);
      setResult(res);
      setStep(4);
      message.success('导入批次已提交');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '数据提交失败');
    } finally {
      setLoading(false);
    }
  };

  const downloadErrorReport = () => {
    if (!parsed || !validation?.errors.length) return;
    const errorRows = Array.from(new Set(validation.errors.map((error) => error.row))).map((rowNumber) => ({
      ...parsed.rows[rowNumber - 2],
      错误原因: validation.errors.filter((error) => error.row === rowNumber).map((error) => error.message).join('；')
    }));
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(errorRows), '错误明细');
    XLSX.writeFile(workbook, `${type}-import-errors.xlsx`);
  };

  const next = async () => {
    if (step === 0) setStep(1);
    if (step === 2) await validate();
    if (step === 3) await commit();
    if (step === 4) {
      if (!embedded) history.push(`/data/${type}`);
      else message.success('导入步骤已完成');
    }
  };

  const validationColumns = fields
    .filter((field) => mappedTargets.includes(field.key))
    .map((field) => ({ title: field.label, dataIndex: field.key }));

  if (error) return <section aria-label="数据导入向导"><Steps current={step} items={items} style={{ marginBottom: 24 }} /><Result status="500" title="导入服务暂时不可用" subTitle={error} extra={<Button type="primary" disabled={!lastFile} onClick={() => lastFile && loadFile(lastFile)}>重试</Button>} /></section>;
  if (step === 2 && parsed && parsed.total === 0) return <section aria-label="数据导入向导"><Steps current={step} items={items} style={{ marginBottom: 24 }} /><EmptyGuide title="文件中没有数据行" description="请检查文件内容后重新上传。" actionText="返回上传" onAction={() => setStep(1)} /></section>;

  return (
    <section aria-label="数据导入向导">
      <Steps current={step} items={items} style={{ marginBottom: 24 }} />

      {step === 0 && (
        <Space direction="vertical" size="middle">
          <Radio.Group
            value={type}
            onChange={(event) => {
              setType(event.target.value);
              resetFileState();
            }}
            options={allowedTypes}
          />
          <Button icon={<DownloadOutlined />} onClick={downloadTemplate}>下载{typeOptions.find((item) => item.value === type)?.label}标准模板</Button>
        </Space>
      )}

      {step === 1 && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Upload.Dragger {...uploadProps} disabled={loading}>
            <p><InboxOutlined /></p>
            <p>拖拽 Excel/CSV/PDF/图片到此处，文件不超过 10MB</p>
            <Typography.Text type="secondary">CSV/Excel 可映射字段；PDF/图片将由服务端 OCR/视觉级联提取，未配置能力时会明确转为待人工处理。</Typography.Text>
          </Upload.Dragger>
          <Button loading={loading} onClick={useExampleFile}>使用当前类型示例文件</Button>
        </Space>
      )}

      {step === 2 && parsed && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {preflightReport && <Alert type={preflightReport.canProceed === false ? 'warning' : 'info'} showIcon message="服务端预检结果（导入最终口径）" description={<pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(preflightReport, null, 2)}</pre>} />}
          {!!missingRequired.length && <Alert type="warning" showIcon message={`必填字段尚未映射：${missingRequired.map((field) => field.label).join('、')}`} />}
          <Table
            size="small"
            pagination={false}
            rowKey="source"
            dataSource={parsed.headers.map((source) => ({ source }))}
            columns={[
              { title: '文件表头', dataIndex: 'source' },
              {
                title: '系统字段',
                dataIndex: 'source',
                render: (source: string) => (
                  <Select
                    allowClear
                    value={mapping[source]}
                    style={{ width: 220 }}
                    placeholder="不导入该列"
                    onChange={(value) => setMapping((current) => ({ ...current, [source]: value }))}
                    options={fields.map((field) => ({
                      label: `${field.label}${field.required ? '（必填）' : ''}`,
                      value: field.key,
                      disabled: mappedTargets.includes(field.key) && mapping[source] !== field.key
                    }))}
                  />
                )
              },
              {
                title: '预匹配置信度',
                dataIndex: 'source',
                render: (source: string) => mapping[source]
                  ? <Tag color={confidence[source] >= 0.75 ? 'green' : 'orange'}>{confidence[source] >= 0.75 ? '高' : '低'} {Math.round(confidence[source] * 100)}%</Tag>
                  : <Tag>未匹配</Tag>
              }
            ]}
          />
          <Table
            size="small"
            title={() => `原始数据预览（前 20 行，共 ${parsed.total} 行）`}
            pagination={false}
            rowKey={(_, index) => String(index)}
            dataSource={parsed.rows.slice(0, 20)}
            columns={parsed.headers.map((header) => ({ title: header, dataIndex: header }))}
            scroll={{ x: true }}
          />
        </Space>
      )}

      {step === 3 && validation && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {preflightReport && (
            <Alert
              type="error"
              showIcon
              message="服务端预检未通过，已中止导入"
              description={
                <Space direction="vertical" style={{ width: '100%' }} size="small">
                  <Typography.Text>预检报告如下，请核对后再决定是否继续导入（继续将带着问题数据落库）：</Typography.Text>
                  <pre style={{ maxHeight: 220, overflow: 'auto', margin: 0, fontSize: 12, background: 'rgba(0,0,0,0.03)', padding: 8, borderRadius: 4 }}>{typeof preflightReport === 'string' ? preflightReport : JSON.stringify(preflightReport, null, 2)}</pre>
                  <Space>
                    <Button danger loading={loading} onClick={() => commit(true)}>仍要导入</Button>
                    <Button onClick={() => setPreflightReport(undefined)}>取消</Button>
                  </Space>
                </Space>
              }
            />
          )}
          <Descriptions bordered size="small" column={{ xs: 1, sm: 3 }} items={[
            { key: 'total', label: '校验总数', children: validation.total },
            { key: 'success', label: '可导入', children: validation.success },
            { key: 'failed', label: '错误行', children: <Typography.Text type={validation.failed ? 'danger' : 'success'}>{validation.failed}</Typography.Text> }
          ]} />
          {!!validation.errors.length && (
            <Alert
              type="error"
              showIcon
              message="校验发现问题"
              description={<Space wrap>{Object.entries(validation.errorSummary).map(([key, count]) => <Tag color="red" key={key}>{errorLabels[key]} {count}</Tag>)}</Space>}
            />
          )}
          <Table
            size="small"
            pagination={{ pageSize: 10 }}
            rowKey="__rowNumber"
            dataSource={validation.mappedRows}
            columns={[
              { title: 'Excel 行号', dataIndex: '__rowNumber', fixed: 'left' },
              ...validationColumns,
              { title: '校验结果', dataIndex: '__rowNumber', render: (row: number) => errorsByRow.has(row) ? <Typography.Text type="danger">{errorsByRow.get(row)?.join('；')}</Typography.Text> : <Tag color="green">通过</Tag> }
            ]}
            scroll={{ x: true }}
          />
          <Space wrap>
            <Typography.Text>重复数据策略：</Typography.Text>
            <Radio.Group value={duplicatePolicy} onChange={(event) => setDuplicatePolicy(event.target.value)} options={[{ label: '跳过', value: 'skip' }, { label: '覆盖', value: 'overwrite' }, { label: '合并', value: 'merge' }]} />
            <Checkbox checked={onlyValidRows} onChange={(event) => setOnlyValidRows(event.target.checked)}>仅导入正确行</Checkbox>
          </Space>
        </Space>
      )}

      {step === 4 && result && (
        <Space direction="vertical" size="middle">
          <Alert type={result.failed ? 'warning' : 'success'} showIcon message={`尝试 ${result.attempted ?? result.total} 条，成功 ${result.success}，失败 ${result.failed}`} description={`批次号：${result.batchId}`} />
          {!!validation?.errors.length && <Button icon={<DownloadOutlined />} onClick={downloadErrorReport}>下载错误报告.xlsx</Button>}
        </Space>
      )}

      <Space style={{ marginTop: 24 }}>
        <Button disabled={step === 0 || loading} onClick={() => setStep((current) => Math.max(current - 1, 0))}>上一步</Button>
        <Button
          type="primary"
          loading={loading}
          disabled={(step === 1 && !parsed) || (step === 2 && missingRequired.length > 0)}
          onClick={next}
        >
          {step === 4 && !embedded ? '查看数据列表' : step === 4 ? '完成' : step === 3 ? '确认导入' : '下一步'}
        </Button>
        {step === 2 && !embedded && <Button onClick={() => message.success('映射模板已保存（mock）')}>保存为映射模板</Button>}
      </Space>
    </section>
  );
}
