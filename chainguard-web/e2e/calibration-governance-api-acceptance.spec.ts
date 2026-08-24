import { readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const __dirname = import.meta.dirname;
import { expect, test, type Page } from '@playwright/test';

const apiPort = Number(process.env.CALIBRATION_API_PORT || 8420);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(process.env.CALIBRATION_EVIDENCE_DIR || '../ChainGuard/output/phase5b-calibration/screenshots');
const password = 'CalibrationUi@2026!';

// 夹具由 ChainGuard/scripts/generate_calibration_e2e_fixture.py 生成并提交进仓库，
// 不在测试里现编——期望值随夹具一起固化，改夹具必须重跑生成脚本。
const fixtureDir = resolve(__dirname, 'fixtures/calibration');
const fixture = (name: string) => readFileSync(resolve(fixtureDir, name));

// 以下常量必须与生成脚本保持一致（脚本顶部同名常量）。
const MAIN_CASES = 120;
const MAIN_FAILURES = MAIN_CASES / 2;
const MAIN_SUCCESSES = MAIN_CASES / 2;
const DRIFT_CASES = 120;

// 第一性原理推导的漂移期望值：
//   确认时基线成功率 = 60 / 120           = 0.5
//   导入 120 条全失败后 = 60 / 240        = 0.25
//   跌幅 = 0.5 - 0.25                    = 0.25 ≥ critical_drop(0.15) → severity=critical
const BASELINE_SUCCESS_RATE = MAIN_SUCCESSES / MAIN_CASES;
const DRIFTED_SUCCESS_RATE = MAIN_SUCCESSES / (MAIN_CASES + DRIFT_CASES);
const EXPECTED_DROP = BASELINE_SUCCESS_RATE - DRIFTED_SUCCESS_RATE;

// 监督式校准准入门（src/supervised_calibration.py）：有效样本 ≥ 80、正负类各 ≥ 40、样本外 AUC ≥ 0.55。
const MIN_AUC = 0.55;

type Session = { token: string };

async function useToken(page: Page, token: string) {
  await page.goto('/user/login');
  await page.context().addCookies([{ name: 'chainguard_token', value: token, url: new URL(page.url()).origin }]);
}

/** 走 C2 的 /imports 通道导入一类数据，等待执行完成。 */
async function importFixture(page: Page, token: string, type: string, file: string) {
  const headers = { Authorization: `Bearer ${token}` };
  const uploaded = await page.request.post(apiUrl(`/imports/upload?type=${type}&mode=structured`), {
    headers,
    multipart: { file: { name: file, mimeType: 'text/csv', buffer: fixture(file) } },
  });
  expect(uploaded.ok(), await uploaded.text()).toBeTruthy();
  const { id } = await uploaded.json() as { id: string };

  expect((await page.request.post(apiUrl(`/imports/${id}/preflight`), { headers, data: {} })).ok()).toBeTruthy();
  const confirmed = await page.request.post(apiUrl(`/imports/${id}/confirm`), {
    headers,
    data: { values: { confirmedType: type, duplicatePolicy: 'merge', onlyValidRows: true } },
  });
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
  expect((await page.request.post(apiUrl(`/imports/${id}/execute`), { headers, data: {} })).status()).toBe(202);

  for (let attempt = 0; attempt < 80; attempt += 1) {
    const body = await (await page.request.get(apiUrl(`/imports/${id}`), { headers })).json() as { status: string };
    if (body.status === 'succeeded') return;
    if (body.status === 'failed') throw new Error(`${type} 导入失败：${JSON.stringify(body)}`);
    await new Promise((done) => setTimeout(done, 250));
  }
  throw new Error(`${type} 导入超时`);
}

async function register(page: Page, suffix: string): Promise<Session> {
  const registered = await page.request.post(apiUrl('/auth/register'), {
    data: { phone: `136${suffix}`, password, companyName: `校准界面验收-${suffix}`, industry: '电子制造', scale: '50-200', ownerRole: 'IT 管理员', plan: 'trial' },
  });
  expect(registered.ok(), await registered.text()).toBeTruthy();
  return await registered.json() as Session;
}

/** 只导历史决策：故意缺事前数据，用于拒绝路径。 */
async function provisionHistoryOnly(page: Page, suffix: string): Promise<Session> {
  const session = await register(page, suffix);
  await importFixture(page, session.token, 'historical_decision', 'historical-decisions.csv');
  await useToken(page, session.token);
  return session;
}

/** 导齐事前数据 + 历史决策：可通过准入门。 */
async function provisionFullDataset(page: Page, suffix: string): Promise<Session> {
  const session = await register(page, suffix);
  // 顺序无关（重建时统一按 event_id / material_id 关联），但按依赖顺序导更易读
  await importFixture(page, session.token, 'material', 'materials.csv');
  await importFixture(page, session.token, 'inventory_snapshot', 'inventory-snapshots.csv');
  await importFixture(page, session.token, 'disruption_event', 'disruption-events.csv');
  await importFixture(page, session.token, 'historical_decision', 'historical-decisions.csv');
  await useToken(page, session.token);
  return session;
}

async function snapshot(page: Page, token: string) {
  const response = await page.request.get(apiUrl('/settings/calibration-governance'), {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return await response.json() as any;
}

test('API 模式 Chromium：校准建议不自动生效，事前特征数据不足时拒绝应用', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  const suffix = String(Date.now()).slice(-8);
  const session = await provisionHistoryOnly(page, suffix);

  await page.goto('/settings/thresholds');
  await expect(page.getByText('数据驱动建议 vs 专家默认值')).toBeVisible();
  await expect(page.getByText('尚未确认，不影响决策')).toBeVisible();
  await expect(page.getByText('有效样本', { exact: true })).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '01-calibration-pending.png'), fullPage: true });

  // 监督式校准要从 disruption_events / inventory_snapshots / materials 重建事前特征，
  // 只导入历史决策的租户重建不出来，确认接口按设计返回 409 CG-2902 并说明缺什么。
  // 这正是本层最关键的行为：没通过样本外验证的权重绝不以"已校准"的名义写入。
  await expect(page.getByText(/未产出数据驱动建议：缺少重建事前特征所需的数据/)).toBeVisible();
  await expect(page.getByText(/disruption_events、inventory_snapshots、materials/).first()).toBeVisible();

  // 接口层同样必须如实报告缺哪几张表，不能只在界面上写。
  const pending = await snapshot(page, session.token);
  expect(pending.supervised.ok).toBe(false);
  expect(pending.supervised.missingTables).toEqual(['disruption_events', 'inventory_snapshots', 'materials']);

  await page.getByRole('button', { name: '人工确认并应用' }).click();
  await page.getByRole('button', { name: '确认应用' }).click();
  // 这句只出现在接口错误提示里（CG-2902），是"确认确实被拒"的证据。
  await expect(page.getByText(/数据驱动校准未通过验证，不能应用/)).toBeVisible();
  // 拒绝之后必须仍停留在未批准状态，不能出现"半应用"。
  await expect(page.getByText('尚未确认，不影响决策')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '02-calibration-refused.png'), fullPage: true });
});

