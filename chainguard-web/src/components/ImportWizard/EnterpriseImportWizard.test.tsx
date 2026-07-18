import { App } from 'antd';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getCatalog, testErpConnection, previewErp, syncErp } = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  testErpConnection: vi.fn(),
  previewErp: vi.fn(),
  syncErp: vi.fn(),
}));

vi.mock('@umijs/max', () => ({
  useModel: () => ({ initialState: { currentUser: { permissions: ['data:import'] } } }),
}));

vi.mock('@/services/enterpriseImport', () => ({
  getEnterpriseImportCatalog: () => getCatalog(),
  uploadForRecognition: vi.fn(),
  uploadBatchForRecognition: vi.fn(),
  preflightRecognizedJob: vi.fn(),
  confirmAndExecuteRecognizedJob: vi.fn(),
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
