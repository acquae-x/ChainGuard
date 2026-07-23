import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

// A03 实时风险解释：API 模式 Chromium 真实产品界面验收。
// 覆盖 E1 重算→解释、E2 当前值/阈值、E3 证据跳转、E4 数据不足降级、
// E5 已消除/已忽略快照、E6 跨租户隔离、E7 权限、E8 忽略后重扫不复活、E9 外部来源标注。
//
// 选择器纪律：一律按 data-testid 唯一定位。
// 同一数值会同时出现在「结论」与「触发规则」两处（结论"风险指数 78.75"、
// 规则"库存风险指数 78.75 超过触发阈值 70"），任何文案子串匹配都会命中多个元素
// 而触发 Playwright strict mode 失败——那是脚本缺陷，不是产品缺陷。

const apiPort = Number(process.env.RISK_EXPLAIN_API_PORT || 8440);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(process.env.RISK_EXPLAIN_EVIDENCE_DIR || '../ChainGuard/output/phase5b-a03/screenshots');
const password = 'RiskExplainE2E@2026!';

const MANAGER_A = 'a03-real-a@chainguard.test';
const VIEWER_A = 'a03-viewer-a@chainguard.test';
const MANAGER_B = 'a03-real-b@chainguard.test';

const MATERIAL_A = 'A03主控芯片';
const WAREHOUSE_A = 'A03主控芯片专用仓';

async function login(page: Page, account: string) {
  await page.context().clearCookies();
  await page.goto('/user/login');
  await page.locator('#account').fill(account);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: /登.*录/ }).first().click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function authHeaders(page: Page) {
  const value = (await page.context().cookies()).find((item) => item.name === 'chainguard_token')?.value;
  expect(value, '登录后应拿到 chainguard_token').toBeTruthy();
  return { Authorization: `Bearer ${value}` };
}

/** 抽屉内容的唯一根节点；避免与 antd Modal 同为 role=dialog 而互相干扰。 */
const drawerOf = (page: Page) => page.getByTestId('risk-explanation-drawer');

async function openExplanation(page: Page, rowPattern: RegExp) {
  await page.getByRole('row').filter({ hasText: rowPattern }).first()
    .getByRole('button', { name: '风险解释' }).click();
  const drawer = drawerOf(page);
  await expect(drawer).toBeVisible();
  return drawer;
}

async function rescanFromUi(page: Page) {
  await page.goto('/risk/overview');
  await page.getByRole('button', { name: '重新扫描风险' }).click();
  await expect(page.getByText(/重新扫描完成/)).toBeVisible();
}

