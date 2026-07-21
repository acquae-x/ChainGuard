import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

// C02/C03 供应链节点健康：API 模式 Chromium 真实产品界面验收。
// 覆盖 E1 管理者概览、E2 筛选、E3 异常原因可读、E4 跳转、E5 一线「我的节点」角色差异、
// E6 角色无对口类型、E7 空数据降级、E8 跨租户隔离、E9 脱敏、E10 窄屏。
//
// 选择器纪律（承 A03/A04 的教训）：一律按 data-testid 唯一定位。
// 实体名之间存在超串关系，任何文案子串匹配都可能命中多个元素并触发 strict mode。

const apiPort = Number(process.env.NODE_HEALTH_API_PORT || 8444);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(
  process.env.NODE_HEALTH_EVIDENCE_DIR || '../ChainGuard/output/phase5b-c02-c03/screenshots',
);
const password = 'NodeHealthE2E@2026!';

const MANAGER_A = 'c02-manager-a@chainguard.test';
const WAREHOUSE_A = 'c02-warehouse-a@chainguard.test';
const BUYER_A = 'c02-buyer-a@chainguard.test';
const PLANNER_A = 'c02-planner-a@chainguard.test';
const SALES_A = 'c02-sales-a@chainguard.test';
const BOSS_A = 'c02-boss-a@chainguard.test';
const MANAGER_B = 'c02-manager-b@chainguard.test';
const MANAGER_EMPTY = 'c02-manager-empty@chainguard.test';

const MAT_CRIT = 'MAT-C02A-CRIT';
const MAT_BARE = 'MAT-C02A-BARE';
const WH_A = 'WH-C02A-A';
const WH_B = 'WH-C02A-B';
const SUP_STOP = 'SUP-C02A-STOP';
const SUP_OK = 'SUP-C02A-OK';
const ORDER_LATE = 'SO-C02A-LATE';
const ORDER_DONE = 'SO-C02A-DONE';

// 租户 B 的实体名：绝不能出现在租户 A 的任何页面上。
const TENANT_B_NAMES = [
  'B租户专属主控芯片', 'B租户专属停产封测厂', 'B租户专属整机客户', 'B租户专属一号仓',
];

// /auth/login 是 5 次/分钟的 IP 限流（src/webapi/routers/auth.py:43）。本用例要覆盖
// 8 个角色，必然撞限流。这里自行按同一窗口配额排队等待，而不是去放宽生产端的限流——
// 限流是真实的安全约束，为了跑通验收把它调松就是在测一个不存在的系统。
const LOGIN_WINDOW_MS = 60_000;
const LOGIN_QUOTA = 5;
const loginStamps: number[] = [];

async function waitForLoginQuota() {
  for (;;) {
    const now = Date.now();
    while (loginStamps.length && now - loginStamps[0] >= LOGIN_WINDOW_MS) loginStamps.shift();
    if (loginStamps.length < LOGIN_QUOTA) {
      loginStamps.push(now);
      return;
    }
    const waitMs = LOGIN_WINDOW_MS - (now - loginStamps[0]) + 2_000;
    console.log(`[限流排队] 等待 ${Math.ceil(waitMs / 1000)}s 后继续登录`);
    await sleep(waitMs);
  }
}

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));

async function attemptLogin(page: Page, account: string) {
  await page.context().clearCookies();
  await page.goto('/user/login');
  await page.locator('#account').fill(account);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: /登.*录/ }).first().click();
  await page.waitForURL(/\/dashboard$/, { timeout: 15_000 }).catch(() => undefined);
  return /\/dashboard$/.test(page.url());
}

// 限流窗口的内部实现是服务端细节，不去猜；主动排队之外再兜一层"整窗等待后重试"。
async function login(page: Page, account: string) {
  await waitForLoginQuota();
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    if (await attemptLogin(page, account)) return;
    console.log(`[限流重试] ${account} 第 ${attempt} 次未登入，整窗等待后重试`);
    loginStamps.length = 0;
    await sleep(LOGIN_WINDOW_MS + 5_000);
  }
  await expect(page, `${account} 连续三次登录失败`).toHaveURL(/\/dashboard$/);
}

async function authHeaders(page: Page) {
  const value = (await page.context().cookies()).find((item) => item.name === 'chainguard_token')?.value;
  expect(value, '登录后应拿到 chainguard_token').toBeTruthy();
  return { Authorization: `Bearer ${value}` };
}

async function apiJson(page: Page, path: string) {
  const response = await page.request.get(apiUrl(path), { headers: await authHeaders(page) });
  expect(response.status(), `${path} 应返回 200`).toBe(200);
  return response.json();
}

