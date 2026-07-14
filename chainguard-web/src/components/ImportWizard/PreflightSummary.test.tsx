import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// ImportWizard 模块顶层 import 了 umi/服务/组件桶；只测纯展示组件 PreflightSummary，
// 因此把这些重依赖 mock 掉，避免拉起 umi 运行时。
vi.mock('@umijs/max', () => ({
  history: { push: vi.fn(), replace: vi.fn() },
  useModel: () => ({ initialState: { currentUser: { permissions: [] } } }),
}));
vi.mock('@/services/data', () => ({
  commitImport: vi.fn(),
  getFieldMapping: vi.fn(),
  getImportTemplate: vi.fn(),
  parseFile: vi.fn(),
  preflightUpload: vi.fn(),
  validateRows: vi.fn(),
}));
vi.mock('@/components', () => ({ EmptyGuide: () => null }));

import { PreflightSummary } from './index';

const alertType = () => {
  const el = document.querySelector('.ant-alert');
  return [...(el?.classList || [])].find((c) => c.startsWith('ant-alert-') && c !== 'ant-alert-with-description' && c !== 'ant-alert-no-icon');
};

describe('PreflightSummary 红黄绿灯与预览', () => {
  it('绿灯：verdict=OK 显示 success 且展示归一化预览行', () => {
    render(
      <PreflightSummary
        report={{
          verdict: 'OK',
          canProceed: true,
          estimatedRows: 25,
          normalized: { table: 'material', previewLimit: 20, previewRows: [{ 物料编码: 'M-AX100', 名称: '核心控制芯片' }] },
        }}
      />,
    );
    expect(alertType()).toBe('ant-alert-success');
    expect(screen.getByText(/绿灯/)).toBeInTheDocument();
    expect(screen.getByText('25')).toBeInTheDocument();
    // 归一化预览表渲染出表头与数据（antd Table 有隐藏测量行，同文本可能出现多次）
    expect(screen.getAllByText('物料编码').length).toBeGreaterThan(0);
    expect(screen.getAllByText('M-AX100').length).toBeGreaterThan(0);
  });

  it('黄灯：verdict=REVIEW 显示 warning 且仍可导入', () => {
    render(
      <PreflightSummary
        report={{ verdict: 'REVIEW', canProceed: true, estimatedRows: 12, normalized: { previewRows: [] } }}
      />,
    );
    expect(alertType()).toBe('ant-alert-warning');
    expect(screen.getByText(/黄灯/)).toBeInTheDocument();
  });

  it('红灯：verdict=PARSE_ERROR 显示 error 并阻止导入', () => {
    render(
      <PreflightSummary
        report={{ verdict: 'PARSE_ERROR', canProceed: false, messages: ['XLSX 解析失败'], normalized: { previewRows: [] } }}
      />,
    );
    expect(alertType()).toBe('ant-alert-error');
    expect(screen.getByText(/红灯/)).toBeInTheDocument();
  });

  it('红灯：磁盘不足 INSUFFICIENT_DISK 硬阻断', () => {
    render(
      <PreflightSummary
        report={{ verdict: 'INSUFFICIENT_DISK', canProceed: false, diskOk: false, diskShortfallBytes: 1024, normalized: { previewRows: [] } }}
      />,
    );
    expect(alertType()).toBe('ant-alert-error');
    expect(screen.getByText(/磁盘空间不足/)).toBeInTheDocument();
  });

  it('红灯：canProceed=false 即使无 verdict 也不放假绿灯', () => {
    render(<PreflightSummary report={{ canProceed: false, normalized: { previewRows: [] } }} />);
    expect(alertType()).toBe('ant-alert-error');
    expect(screen.getByText(/红灯/)).toBeInTheDocument();
  });
});