test('API 模式 Chromium：事前数据齐备时，人工确认可走通并落库留痕', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  const suffix = String(Date.now()).slice(-8);
  const session = await provisionFullDataset(page, suffix);

  // 重建结果必须与夹具逐条对应：夹具每条决策都配齐了事件/物料/快照，
  // 因此剔除数应为 0。任何非零剔除都说明导入链路丢了数据，而不是"差不多能用"。
  const ready = await snapshot(page, session.token);
  expect(ready.supervised.reconstruction).toMatchObject({
    sampleSize: MAIN_CASES,
    failureCount: MAIN_FAILURES,
    successCount: MAIN_SUCCESSES,
    excludedTotal: 0,
  });
  expect(ready.supervised.ok).toBe(true);
  // 样本外 AUC 是这组权重可信度的核心证据，必须真的过门槛而不是被跳过。
  expect(ready.supervised.diagnostics.aucOutOfSample).toBeGreaterThanOrEqual(MIN_AUC);
  // 四个因子按夹具设计在高风险档一律更高，因此不应出现"全为负系数"。
  expect(Object.values(ready.supervised.coefficients as Record<string, number>).some((value) => value > 0)).toBeTruthy();

  await page.goto('/settings/thresholds');
  await expect(page.getByText('尚未确认，不影响决策')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '03-calibration-ready.png'), fullPage: true });

  await page.getByRole('button', { name: '人工确认并应用' }).click();
  await page.getByRole('button', { name: '确认应用' }).click();
  await expect(page.getByText('当前已有已批准配置')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '04-calibration-approved.png'), fullPage: true });

  // 确认后阈值与权重都必须落成已批准的租户配置版本，且方法记为监督式校准。
  const approved = await snapshot(page, session.token);
  expect(approved.comparison.active.approved).toBe(true);
  expect(approved.comparison.active.weightsVersion).toBeTruthy();
  expect(approved.comparison.active.thresholdsVersion).toBeTruthy();
  expect(approved.calculation.weightMethod).toBe('logistic_regression_pre_event');
});