test('A03：真实数据风险解释、证据追溯、数据不足降级、权限与跨租户隔离', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 960 });

  // ── E1：真实租户重算 → 风险列表出现由实体算出的风险 ──────────────────────
  await login(page, MANAGER_A);
  await page.goto('/risk/overview');
  await expect(page.getByRole('button', { name: '重新扫描风险' })).toBeVisible();
  await page.getByRole('button', { name: '重新扫描风险' }).click();
  await expect(page.getByText(/重新扫描完成：新增 1/)).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '01-rescan-done.png'), fullPage: true });

  await page.goto('/risk/list');

  // 先拿到风险编号再定位行：objectName「A03主控芯片」是外部录入风险
  // 「A03主控芯片供应商」的子串，用物料名做行筛选会同时命中两行。
  const headers = await authHeaders(page);
  const listed = await page.request.get(apiUrl('/risks?pageSize=50'), { headers });
  const risks = (await listed.json() as { data: { id: string; code: string; objectName: string; type: string }[] }).data;
  const target = risks.find((item) => item.type === '库存' && item.objectName === MATERIAL_A);
  expect(target, '重算应产出该物料的库存风险').toBeTruthy();
  const targetRow = new RegExp(target!.code);
  await expect(page.getByRole('row').filter({ hasText: targetRow })).toHaveCount(1);

  // ── E2：当前值/阈值可读，且界面数值逐位等于接口数值 ──────────────────────
  const drawer = await openExplanation(page, targetRow);
  await expect(drawer.getByTestId('risk-explanation-warning-level')).toHaveText('红色预警');
  await expect(drawer.getByTestId('risk-explanation-threshold-source')).toHaveText('阈值来源：专家默认');
  await expect(drawer.getByTestId('risk-driver-shortage_urgency-current')).toHaveText('库存支撑小时数：15 小时');
  await expect(drawer.getByTestId('risk-driver-shortage_urgency-threshold')).toHaveText('黄线 48 / 红线 24（低于红线）');

  const explained = await page.request.get(apiUrl(`/risks/${target!.id}/explanation`), { headers });
  const body = await explained.json() as any;
  expect(body.available).toBe(true);
  expect(body.verdict.triggerThreshold).toBe(70);
  // 唯一定位后按精确文本比对：界面显示的就是接口返回的那个数，前端没有另算。
  await expect(drawer.getByTestId('risk-explanation-index')).toHaveText(String(body.verdict.riskIndex));
  await expect(drawer.getByTestId('risk-explanation-threshold')).toHaveText(String(body.verdict.triggerThreshold));
  await page.screenshot({ path: resolve(evidenceDir, '02-explanation-thresholds.png'), fullPage: true });

  // ── E3：证据来源可跳转到对应资料页 ──────────────────────────────────────
  const inventoryEvidence = body.evidence.find((item: any) => item.entity === 'inventory');
  expect(inventoryEvidence, '证据里应有库存实体').toBeTruthy();
  await expect(drawer.getByTestId(`risk-evidence-inventory-${inventoryEvidence.id}`)).toContainText(WAREHOUSE_A);
  await page.screenshot({ path: resolve(evidenceDir, '03-evidence-cards.png'), fullPage: true });
  await drawer.getByTestId(`risk-evidence-link-inventory-${inventoryEvidence.id}`).click();
  await expect(page).toHaveURL(/\/data\/inventory/);
  await page.screenshot({ path: resolve(evidenceDir, '04-evidence-jump.png'), fullPage: true });

  // ── E4：数据不足降级——缺库存物料如实跳过，不编造分数 ────────────────────
  const rescan = await page.request.post(apiUrl('/risks/recompute'), { headers });
  const outcome = await rescan.json() as { skipped: { materialId: string; code: string }[] };
  expect(outcome.skipped.some((item) => item.materialId === 'MCU-NOSTOCK' && item.code === 'CG-2513')).toBeTruthy();
  await page.goto('/risk/list');
  // 缺库存的物料不会产出风险行——不产生"无风险"记录，也不产生假风险。
  await expect(page.getByRole('row').filter({ hasText: /A03无库存物料/ })).toHaveCount(0);
  const afterScan = await page.request.get(apiUrl('/risks?pageSize=50'), { headers });
  const nostockRisk = (await afterScan.json() as { data: { objectName: string }[] }).data
    .find((item) => item.objectName.includes('A03无库存物料'));
  expect(nostockRisk, '缺库存物料不应产出风险行').toBeFalsy();

  // ── E8：忽略后重扫不复活 ────────────────────────────────────────────────
  await page.goto('/risk/list');
  await page.getByRole('row').filter({ hasText: targetRow })
    .getByRole('button', { name: '忽略' }).click();
  const ignoreModal = page.getByRole('dialog').filter({ hasText: '忽略风险' });
  await ignoreModal.getByLabel('忽略理由').fill('E2E 验收：忽略后重扫不应复活');
  await ignoreModal.getByRole('button', { name: /确\s*定/ }).click();
  await expect(page.getByText('已忽略风险并写入审计日志')).toBeVisible();

  await rescanFromUi(page);
  await page.goto('/risk/list');
  await expect(page.getByRole('row').filter({ hasText: targetRow })).toContainText('已忽略');
  await page.screenshot({ path: resolve(evidenceDir, '05-ignored-not-resurrected.png'), fullPage: true });

  // ── E5：已忽略风险的解释显示为历史快照，而不是拿当前数据现编 ──────────────
  const closedDrawer = await openExplanation(page, targetRow);
  await expect(closedDrawer.getByTestId('risk-explanation-unavailable-title'))
    .toHaveText('当前无法生成实时解释（以下为历史快照）');
  await expect(closedDrawer.getByTestId('risk-explanation-code')).toHaveText('错误码：CG-A031');
  await expect(closedDrawer.getByTestId('risk-explanation-snapshot')).toBeVisible();
  // 快照态不得渲染实时结论区。
  await expect(closedDrawer.getByTestId('risk-explanation-index')).toHaveCount(0);
  await expect(closedDrawer.getByTestId('risk-explanation-drivers')).toHaveCount(0);
  await page.screenshot({ path: resolve(evidenceDir, '06-closed-risk-snapshot.png'), fullPage: true });

  // ── E7：无 risk:manage 看不到也调不动重扫，但解释仍可看 ────────────────────
  await login(page, VIEWER_A);
  await page.goto('/risk/overview');
  await expect(page.getByRole('button', { name: '重新扫描风险' })).toHaveCount(0);
  const viewerHeaders = await authHeaders(page);
  const forbidden = await page.request.post(apiUrl('/risks/recompute'), { headers: viewerHeaders, failOnStatusCode: false });
  expect(forbidden.status()).toBe(403);
  const viewerExplain = await page.request.get(apiUrl(`/risks/${target!.id}/explanation`), { headers: viewerHeaders });
  expect(viewerExplain.status()).toBe(200);
  await page.screenshot({ path: resolve(evidenceDir, '07-viewer-no-rescan.png'), fullPage: true });

  // ── E6：跨租户既看不到、也访问不到 ──────────────────────────────────────
  await login(page, MANAGER_B);
  await page.goto('/risk/list');
  await expect(page.getByText(MATERIAL_A)).toHaveCount(0);
  await expect(page.getByText(WAREHOUSE_A)).toHaveCount(0);
  const tenantBHeaders = await authHeaders(page);
  const denied = await page.request.get(apiUrl(`/risks/${target!.id}/explanation`), { headers: tenantBHeaders, failOnStatusCode: false });
  expect(denied.status()).toBe(404);
  const deniedText = await denied.text();
  expect(deniedText).not.toContain(MATERIAL_A);
  expect(deniedText).not.toContain(WAREHOUSE_A);
  await page.screenshot({ path: resolve(evidenceDir, '08-cross-tenant-isolated.png'), fullPage: true });
});

