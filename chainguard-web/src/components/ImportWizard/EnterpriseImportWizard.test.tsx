import { App } from 'antd';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getCatalog = vi.fn();

vi.mock('@umijs/max', () => ({
  useModel: () => ({ initialState: { currentUser: { permissions: ['data:import'] } } }),
}));

vi.mock('@/services/enterpriseImport', () => ({
  getEnterpriseImportCatalog: () => getCatalog(),
  uploadForRecognition: vi.fn(),
  uploadBatchForRecognition: vi.fn(),
  preflightRecognizedJob: vi.fn(),
  confirmAndExecuteRecognizedJob: vi.fn(),
  testErpConnection: vi.fn(),
  previewErp: vi.fn(),
  syncErp: vi.fn(),
}));

import EnterpriseImportWizard from './EnterpriseImportWizard';

describe('EnterpriseImportWizard 数据来源与识别优先流程', () => {
  beforeEach(() => {
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
