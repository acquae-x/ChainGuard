import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

// A04 影响范围完整版：API 模式 Chromium 真实产品界面验收。
// 覆盖 E1 事件直接影响、E2 间接影响可辨识、E3 跳转、E4 风险侧影响范围、
// E5 空数据降级、E6 跨租户隔离、E7 脱敏、E8 权限。
//
// 选择器纪律（承 A03 的教训）：一律按 data-testid 唯一定位。
// 实体名之间存在超串关系（「A04主控芯片」是「A04主控芯片供应商」的子串），
// 任何文案子串匹配都可能命中多个元素并触发 strict mode——那是脚本缺陷，不是产品缺陷。

const apiPort = Number(process.env.IMPACT_SCOPE_API_PORT || 8442);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(
  process.env.IMPACT_SCOPE_EVIDENCE_DIR || '../ChainGuard/output/phase5b-a04/screenshots',
);
const password = 'ImpactScopeE2E@2026!';

const MANAGER_A = 'a04-real-a@chainguard.test';
const BUYER_A = 'a04-buyer-a@chainguard.test';
const NO_INCIDENT_A = 'a04-norisk-a@chainguard.test';
const MANAGER_B = 'a04-real-b@chainguard.test';

const INCIDENT_A = 'inc-a04-MCU-A04';
const RISK_A = 'risk-a04-MCU-A04';
const RISK_LONELY = 'risk-a04-lonely';
const SUPPLIER_A = 'SUP-MCU-A04';
const CUSTOMER_A = 'CUS-MCU-A04';
const SIBLING_A = 'MCU-A04-SIB';

// 租户 B 的实体名，用于隔离断言：它们绝不能出现在租户 A 的任何页面上。
const TENANT_B_NAMES = ['B租户专属主控芯片', 'B租户专属封测厂', 'B租户专属整机客户', 'B租户专属上海一仓'];

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

/** 展开某个实体分组，返回该组的组头节点。 */
async function expandGroup(page: Page, prefix: string, entityType: string) {
  const header = page.getByTestId(`${prefix}-group-${entityType}`);
  await expect(header).toBeVisible();
  await header.click();
  return header;
}