test('A03：外部录入型风险从界面上标注来源，不伪造指标推导（E9）', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await login(page, MANAGER_A);
  await page.goto('/risk/list');

  // seed 落的 origin=external_event 风险：供应商停产只能由外部告知，算不出来。
  const drawer = await openExplanation(page, /A03主控芯片供应商/);
  await expect(drawer.getByTestId('risk-explanation-declared-origin')).toHaveText('来源：外部事件录入');
  await expect(drawer.getByTestId('risk-explanation-declared-notice')).toHaveText('等级为申报值，非系统计算');
  await expect(drawer).toContainText('供应商电话通知');
  await expect(drawer.getByTestId('risk-limitation-CG-A034')).toBeVisible();
  // 关键：不得渲染"等级由指标算出"那一套。
  await expect(drawer.getByTestId('risk-explanation-index')).toHaveCount(0);
  await expect(drawer.getByTestId('risk-explanation-threshold-source')).toHaveCount(0);
  // 但"它驱动了什么"是实时算的。
  await expect(drawer.getByTestId('risk-explanation-driven-impact')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '09-external-origin-declared.png'), fullPage: true });

  // 该风险不属于重算来源，重扫前后必须逐字段不变（B21 的界面侧印证）。
  const headers = await authHeaders(page);
  const before = await (await page.request.get(apiUrl('/risks/risk-a03-external'), { headers })).json();
  await page.request.post(apiUrl('/risks/recompute'), { headers });
  const after = await (await page.request.get(apiUrl('/risks/risk-a03-external'), { headers })).json();
  expect(after.score).toBe(before.score);
  expect(after.level).toBe(before.level);
  expect(after.rule).toBe(before.rule);
});
