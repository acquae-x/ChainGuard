import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const apiPort = Number(process.env.ERP_E2E_API_PORT || 8470);
const erpPort = Number(process.env.ERP_E2E_MOCK_PORT || 8472);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(process.env.ERP_E2E_EVIDENCE_DIR || '../ChainGuard/output/phase5b-erp/screenshots');

async function useToken(page: Page, token: string) {
  await page.goto('/user/login');
  await page.context().addCookies([{ name: 'chainguard_token', value: token, url: new URL(page.url()).origin }]);
}

async function loginToken(page: Page, account: string) {
  const response = await page.request.post(apiUrl('/auth/login'), { data: { account, password: 'ErpE2E@2026!' } });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json() as { token: string }).token;
}

test('API 模式 Chromium：ERP 配置、health/catalog、手动同步、隔离与安全失败', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  const tokenA = await loginToken(page, 'erp-admin-a@chainguard.test');
  const headersA = { Authorization: `Bearer ${tokenA}` };
  await useToken(page, tokenA);

  await page.goto('/settings/integration');
  await page.getByLabel('ERP Base URL').fill(`http://127.0.0.1:${erpPort}`);
  await page.getByLabel('认证令牌').fill('erp-e2e-token');
  await page.getByRole('button', { name: '保存配置' }).click();
  await expect(page.getByText('凭证不会再次显示')).toBeVisible();
  await expect(page.getByText('erp-e2e-token')).not.toBeVisible();
  await page.getByRole('button', { name: '测试连接' }).click();
  await expect(page.getByText('ERP 健康检查和资源目录读取成功。')).toBeVisible();
  await expect(page.getByText('materials', { exact: true })).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '01-erp-health-catalog.png'), fullPage: true });

  await page.getByRole('button', { name: '开始同步' }).click();
  await expect(page.getByText('ERP 手动同步已完成。')).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText('ERP 同步历史')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '02-erp-manual-sync-history.png'), fullPage: true });

  const materialPage = await page.request.get(apiUrl('/data/material'), { headers: headersA });
  expect(materialPage.ok(), await materialPage.text()).toBeTruthy();
  expect((await materialPage.json() as { total: number }).total).toBeGreaterThan(0);
  await page.goto('/data/material');
  await expect(page).toHaveURL(/\/data\/material/);
  await expect(page.getByRole('cell', { name: '传感器-0001', exact: true })).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '03-product-material-data-after-erp-sync.png'), fullPage: true });

  // Complete the C1 parent/child set through the saved-config endpoint; this is the same C2 adapter and tenant context.
  const fullSync = await page.request.post(apiUrl('/settings/integrations/erp/sync'), { headers: headersA, data: { values: { types: ['material', 'supplier', 'supplier_material', 'customer', 'order', 'order_line', 'inventory'] } }, timeout: 120_000 });
  expect(fullSync.ok(), await fullSync.text()).toBeTruthy();
  const incident = await page.request.post(apiUrl('/incidents'), { headers: headersA, data: { riskIds: ['risk-erp-e2e-a'], title: 'ERP synced C1 decision', type: 'supplier_shutdown', loss: 0, cost: 0 } });
  expect(incident.ok(), await incident.text()).toBeTruthy();
  const incidentId = (await incident.json() as { id: string }).id;
  const proposal = await page.request.post(apiUrl(`/incidents/${incidentId}/proposals:generate`), { headers: headersA });
  expect(proposal.status(), await proposal.text()).toBe(202);
  const proposalJob = (await proposal.json() as { jobId: string }).jobId;
  let decisionStatus = 'pending';
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const job = await page.request.get(apiUrl(`/jobs/${proposalJob}`), { headers: headersA });
    expect(job.ok(), await job.text()).toBeTruthy();
    decisionStatus = (await job.json() as { status: string }).status;
    if (['succeeded', 'failed'].includes(decisionStatus)) break;
    await page.waitForTimeout(500);
  }
  expect(decisionStatus).toBe('succeeded');

  const tokenB = await loginToken(page, 'erp-admin-b@chainguard.test');
  const headersB = { Authorization: `Bearer ${tokenB}` };
  const bConfig = await page.request.get(apiUrl('/settings/integrations/erp'), { headers: headersB });
  expect((await bConfig.json() as { configured: boolean }).configured).toBe(false);
  const bHistory = await page.request.get(apiUrl('/imports'), { headers: headersB });
  expect((await bHistory.json() as { total: number }).total).toBe(0);

  // Controlled mock failures must not include credentials in the API message.
  const wrongCredential = await page.request.patch(apiUrl('/settings/integrations/erp'), { headers: headersA, data: { values: { baseUrl: `http://127.0.0.1:${erpPort}`, apiKey: 'bad-e2e-secret' } } });
  expect(wrongCredential.ok()).toBeTruthy();
  const authFailure = await page.request.post(apiUrl('/settings/integrations/erp/test'), { headers: headersA });
  expect(authFailure.status()).toBe(502); expect((await authFailure.text())).toContain('认证失败');
  const unavailable = await page.request.patch(apiUrl('/settings/integrations/erp'), { headers: headersA, data: { values: { baseUrl: 'http://127.0.0.1:1' } } });
  expect(unavailable.ok()).toBeTruthy();
  const unavailableTest = await page.request.post(apiUrl('/settings/integrations/erp/test'), { headers: headersA });
  expect(unavailableTest.status()).toBe(502); expect((await unavailableTest.text())).not.toContain('bad-e2e-secret');
});
