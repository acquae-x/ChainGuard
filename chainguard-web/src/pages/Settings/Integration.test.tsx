import { describe, expect, it, vi } from 'vitest';
import { App } from 'antd';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const services = vi.hoisted(() => ({
  getErpIntegration: vi.fn(), getErpSyncHistory: vi.fn(), saveErpIntegration: vi.fn(),
  testSavedErpIntegration: vi.fn(), syncSavedErpIntegration: vi.fn(),
  getErpMapping: vi.fn(), validateErpMapping: vi.fn(), saveErpMapping: vi.fn(),
  resetErpMapping: vi.fn(), getErpMappingSourceFields: vi.fn(),
}));
const mappingView = {
  source: 'file', version: null, updatedAt: null, updatedBy: null, filePath: 'config/erp_mapping.yaml',
  usable: true, degraded: false, degradeReason: null, errors: [], warnings: [],
  conversionTypes: ['float', 'integer', 'string'], sensitiveColumns: ['token'],
  resources: [{
    resourceType: 'material', label: '物料主数据', sourceTable: 'materials', targetTable: 'materials',
    aggregation: 'row', unknownColumns: 'extra', forbiddenColumns: [], requiredSources: ['material_id'],
    businessKeys: ['material_id'],
    rows: [
      { sourceField: 'material_id', targetField: 'material_id', kind: 'field', convertType: null, required: true, businessKey: true, sensitive: false },
      { sourceField: 'standard_cost', targetField: 'unit_cost', kind: 'convert', convertType: 'float', required: false, businessKey: false, sensitive: false },
    ],
    targetColumns: [{ name: 'material_id', type: 'string', nullable: false }, { name: 'unit_cost', type: 'float', nullable: true }],
  }],
  spec: { resources: { material: { fields: { material_id: 'material_id' }, converts: { unit_cost: { from: 'standard_cost', type: 'float' } }, required: ['material_id'] } } },
};
const config = {
  configured: true, baseUrl: 'http://127.0.0.1:8765', credentialConfigured: true, credentialMasked: '已配置',
  connectionParams: { timeoutSeconds: 8, pageSize: 500 }, lastTestStatus: 'available', lastTestAt: '2026-07-19T10:00:00+00:00',
  lastTestError: null, availableResources: [{ resource: 'materials', recordCount: 1 }],
};
services.getErpIntegration.mockResolvedValue(config);
services.getErpSyncHistory.mockResolvedValue([{ id: 'erp-a', updatedAt: '2026-07-19T10:01:00+00:00', operator: 'ERP admin', options: { types: ['material'] }, successRows: 1, rejectedRows: 0, status: 'succeeded', result: {} }]);
services.testSavedErpIntegration.mockResolvedValue(config);
services.getErpMapping.mockResolvedValue(mappingView);
vi.mock('@/services/settings', () => services);

// 集成页在 5B「账户完善」后同时承载 SSO 配置卡；此处只关心它挂上了，SSO 行为由自己的用例覆盖。
const accountServices = vi.hoisted(() => ({ getSsoConfig: vi.fn(), saveSsoConfig: vi.fn() }));
accountServices.getSsoConfig.mockResolvedValue({
  configured: false, enabled: false, clientSecretSet: false, issuer: '', clientId: '',
  authorizationEndpoint: '', tokenEndpoint: '', redirectUri: '', scopes: 'openid email profile',
  emailClaim: 'email', subjectClaim: 'sub', allowedDomains: [], autoProvision: false,
  defaultRoleCode: 'auditor', updatedAt: null,
});
vi.mock('@/services/account', () => accountServices);

import Integration from './Integration';

describe('ERP integration settings', () => {
  it('shows masked credential state, catalog and tenant-local sync history', async () => {
    render(<App><Integration /></App>);
    expect(await screen.findByText('ERP 连接配置')).toBeInTheDocument();
    expect(screen.getByText('已配置')).toBeInTheDocument();
    expect(screen.getByText('materials')).toBeInTheDocument();
    expect(screen.getByText('ERP 同步历史')).toBeInTheDocument();
    expect(screen.queryByText('erp-test-token')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '测试连接' }));
    await waitFor(() => expect(services.testSavedErpIntegration).toHaveBeenCalledTimes(1));
    // 当前方案加密的凭证不应出现升级提示
    expect(screen.queryByText('凭证使用旧版加密方案')).not.toBeInTheDocument();
  });

  // 后端能算出"这条密文用的是旧密钥派生方案"，但此前前端从不读这个字段，
  // 管理员因此无从得知需要重新保存一次来完成升级，存量密文永远升不了级。
  it('tells the operator to re-save when the stored credential still uses the legacy KDF', async () => {
    services.getErpIntegration.mockResolvedValueOnce({ ...config, credentialNeedsRewrap: true });
    render(<App><Integration /></App>);
    expect(await screen.findByText('凭证使用旧版加密方案')).toBeInTheDocument();
    expect(screen.getByText(/重新填写一次认证令牌并保存/)).toBeInTheDocument();
    // 升级前仍可正常使用，不能把它说成故障
    expect(screen.getByText(/在此之前它仍可正常解密使用/)).toBeInTheDocument();
  });

  it('renders the field mapping editor with its provenance and per-entity rows', async () => {
    render(<App><Integration /></App>);
    expect(await screen.findByText('ERP 字段映射')).toBeInTheDocument();
    expect(screen.getByText('随产品交付的内置映射文件')).toBeInTheDocument();
    expect(screen.getByText('物料主数据')).toBeInTheDocument();
    expect(screen.getByText('materials → materials')).toBeInTheDocument();
    // 未保存前不可保存，也不能恢复内置映射（当前就是内置）。
    expect(screen.getByRole('button', { name: '保存映射' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '恢复内置映射' })).toBeDisabled();
    await waitFor(() => expect(screen.getByDisplayValue('standard_cost')).toBeInTheDocument());
  });

  it('surfaces the SSO card as unconfigured without ever showing a client secret', async () => {
    render(<App><Integration /></App>);
    expect(await screen.findByText('企业单点登录（OIDC SSO）')).toBeInTheDocument();
    expect(screen.getByText('未配置客户端密钥')).toBeInTheDocument();
    expect(screen.getByText('未配置完成前，登录页的 SSO 入口会明确提示不可用')).toBeInTheDocument();
  });

  it('blocks the save and surfaces every reason when validation fails', async () => {
    services.validateErpMapping.mockResolvedValue({ valid: false, errors: ["material: target_key 'material_id' is not mapped"], warnings: [] });
    render(<App><Integration /></App>);
    await screen.findByText('ERP 字段映射');
    const sourceInput = await screen.findByDisplayValue('material_id');
    fireEvent.change(sourceInput, { target: { value: 'legacy_id' } });
    fireEvent.click(screen.getByRole('button', { name: '保存映射' }));
    expect(await screen.findByText('映射校验未通过（未保存）')).toBeInTheDocument();
    expect(screen.getByText("material: target_key 'material_id' is not mapped")).toBeInTheDocument();
    expect(services.saveErpMapping).not.toHaveBeenCalled();
  });
});