test('A04：事件与风险影响范围、直接/间接、跳转、降级、脱敏与跨租户隔离', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  const shot = (name: string) => page.screenshot({ path: resolve(evidenceDir, `${name}.png`), fullPage: true });

  // ── E1：事件影响范围，直接影响可见且计数为真实实体行数 ──────────────────
  await login(page, MANAGER_A);
  await page.goto(`/incident/${INCIDENT_A}?tab=impact`);

  const incidentScope = page.getByTestId('incident-impact-scope');
  await expect(incidentScope).toBeVisible();
  // 总计与分组计数来自后端，界面不得自己算
  const apiScope = await (await page.request.get(apiUrl(`/incidents/${INCIDENT_A}/impact`), {
    headers: await authHeaders(page),
  })).json();
  expect(apiScope.available).toBe(true);
  await expect(page.getByTestId('incident-impact-scope-total')).toHaveText(String(apiScope.summary.total));
  await expect(page.getByTestId('incident-impact-scope-direct-total')).toContainText(String(apiScope.summary.direct));
  await expect(page.getByTestId('incident-impact-scope-indirect-total')).toContainText(String(apiScope.summary.indirect));

  // 三条库存行 / 两个仓库 / 一个供应商 / 一张未关闭订单 —— 与 seed 的实体行一一对应
  await expect(page.getByTestId('incident-impact-scope-group-inventory-counts')).toContainText('直接 3');
  await expect(page.getByTestId('incident-impact-scope-group-warehouse-counts')).toContainText('直接 2');
  await expect(page.getByTestId('incident-impact-scope-group-supplier-counts')).toContainText('直接 1');
  await expect(page.getByTestId('incident-impact-scope-group-order-counts')).toContainText('直接 1');
  await shot('E1-incident-impact-scope-overview');

  await expandGroup(page, 'incident-impact-scope', 'supplier');
  await expect(page.getByTestId(`incident-impact-scope-item-supplier-${SUPPLIER_A}`)).toHaveText('A04封测厂');
  await expect(page.getByTestId(`incident-impact-scope-degree-supplier-${SUPPLIER_A}`)).toHaveText('直接');
  await expect(page.getByTestId(`incident-impact-scope-relation-supplier-${SUPPLIER_A}`)).toHaveText('为受影响物料供货');

  // 任务：由 tasks.incident_id 真实外键带出
  await expandGroup(page, 'incident-impact-scope', 'task');
  await expect(page.getByTestId('incident-impact-scope-item-task-task-a04-MCU-A04')).toBeVisible();
  await shot('E1b-incident-impact-scope-supplier-and-task');

  // ── E2：间接影响可辨识（客户经由订单、兄弟物料经由共用供应商）────────────
  await expandGroup(page, 'incident-impact-scope', 'customer');
  await expect(page.getByTestId(`incident-impact-scope-degree-customer-${CUSTOMER_A}`)).toHaveText('间接');
  await expect(page.getByTestId(`incident-impact-scope-relation-customer-${CUSTOMER_A}`)).toHaveText('经由订单关联的客户');

  await expandGroup(page, 'incident-impact-scope', 'material');
  await expect(page.getByTestId(`incident-impact-scope-degree-material-${SIBLING_A}`)).toHaveText('间接');
  await expect(page.getByTestId(`incident-impact-scope-relation-material-${SIBLING_A}`)).toHaveText('与受影响物料共用供应商');
  // 已关闭订单被排除这件事必须写在界面上
  await expect(page.getByTestId('incident-impact-scope-limitation-CG-A045')).toContainText('1 条已关闭订单');
  await expect(page.getByTestId('incident-impact-scope-limitation-CG-A042')).toContainText('没有独立的仓库主数据');
  await shot('E2-indirect-impact-and-limitations');

  // ── E3：跳转到真实业务对象资料页 ───────────────────────────────────────
  await expandGroup(page, 'incident-impact-scope', 'supplier');
  await page.getByTestId(`incident-impact-scope-link-supplier-${SUPPLIER_A}`).click();
  await expect(page).toHaveURL(new RegExp(`/data/supplier\\?id=${SUPPLIER_A}`));
  await shot('E3-jump-to-supplier-page');

  // ── E4：风险侧影响范围（解释抽屉第五段），与事件侧同构 ──────────────────
  await page.goto('/risk/list');
  await page.getByRole('row').filter({ hasText: 'RISK-A04-MCU-A04' }).first()
    .getByRole('button', { name: '风险解释' }).click();
  const riskScope = page.getByTestId('risk-impact-scope');
  await expect(riskScope).toBeVisible();
  await expandGroup(page, 'risk-impact-scope', 'supplier');
  await expect(page.getByTestId(`risk-impact-scope-item-supplier-${SUPPLIER_A}`)).toHaveText('A04封测厂');
  await shot('E4-risk-drawer-impact-scope');

  // ── E5：空数据降级——零关联物料必须说"范围有限"，页面上不得出现编造实体 ──
  await page.goto('/risk/list');
  await page.getByRole('row').filter({ hasText: 'RISK-A04-LONELY' }).first()
    .getByRole('button', { name: '风险解释' }).click();
  await expect(page.getByTestId('risk-impact-scope-limitation-CG-A041')).toBeVisible();
  await expect(page.getByTestId('risk-impact-scope-total')).toHaveText('1');   // 只有起点物料自己
  // 空态文案与明细表一样挂在 Collapse children 上，按需展开才挂载——先展开再断言，
  // 否则断言的是「面板没展开」而不是「组内没数据」。
  await expandGroup(page, 'risk-impact-scope', 'supplier');
  await expect(page.getByTestId('risk-impact-scope-empty-supplier')).toBeVisible();
  await expandGroup(page, 'risk-impact-scope', 'order');
  await expect(page.getByTestId('risk-impact-scope-empty-order')).toBeVisible();
  // 关键：孤立风险的抽屉里不能出现另一条风险的实体
  await expect(page.locator('body')).not.toContainText('A04封测厂');
  await shot('E5-empty-data-degradation');

  // ── E6：跨租户隔离 ─────────────────────────────────────────────────────
  await login(page, MANAGER_B);
  const headersB = await authHeaders(page);
  const crossRisk = await page.request.get(apiUrl(`/risks/${RISK_A}/impact-scope`), { headers: headersB });
  expect(crossRisk.status()).toBe(404);
  const crossIncident = await page.request.get(apiUrl(`/incidents/${INCIDENT_A}/impact`), { headers: headersB });
  expect(crossIncident.status()).toBe(404);
  // 连存在性都不该泄露：响应体里不能出现租户 A 的任何实体标识
  for (const body of [await crossRisk.text(), await crossIncident.text()]) {
    for (const token of [SUPPLIER_A, CUSTOMER_A, 'A04封测厂', 'A04主控芯片']) {
      expect(body).not.toContain(token);
    }
  }

  await page.goto('/incident/inc-a04-MCU-B04?tab=impact');
  await expect(page.getByTestId('incident-impact-scope')).toBeVisible();
  const bodyText = await page.locator('body').innerText();
  for (const token of ['A04封测厂', 'A04主控芯片', 'A04整机客户', 'A04上海一仓']) {
    expect(bodyText, `租户 B 页面不应出现租户 A 的实体：${token}`).not.toContain(token);
  }
  // 反向确认租户 B 看得到自己的数据，避免"什么都没渲染"也能通过断言
  for (const token of TENANT_B_NAMES.slice(0, 1)) {
    expect(bodyText).toContain(token);
  }
  await shot('E6-cross-tenant-isolation');

  // ── E7：脱敏——buyer 无 field:*:view，金额与客户等级必须是 *** ──────────
  await login(page, BUYER_A);
  await page.goto(`/incident/${INCIDENT_A}?tab=impact`);
  await expandGroup(page, 'incident-impact-scope', 'order');
  await expandGroup(page, 'incident-impact-scope', 'customer');
  const maskedText = await page.getByTestId('incident-impact-scope').innerText();
  expect(maskedText).toContain('***');
  // 真实金额与客户等级一个都不能漏出来
  expect(maskedText).not.toContain('1800000');
  expect(maskedText).not.toContain('1,800,000');
  expect(maskedText).not.toContain('180000');
  expect(maskedText).not.toMatch(/客户等级：A\b/);
  await shot('E7-field-masking-for-buyer');

  // ── E8：权限——无 incident:view 时端点 403，界面不渲染任何分组 ───────────
  await login(page, NO_INCIDENT_A);
  const forbidden = await page.request.get(apiUrl(`/incidents/${INCIDENT_A}/impact`), {
    headers: await authHeaders(page),
  });
  expect(forbidden.status()).toBe(403);
  await page.goto(`/incident/${INCIDENT_A}?tab=impact`);
  await expect(page.getByTestId('incident-impact-scope-group-supplier')).toHaveCount(0);
  await shot('E8-permission-denied');
});
