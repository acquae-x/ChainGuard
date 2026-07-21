import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const apiPort = Number(process.env.CALIBRATION_API_PORT || 8420);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(process.env.CALIBRATION_EVIDENCE_DIR || '../ChainGuard/output/phase5b-calibration/screenshots');
const password = 'CalibrationUi@2026!';

function historyCsv(prefix: string, outcome: 'success' | 'failed') {
  const rows = ['case_id,created_at,outcome_status,covered_demand_rate,actual_delay_hours,predicted_delay_hours,actual_cost,predicted_cost,lost_orders,production_downtime_hours,human_rating'];
  for (let index = 0; index < 5; index += 1) rows.push(`${prefix}-${index},2026-07-${String(index + 1).padStart(2, '0')}T00:00:00+00:00,${outcome},${outcome === 'success' ? 0.95 : 0.3},${outcome === 'success' ? 4 : 30},10,${outcome === 'success' ? 1000 : 1500},1000,${outcome === 'success' ? 0 : 2},${outcome === 'success' ? 0 : 8},${outcome === 'success' ? 5 : 2}`);
  return Buffer.from(rows.join('\n'), 'utf8');
}

async function useToken(page: Page, token: string) {
  await page.goto('/user/login');
  await page.context().addCookies([{ name: 'chainguard_token', value: token, url: new URL(page.url()).origin }]);
}

async function importHistory(page: Page, token: string, name: string, csv: Buffer) {
  const headers = { Authorization: `Bearer ${token}` };
  const uploaded = await page.request.post(apiUrl('/imports/upload?type=historical_decision&mode=structured'), { headers, multipart: { file: { name, mimeType: 'text/csv', buffer: csv } } });
  expect(uploaded.ok(), await uploaded.text()).toBeTruthy();
  const { id } = await uploaded.json() as { id: string };
  expect((await page.request.post(apiUrl(`/imports/${id}/preflight`), { headers, data: {} })).ok()).toBeTruthy();
  expect((await page.request.post(apiUrl(`/imports/${id}/confirm`), { headers, data: { values: { confirmedType: 'historical_decision', duplicatePolicy: 'merge', onlyValidRows: true } } })).ok()).toBeTruthy();
  expect((await page.request.post(apiUrl(`/imports/${id}/execute`), { headers, data: {} })).status()).toBe(202);
  for (let index = 0; index < 40; index += 1) {
    const status = await page.request.get(apiUrl(`/imports/${id}`), { headers });
    const body = await status.json() as { status: string };
    if (body.status === 'succeeded') return;
    if (body.status === 'failed') throw new Error(`history import failed: ${JSON.stringify(body)}`);
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 250));
  }
  throw new Error('history import timed out');
}

test('API 模式 Chromium：校准建议须人工确认，漂移超限通知管理员', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  const suffix = String(Date.now()).slice(-8);
  const registered = await page.request.post(apiUrl('/auth/register'), { data: { phone: `136${suffix}`, password, companyName: `校准界面验收-${suffix}`, industry: '电子制造', scale: '50-200', ownerRole: 'IT 管理员', plan: 'trial' } });
  expect(registered.ok(), await registered.text()).toBeTruthy();
  const session = await registered.json() as { token: string };
  await importHistory(page, session.token, `history-success-${suffix}.csv`, historyCsv(`success-${suffix}`, 'success'));
  await useToken(page, session.token);

  await page.goto('/settings/thresholds');
  await expect(page.getByText('数据驱动建议 vs 专家默认值')).toBeVisible();
  await expect(page.getByText('尚未确认，不影响决策')).toBeVisible();
  await expect(page.getByText('有效样本', { exact: true })).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '01-calibration-pending.png'), fullPage: true });
  await page.getByRole('button', { name: '人工确认并应用' }).click();
  await page.getByRole('button', { name: '确认应用' }).click();
  await expect(page.getByText('当前已有已批准配置')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '02-calibration-approved.png'), fullPage: true });

  await importHistory(page, session.token, `history-failed-${suffix}.csv`, historyCsv(`failed-${suffix}`, 'failed'));
  await page.reload();
  await expect(page.getByText('漂移严重超限')).toBeVisible();
  await expect(page.getByText('相对基线变化：下降 50.0%。')).toBeVisible();
  const notifications = await page.request.get(apiUrl('/notifications'), { headers: { Authorization: `Bearer ${session.token}` } });
  expect((await notifications.json() as { data: Array<{ kind: string }> }).data.some((item) => item.kind === 'drift_detected')).toBeTruthy();
  await page.screenshot({ path: resolve(evidenceDir, '03-calibration-drift-alert.png'), fullPage: true });
});
