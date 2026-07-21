import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const apiPort = Number(process.env.CALIBRATION_API_PORT || 8420);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(process.env.CALIBRATION_EVIDENCE_DIR || '../ChainGuard/output/phase5b-calibration/screenshots');
const password = 'CalibrationUi@2026!';

// 监督式校准的准入门（src/supervised_calibration.py）要求有效样本 ≥ 80、
// 正负类各 ≥ 40、样本外 AUC ≥ 0.55，否则确认接口按设计返回 409 CG-2902。
// 因此批准前必须先喂够两类样本，不能像早期夹具那样只给 5 条单一类别。
const CLASS_ROWS = 50;

function historyCsv(prefix: string, outcome: 'success' | 'failed', rowCount = CLASS_ROWS) {
  const rows = ['case_id,created_at,outcome_status,covered_demand_rate,actual_delay_hours,predicted_delay_hours,actual_cost,predicted_cost,lost_orders,production_downtime_hours,human_rating'];
  for (let index = 0; index < rowCount; index += 1) {
    const day = String((index % 28) + 1).padStart(2, '0');
    rows.push(`${prefix}-${index},2026-07-${day}T00:00:00+00:00,${outcome},${outcome === 'success' ? 0.95 : 0.3},${outcome === 'success' ? 4 : 30},10,${outcome === 'success' ? 1000 : 1500},1000,${outcome === 'success' ? 0 : 2},${outcome === 'success' ? 0 : 8},${outcome === 'success' ? 5 : 2}`);
  }
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

async function registerWithHistory(page: Page, suffix: string) {
  const registered = await page.request.post(apiUrl('/auth/register'), { data: { phone: `136${suffix}`, password, companyName: `校准界面验收-${suffix}`, industry: '电子制造', scale: '50-200', ownerRole: 'IT 管理员', plan: 'trial' } });
  expect(registered.ok(), await registered.text()).toBeTruthy();
  const session = await registered.json() as { token: string };
  // 成功/失败各 50 条：满足样本量与类别均衡，把拒绝原因收敛到"缺实体数据"这一项。
  await importHistory(page, session.token, `history-success-${suffix}.csv`, historyCsv(`success-${suffix}`, 'success'));
  await importHistory(page, session.token, `history-failed-${suffix}.csv`, historyCsv(`base-failed-${suffix}`, 'failed'));
  await useToken(page, session.token);
  return session;
}

test('API 模式 Chromium：校准建议不自动生效，事前特征数据不足时拒绝应用', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  const suffix = String(Date.now()).slice(-8);
  await registerWithHistory(page, suffix);

  await page.goto('/settings/thresholds');
  await expect(page.getByText('数据驱动建议 vs 专家默认值')).toBeVisible();
  await expect(page.getByText('尚未确认，不影响决策')).toBeVisible();
  await expect(page.getByText('有效样本', { exact: true })).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '01-calibration-pending.png'), fullPage: true });

  // 监督式校准要从 disruption_events / inventory_snapshots / materials 重建事前特征，
  // 只导入历史决策的租户重建不出来，确认接口按设计返回 409 CG-2902 并说明缺什么。
  // 这正是本层最关键的行为：没通过样本外验证的权重绝不以"已校准"的名义写入。
  // 面板在确认前就写明了为什么产不出建议、缺哪几张表。
  await expect(page.getByText(/未产出数据驱动建议：缺少重建事前特征所需的数据/)).toBeVisible();
  await expect(page.getByText(/disruption_events、inventory_snapshots、materials/).first()).toBeVisible();

  await page.getByRole('button', { name: '人工确认并应用' }).click();
  await page.getByRole('button', { name: '确认应用' }).click();
  // 这句只出现在接口错误提示里（CG-2902），是"确认确实被拒"的证据。
  await expect(page.getByText(/数据驱动校准未通过验证，不能应用/)).toBeVisible();
  // 拒绝之后必须仍停留在未批准状态，不能出现"半应用"。
  await expect(page.getByText('尚未确认，不影响决策')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '02-calibration-refused.png'), fullPage: true });
});

// 漂移验收依赖"已批准的基线成功率"，而基线只在确认成功时落库。确认要走通就需要一个
// 既有实体数据（disruption_events / inventory_snapshots / materials）、历史决策又能
// 关联到真实中断事件的租户——当前没有能造出这种租户的 provisioning 脚本，
// 空租户 + 一张历史 CSV 的老夹具在监督式校准准入门下永远过不去。
// 补上该脚本后再启用本用例，届时期望值需按实际基线重算（不再是旧的"下降 50.0%"）。
test.fixme('API 模式 Chromium：漂移超限通知管理员（阻塞：缺少带实体数据的租户 provisioning）', async ({ page }) => {
  const suffix = String(Date.now()).slice(-8);
  const session = await registerWithHistory(page, suffix);
  await page.goto('/settings/thresholds');
  await page.getByRole('button', { name: '人工确认并应用' }).click();
  await page.getByRole('button', { name: '确认应用' }).click();
  await expect(page.getByText('当前已有已批准配置')).toBeVisible();

  await importHistory(page, session.token, `history-drift-${suffix}.csv`, historyCsv(`drift-${suffix}`, 'failed', CLASS_ROWS * 2));
  await page.reload();
  await expect(page.getByText('漂移严重超限')).toBeVisible();
  const notifications = await page.request.get(apiUrl('/notifications'), { headers: { Authorization: `Bearer ${session.token}` } });
  expect((await notifications.json() as { data: Array<{ kind: string }> }).data.some((item) => item.kind === 'drift_detected')).toBeTruthy();
  await page.screenshot({ path: resolve(evidenceDir, '03-calibration-drift-alert.png'), fullPage: true });
});
