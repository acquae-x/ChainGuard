import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

// ERP 字段映射编辑 UI 的真实 Chromium API-mode 验收。
// 覆盖查看、编辑、校验失败、保存后被真实同步使用、权限与跨租户隔离。
const apiPort = Number(process.env.MAP_E2E_API_PORT || 8480);
const erpPort = Number(process.env.MAP_E2E_MOCK_PORT || 8482);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(process.env.MAP_E2E_EVIDENCE_DIR || '../ChainGuard/output/phase5b-erp-mapping/screenshots');

async function useToken(page: Page, token: string) {
  await page.goto('/user/login');
  await page.context().addCookies([{ name: 'chainguard_token', value: token, url: new URL(page.url()).origin }]);
}

async function loginToken(page: Page, account: string) {
  const response = await page.request.post(apiUrl('/auth/login'), { data: { account, password: 'MapE2E@2026!' } });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json() as { token: string }).token;
}

test('API 模式 Chromium：ERP 字段映射查看、编辑、校验、驱动同步、权限与隔离', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  const adminToken = await loginToken(page, 'map-admin-a@chainguard.test');
  const adminHeaders = { Authorization: `Bearer ${adminToken}` };
  await useToken(page, adminToken);

  // ---- 连接配置 + 连通测试（映射编辑的前置） ----
  await page.goto('/settings/integration');
  await page.getByLabel('ERP Base URL').fill(`http://127.0.0.1:${erpPort}`);
  await page.getByLabel('认证令牌').fill('map-e2e-token');
  await page.getByRole('button', { name: '保存配置' }).click();
  await expect(page.getByText('凭证不会再次显示')).toBeVisible();
  await page.getByRole('button', { name: '测试连接' }).click();
  await expect(page.getByText('ERP 健康检查和资源目录读取成功。')).toBeVisible();

  // ---- 1. 查看：默认内置映射，按实体分组 ----
  const mappingCard = page.locator('.ant-card', { hasText: 'ERP 字段映射' }).first();
  await expect(mappingCard.getByText('随产品交付的内置映射文件')).toBeVisible();
  await expect(mappingCard.getByText('物料主数据')).toBeVisible();
  await expect(mappingCard.getByText('materials → materials')).toBeVisible();
  await expect(mappingCard.getByText('未声明列：进入 extra（保留原值）').first()).toBeVisible();
  await expect(mappingCard.getByText('业务键').first()).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '01-mapping-view-grouped.png'), fullPage: true });

  // 真实源字段目录（连接已验证）
  await mappingCard.getByRole('button', { name: '读取 ERP 源字段' }).first().click();
  await expect(page.getByText('行真实 ERP 数据得到的源字段')).toBeVisible();
  await expect(page.getByRole('cell', { name: 'sales_price', exact: true })).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '02-source-field-catalog.png'), fullPage: true });
  await page.keyboard.press('Escape');

  // ---- 2. 校验失败：删掉业务键映射后保存被拒 ----
  const materialTable = mappingCard.locator('.ant-collapse-item').filter({ hasText: '物料主数据' }).locator('table').first();
  const keyRow = materialTable.locator('tr', { has: page.locator('input[value="material_id"]') }).first();
  await keyRow.getByRole('button', { name: '删除映射行' }).click();
  await mappingCard.getByRole('button', { name: '保存映射' }).click();
  await expect(page.getByText('映射校验未通过（未保存）')).toBeVisible();
  await expect(mappingCard.getByText(/material_id.*not mapped|not mapped.*material_id/)).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '03-validation-failure-blocks-save.png'), fullPage: true });

  // 校验失败不得写入任何版本
  const stillFile = await page.request.get(apiUrl('/settings/integrations/erp/mapping'), { headers: adminHeaders });
  expect((await stillFile.json() as { source: string }).source).toBe('file');

  // ---- 3. 编辑并保存：unit_cost 改从 sales_price 取值 ----
  await mappingCard.getByRole('button', { name: '重新加载' }).click();
  await expect(mappingCard.getByText('随产品交付的内置映射文件')).toBeVisible();
  const costInput = materialTable.locator('input[value="standard_cost"]').first();
  await costInput.fill('sales_price');
  await mappingCard.getByRole('button', { name: '保存映射' }).click();
  await expect(page.getByText(/映射已保存为 v1/)).toBeVisible();
  await expect(mappingCard.getByText('租户自定义 v1')).toBeVisible();
  await expect(mappingCard.getByText('实施管理员 A')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '04-mapping-saved-v1.png'), fullPage: true });

  // ---- 4. 保存后的映射必须被下一次同步实际使用 ----
  await page.getByRole('button', { name: '开始同步' }).click();
  await expect(page.getByText('ERP 手动同步已完成。')).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText('自定义 v1').first()).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '05-sync-history-mapping-version.png'), fullPage: true });

  const synced = await page.request.get(apiUrl('/data/material'), { headers: adminHeaders });
  expect(synced.ok(), await synced.text()).toBeTruthy();
  const first = (await synced.json() as { data: Array<{ id: string; cost: number }> }).data
    .find((item) => item.id === 'MAT-0001');
  // 内置映射取 standard_cost=174.9；自定义映射取 sales_price=250.62。
  expect(first?.cost).toBeCloseTo(250.62, 2);

  const history = await page.request.get(apiUrl('/imports'), { headers: adminHeaders });
  const job = (await history.json() as { data: any[] }).data.find((item) => item.importType === 'erp');
  expect(job.options.mappingSource).toBe('tenant');
  expect(job.options.mappingVersion).toBe(1);
  expect(job.options.mappingUpdatedBy).toBe('实施管理员 A');
  expect(job.options.mappingUpdatedAt).toBeTruthy();

  // ---- 5. 无 settings:manage 的用户既不能读也不能写映射 ----
  const importerToken = await loginToken(page, 'map-importer-a@chainguard.test');
  const importerHeaders = { Authorization: `Bearer ${importerToken}` };
  const forbiddenRead = await page.request.get(apiUrl('/settings/integrations/erp/mapping'), { headers: importerHeaders });
  expect(forbiddenRead.status()).toBe(403);
  const forbiddenWrite = await page.request.put(apiUrl('/settings/integrations/erp/mapping'), { headers: importerHeaders, data: { values: { spec: {} } } });
  expect(forbiddenWrite.status()).toBe(403);
  expect(await forbiddenWrite.text()).not.toContain('sales_price');

  // ---- 6. 跨租户隔离：B 租户看不到 A 的自定义映射 ----
  const tenantBToken = await loginToken(page, 'map-admin-b@chainguard.test');
  const tenantBHeaders = { Authorization: `Bearer ${tenantBToken}` };
  const mappingB = await page.request.get(apiUrl('/settings/integrations/erp/mapping'), { headers: tenantBHeaders });
  const viewB = await mappingB.json() as { source: string; version: number | null; updatedBy: string | null; spec: any };
  expect(viewB.source).toBe('file');
  expect(viewB.version).toBeNull();
  expect(viewB.updatedBy).toBeNull();
  expect(viewB.spec.resources.material.converts.unit_cost.from).toBe('standard_cost');

  // ---- 7. 恢复内置映射 ----
  await useToken(page, adminToken);
  await page.goto('/settings/integration');
  await mappingCard.getByRole('button', { name: '恢复内置映射' }).click();
  await page.getByRole('button', { name: '恢复内置映射' }).last().click();
  await expect(page.getByText('已恢复内置映射。')).toBeVisible();
  await expect(mappingCard.getByText('随产品交付的内置映射文件')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '06-reset-to-builtin.png'), fullPage: true });
});