test('API 模式 Chromium：确认后成功率跌破阈值触发漂移告警', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  const suffix = String(Date.now()).slice(-8);
  const session = await provisionFullDataset(page, suffix);

  await page.goto('/settings/thresholds');
  await page.getByRole('button', { name: '人工确认并应用' }).click();
  await page.getByRole('button', { name: '确认应用' }).click();
  await expect(page.getByText('当前已有已批准配置')).toBeVisible();

  // 基线只在确认成功时落库（promote_stable），确认前不存在基线。
  const confirmed = await snapshot(page, session.token);
  expect(confirmed.drift.baselineSuccessRate).toBeCloseTo(BASELINE_SUCCESS_RATE, 4);

  // 再导入 120 条全失败决策，复用既有 event_id（同一批事件上的新决策）。
  await importFixture(page, session.token, 'historical_decision', 'historical-decisions-drift.csv');

  // 每次建快照都会往 registry 落一条记录，而漂移阈值在记录数 ≥3 时改按 2σ 计算——
  // 即阈值数值会随页面被打开过几次浮动。但成功率只取基线 a 与漂移后 b 两个值时，
  // σ = d·√(km)/(k+m) 在 k=m 处最大为 d/2，故 2σ ≤ d 恒成立，而判定含等号，
  // 所以 severity=critical 与打开次数无关。下面仍按自洽形式断言阈值，不写死 0.15。
  await page.reload();
  await expect(page.getByText('漂移严重超限')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '05-calibration-drift-alert.png'), fullPage: true });

  const drifted = await snapshot(page, session.token);
  expect(drifted.drift.baselineSuccessRate).toBeCloseTo(BASELINE_SUCCESS_RATE, 4);
  expect(drifted.drift.successRate).toBeCloseTo(DRIFTED_SUCCESS_RATE, 4);
  expect(drifted.drift.successRateDrop).toBeCloseTo(EXPECTED_DROP, 4);
  expect(drifted.drift.severity).toBe('critical');
  expect(drifted.drift.driftDetected).toBe(true);
  // 与实际生效的阈值自洽：阈值本身可能被 registry 方差校准过，不硬编码 0.15。
  expect(drifted.drift.successRateDrop).toBeGreaterThanOrEqual(drifted.drift.thresholds.criticalDrop);

  const notifications = await page.request.get(apiUrl('/notifications'), {
    headers: { Authorization: `Bearer ${session.token}` },
  });
  const items = (await notifications.json() as { data: Array<{ kind: string }> }).data;
  expect(items.some((item) => item.kind === 'drift_detected')).toBeTruthy();
});