test('C02/C03：节点健康概览、筛选、原因、跳转、角色范围、降级、隔离与脱敏', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1200 });
  const shot = (name: string) =>
    page.screenshot({ path: resolve(evidenceDir, `${name}.png`), fullPage: true });

  // ── E1：管理者概览，四档计数与后端逐值一致 ──────────────────────────────
  await login(page, MANAGER_A);
  const panel = page.getByTestId('node-health');
  await expect(panel).toBeVisible();

  const api = await apiJson(page, '/dashboard/node-health?pageSize=50');
  expect(api.available, '租户 A 有真实数据，概览必须可用').toBe(true);
  for (const level of ['critical', 'warning', 'healthy', 'unknown']) {
    await expect(
      page.getByTestId(`node-health-count-${level}-value`),
      `${level} 计数必须来自后端，不得由界面另算一遍`,
    ).toHaveText(String(api.summary[level]));
  }
  // 四类节点全部出现，包括计数为 0 的类型
  for (const nodeType of ['material', 'warehouse', 'supplier', 'order']) {
    await expect(page.getByTestId(`node-health-type-${nodeType}`)).toBeVisible();
  }
  // 数据不足单独成列：MAT-BARE 不得被算成健康
  await expect(page.getByTestId(`node-health-health-material-${MAT_BARE}`)).toHaveText('数据不足');
  // 已交付订单不出现在任何节点行里
  await expect(page.getByTestId(`node-health-node-order-${ORDER_DONE}`)).toHaveCount(0);
  await shot('E1-manager-node-health-overview');

  // ── E3：异常原因可读——观测值、阈值与判据来源都写在界面上 ────────────────
  const critReason = page.getByTestId(
    `node-health-reason-material-${MAT_CRIT}-support_hours_below_red`,
  );
  await expect(critReason).toContainText('库存支撑');
  await expect(critReason).toContainText('红线');
  await expect(critReason, '阈值来源必须可见（专家默认值 or 本租户校准值）').toContainText('判据来源');
  // 停产供应商回显 status 原值
  await expect(
    page.getByTestId(`node-health-reason-supplier-${SUP_STOP}-supplier_status_disrupted`),
  ).toContainText('停产');
  // 传播型结论必须指得回来源物料
  await expect(
    page.getByTestId(`node-health-reason-supplier-${SUP_OK}-supplies_critical_material`),
  ).toBeVisible();
  // 逾期订单是纯事实
  await expect(
    page.getByTestId(`node-health-reason-order-${ORDER_LATE}-delivery_overdue`),
  ).toContainText('承诺交期');
  // 恒常声明：非物料节点不是独立评分模型
  await expect(page.getByTestId('node-health-limitation-CG-C024')).toContainText('不是独立评分模型');
  await expect(page.getByTestId('node-health-limitation-CG-C023')).toContainText('仓库');
  await shot('E3-node-health-reasons-and-limitations');

  // ── E2：筛选——「异常」+「供应商」后列表只剩异常供应商 ────────────────────
  await page.getByTestId('node-health-filter-type').locator('input').first().click();
  await page.getByTitle('供应商', { exact: true }).click();
  await page.getByTestId('node-health-filter-health').locator('input').first().click();
  await page.getByTitle('异常', { exact: true }).click();
  await expect(page.getByTestId(`node-health-node-supplier-${SUP_STOP}`)).toBeVisible();
  // 「可用」供应商是 warning，被筛掉；物料行也不该再出现
  await expect(page.getByTestId(`node-health-node-supplier-${SUP_OK}`)).toHaveCount(0);
  await expect(page.getByTestId(`node-health-node-material-${MAT_CRIT}`)).toHaveCount(0);
  const filtered = await apiJson(page, '/dashboard/node-health?nodeType=supplier&health=critical');
  expect(filtered.nodes.every((node: any) => node.health === 'critical')).toBe(true);
  await shot('E2-node-health-filter-critical-supplier');

  // ── E4：跳转落在真实资料页 ─────────────────────────────────────────────
  await page.reload();
  await expect(page.getByTestId('node-health')).toBeVisible();
  await page.getByTestId(`node-health-link-material-${MAT_CRIT}`).click();
  await expect(page).toHaveURL(new RegExp(`/data/material\\?id=${MAT_CRIT}`));
  await shot('E4-node-health-jump-to-material');

  // 仓库没有主数据 → 不给假链接
  await page.goto('/dashboard');
  await expect(page.getByTestId('node-health')).toBeVisible();
  await expect(page.getByTestId(`node-health-nolink-warehouse-${WH_A}`)).toContainText('无资料页');
  // 二号仓的异常来自库存行事实判据，而不是物料传播
  await expect(
    page.getByTestId(`node-health-reason-warehouse-${WH_B}-inventory_below_safety_stock`),
  ).toBeVisible();

  // ── E8：跨租户隔离——租户 A 页面不含租户 B 任何实体名 ─────────────────────
  const managerAText = await page.locator('body').innerText();
  for (const name of TENANT_B_NAMES) {
    expect(managerAText, `租户 A 页面不得出现租户 B 的「${name}」`).not.toContain(name);
  }

  // ── E5：一线「我的节点」按角色收敛，且范围依据写在界面上 ──────────────────
  const scopes: [string, string, string][] = [
    [WAREHOUSE_A, 'warehouse', '仓库'],
    [BUYER_A, 'supplier', '供应商'],
    [PLANNER_A, 'material', '物料'],
    [SALES_A, 'order', '订单'],
  ];
  for (const [account, nodeType, label] of scopes) {
    await login(page, account);
    const mine = page.getByTestId('my-nodes');
    await expect(mine).toBeVisible();
    await expect(page.getByTestId('my-nodes-scope')).toContainText(label);
    await expect(
      page.getByTestId('my-nodes-scope'),
      '范围依据必须是既有权限码，不新增权限码',
    ).toContainText('未新增权限码');
    const payload = await apiJson(page, '/dashboard/my-nodes?pageSize=50');
    expect(payload.scope.nodeTypes, `${account} 的节点范围`).toEqual([nodeType]);
    expect(payload.scope.isGlobal).toBe(false);
    expect(payload.nodes.every((node: any) => node.nodeType === nodeType)).toBe(true);
    await expect(page.getByTestId(`my-nodes-type-${nodeType}`)).toBeVisible();
    await shot(`E5-my-nodes-${nodeType}`);
  }

  // ── E9：脱敏——sales 无 field:cost:view，订单金额必须是 *** ────────────────
  // 复用上一步 sales 的会话，不重复登录（登录配额有限）。
  await expect(page.getByTestId('my-nodes')).toBeVisible();
  const salesPayload = await apiJson(page, '/dashboard/my-nodes?pageSize=50');
  const lateOrder = salesPayload.nodes.find((node: any) => node.id === ORDER_LATE);
  expect(lateOrder, '销售应看得到逾期订单节点').toBeTruthy();
  expect(lateOrder.metrics.orderAmount, '无 field:cost:view → 金额脱敏').toBe('***');
  expect(lateOrder.metrics.penaltyCost).toBe('***');
  await expect(page.getByTestId('my-nodes')).toContainText('***');
  await shot('E9-my-nodes-masked-amounts');

  // ── E10：窄屏可读且不横向溢出（同一 sales 会话，无需再登录） ──────────────
  await page.setViewportSize({ width: 375, height: 900 });
  await page.reload();
  await expect(page.getByTestId('my-nodes')).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, '375px 下页面不得横向溢出').toBeLessThanOrEqual(1);
  await shot('E10-my-nodes-mobile-375');
  await page.setViewportSize({ width: 1440, height: 1200 });

  // ── E6：没有对口节点类型的角色，明说而不是给空列表 ────────────────────────
  await login(page, BOSS_A);
  await expect(page.getByTestId('node-health')).toBeVisible();  // boss 仍能看全局概览
  const bossMine = await apiJson(page, '/dashboard/my-nodes');
  expect(bossMine.available).toBe(false);
  expect(bossMine.code).toBe('CG-C031');
  expect(bossMine.nodes).toEqual([]);
  expect(bossMine.summary).toBeNull();
  await shot('E6-boss-overview-only');

  // ── E7：空租户降级——不编造任何计数 ───────────────────────────────────────
  await login(page, MANAGER_EMPTY);
  await expect(page.getByTestId('node-health-unavailable')).toBeVisible();
  await expect(page.getByTestId('node-health-code')).toContainText('CG-C021');
  await expect(page.getByTestId('node-health-count-critical-value')).toHaveCount(0);
  await expect(page.getByTestId('node-health-table')).toHaveCount(0);
  await shot('E7-empty-tenant-degraded');

  // ── E8（续）：租户 B 页面不含租户 A 任何实体名 ───────────────────────────
  await login(page, MANAGER_B);
  await expect(page.getByTestId('node-health')).toBeVisible();
  const managerBText = await page.locator('body').innerText();
  for (const name of ['A租户主控芯片', 'A租户停产封测厂', 'A租户整机客户', MAT_CRIT, SUP_STOP]) {
    expect(managerBText, `租户 B 页面不得出现租户 A 的「${name}」`).not.toContain(name);
  }
  await shot('E8-tenant-b-isolated');
});
