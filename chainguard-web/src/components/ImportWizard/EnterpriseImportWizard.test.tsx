import { App } from 'antd';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getCatalog, uploadForRecognition, preflightRecognizedJob, confirmAndExecuteRecognizedJob, testErpConnection, previewErp, syncErp } = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  uploadForRecognition: vi.fn(),
  preflightRecognizedJob: vi.fn(),
  confirmAndExecuteRecognizedJob: vi.fn(),
  testErpConnection: vi.fn(),
  previewErp: vi.fn(),
  syncErp: vi.fn(),
}));

vi.mock('@/runtime', () => ({
  useModel: () => ({ initialState: { currentUser: { permissions: ['data:import'] } } }),
}));

vi.mock('@/services/enterpriseImport', () => ({
  getEnterpriseImportCatalog: () => getCatalog(),
  uploadForRecognition,
  uploadBatchForRecognition: vi.fn(),
  preflightRecognizedJob,
  confirmAndExecuteRecognizedJob,
  testErpConnection,
  previewErp,
  syncErp,
}));

import EnterpriseImportWizard from './EnterpriseImportWizard';

describe('EnterpriseImportWizard 数据来源与识别优先流程', () => {
  beforeEach(() => {
    testErpConnection.mockReset();
    previewErp.mockReset();
    syncErp.mockReset();
    uploadForRecognition.mockReset();
    preflightRecognizedJob.mockReset();
    confirmAndExecuteRecognizedJob.mockReset();
    getCatalog.mockResolvedValue({
      modes: [],
      types: Array.from({ length: 18 }, (_, index) => ({
        value: `type-${index}`,
        label: `资料${index}`,
        group: '真实业务资料',
        source_table: `table_${index}`,
        erp_resource: `resource-${index}`,
        entity: index < 7,
      })),
    });
  });

  it('OCR 人工确认页展示源字段、别名建议并提交 fieldMapping', async () => {
    const user = userEvent.setup();
    getCatalog.mockResolvedValue({ modes: [], types: [{
      value: 'material', label: '物料主数据', group: '主数据', source_table: 'materials', erp_resource: 'materials', entity: true,
    }] });
    uploadForRecognition.mockResolvedValue({
      jobId: 'ocr-1', fileName: '中文物料.png', mode: 'ocr', selectedType: 'material',
      recognition: { recognizedType: 'material', label: '物料主数据', confidence: 0.98, requiresConfirmation: true, reasons: [], candidates: [] },
    });
    preflightRecognizedJob.mockResolvedValue({ id: 'ocr-1', status: 'manual_review', result: {
      canProceed: true, normalized: { previewRows: [{ 物料编码: 'MAT-CN-1', 物料名称: '中文芯片', 成本: '12.5' }] },
      manualReview: { confirmationLevel: 'full' },
    } });
    confirmAndExecuteRecognizedJob.mockResolvedValue({ id: 'ocr-1', status: 'succeeded', result: { successRows: 1, rejectedRows: 0 } });

    const { container } = render(<App><EnterpriseImportWizard /></App>);
    await user.click(screen.getByText('PDF / Word / 图片'));
    await user.click(screen.getByRole('button', { name: '下一步' }));
    const input = container.querySelector('.ant-upload input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(['png'], '中文物料.png', { type: 'image/png' }));
    await screen.findByText('中文物料.png');
    await user.click(screen.getByRole('button', { name: '下一步' }));

    await screen.findByRole('table', { name: '中文物料.png 字段映射' });
    expect(screen.getByRole('combobox', { name: '物料编码 目标字段' }).closest('.ant-select')).toHaveTextContent('物料编号');
    expect(screen.getByRole('combobox', { name: '物料名称 目标字段' }).closest('.ant-select')).toHaveTextContent('物料名称');
    expect(screen.getByRole('combobox', { name: '成本 目标字段' }).closest('.ant-select')).toHaveTextContent('单位成本');
    await user.click(screen.getByRole('checkbox', { name: /已核对原文、类型和关键字段/ }));
    await user.click(screen.getByRole('button', { name: '确认并执行' }));

    await waitFor(() => expect(confirmAndExecuteRecognizedJob).toHaveBeenCalledWith(expect.objectContaining({
      manualConfirmed: true,
      fieldMapping: { 物料编码: 'material_id', 物料名称: 'material_name', 成本: 'standard_cost' },
    })));
    expect(await screen.findByText('导入批次执行完成')).toBeInTheDocument();
  });

  it('OCR 乱码或列结构损坏时展示明确原因和重传/人工录入建议', async () => {
    const user = userEvent.setup();
    getCatalog.mockResolvedValue({ modes: [], types: [{
      value: 'material', label: '物料主数据', group: '主数据', source_table: 'materials', erp_resource: 'materials', entity: true,
    }] });
    uploadForRecognition.mockResolvedValue({
      jobId: 'ocr-garbled', fileName: '乱码物料.png', mode: 'ocr', selectedType: 'material',
      recognition: { recognizedType: 'material', label: '物料主数据', confidence: 0.99, requiresConfirmation: true, reasons: [], candidates: [] },
    });
    preflightRecognizedJob.mockResolvedValue({ id: 'ocr-garbled', status: 'manual_required', result: {
      canProceed: false,
      message: 'OCR 结果疑似乱码；不能作为预检通过依据。请重新上传包含真实中文像素的清晰图片，或改用人工录入。',
      extraction: { error_code: 'OCR_GARBLED_TEXT', note: 'OCR 结果疑似乱码。', confidence: 0.99 },
      normalized: { previewRows: [] },
      manualReview: {
        confirmationLevel: 'full',
        reasonCode: 'OCR_GARBLED_TEXT',
        suggestions: ['重新上传清晰、端正且保留表头和列分隔符的图片', '改用 CSV/Excel 上传，或人工录入'],
      },
    } });

    const { container } = render(<App><EnterpriseImportWizard /></App>);
    await user.click(screen.getByText('PDF / Word / 图片'));
    await user.click(screen.getByRole('button', { name: '下一步' }));
    const input = container.querySelector('.ant-upload input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(['png'], '乱码物料.png', { type: 'image/png' }));
    await screen.findByText('乱码物料.png');
    await user.click(screen.getByRole('button', { name: '下一步' }));

    expect(await screen.findByText(/OCR 无法安全形成字段映射（OCR_GARBLED_TEXT）/)).toBeInTheDocument();
    expect(screen.getByText(/疑似乱码；不能作为预检通过依据/)).toBeInTheDocument();
    expect(screen.getByText(/重新上传清晰、端正且保留表头和列分隔符/)).toBeInTheDocument();
    expect(screen.getByText(/CSV\/Excel 上传，或人工录入/)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /已核对原文、类型和关键字段/ })).toBeDisabled();
    expect(confirmAndExecuteRecognizedJob).not.toHaveBeenCalled();
  });

  it('ERP 确认步骤沿用已预览的连接信息执行全量同步', async () => {
    const user = userEvent.setup();
    testErpConnection.mockResolvedValue({ ok: true });
    previewErp.mockResolvedValue({
      resources: [{ type: 'type-0', label: '资料0', rows: 1 }],
    });
    syncErp.mockResolvedValue({
      id: 'erp-1',
      status: 'succeeded',
      result: { sourceRows: 1, successRows: 1, rejectedRows: 0 },
    });

    render(<App><EnterpriseImportWizard /></App>);
    await waitFor(() => expect(screen.getByText(/已配置 18 类真实业务资料/)).toBeInTheDocument());
    await user.click(screen.getByText('ERP 接口'));
    await user.click(screen.getByRole('button', { name: '下一步' }));

    const baseUrl = screen.getByRole('textbox', { name: /ERP API 地址/ });
    await user.clear(baseUrl);
    await user.type(baseUrl, 'http://127.0.0.1:8462');
    await user.click(screen.getByRole('button', { name: /测试连接/ }));
    await waitFor(() => expect(screen.getByText('连接已验证，可以读取资料目录')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: '下一步' }));
    await waitFor(() => expect(screen.getByText('ERP 共识别 1 类资料，请选择本次同步范围。')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '下一步' }));
    await user.click(screen.getByRole('checkbox', { name: /我已核对 ERP 地址/ }));
    await user.click(screen.getByRole('button', { name: '确认并执行' }));

    await waitFor(() => expect(syncErp).toHaveBeenCalledWith({
      baseUrl: 'http://127.0.0.1:8462',
      types: ['type-0'],
    }));
    await waitFor(() => expect(screen.getByText('导入批次执行完成')).toBeInTheDocument());
  });

  it('首屏提供混合批量入口和三种固定来源，不要求预先选择业务类型', async () => {
    render(<App><EnterpriseImportWizard /></App>);
    expect(screen.getByText('智能混合导入：文件夹 / ZIP')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /直接上传/ })).toBeInTheDocument();
    expect(screen.getByText(/同时包含 CSV、Excel、PDF、Word 和图片/)).toBeInTheDocument();
    expect(screen.getByText('CSV / Excel')).toBeInTheDocument();
    expect(screen.getByText('PDF / Word / 图片')).toBeInTheDocument();
    expect(screen.getByText('ERP 接口')).toBeInTheDocument();
    expect(screen.getByText('直接上传，系统会识别文件格式和业务类型')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '企业数据导入' })).not.toHaveStyle({ overflowX: 'hidden' });
    await waitFor(() => expect(screen.getByText(/已配置 18 类真实业务资料/)).toBeInTheDocument());
    expect(screen.queryByText('先选业务类型')).not.toBeInTheDocument();
  });
});
