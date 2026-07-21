import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const apiPort = Number(process.env.C3_API_PORT || 8450);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(process.env.C3_EVIDENCE_DIR || '../ChainGuard/output/phase5b-c3/screenshots');
const password = 'C3E2E@2026!';
const riskId = 'risk-c3-e2e-a';

const files = [
  ['materials.csv', 'material_id,material_name,category,unit,daily_consumption,standard_cost,criticality\nC3-MAT-001,C3真实MCU,芯片,件,240,12.5,critical\n'],
  ['suppliers.csv', 'supplier_id,supplier_name,region,status,reliability_score\nC3-SUP-001,C3真实供应商,上海,active,93\n'],
  ['supplier_materials.csv', 'supplier_material_id,supplier_id,material_id,qualified,supplier_rank,lead_time_hours,available_emergency_qty,emergency_cost_multiplier,unit_cost\nC3-REL-001,C3-SUP-001,C3-MAT-001,true,1,24,1200,1.2,15\n'],
  ['customers.csv', 'customer_id,customer_name,customer_level,region\nC3-CUS-001,C3重点客户,A,华东\n'],
  ['sales_orders.csv', 'sales_order_id,customer_id,order_status,promised_delivery_at,order_amount,gross_profit,penalty_cost\nC3-SO-001,C3-CUS-001,pending,2030-01-05T00:00:00+00:00,100000,30000,20000\n'],
  ['sales_order_lines.csv', 'sales_order_line_id,sales_order_id,line_no,material_id,ordered_qty,unit_price\nC3-SOL-001,C3-SO-001,1,C3-MAT-001,800,125\n'],
  ['inventory.csv', 'inventory_id,material_id,warehouse_id,warehouse_name,on_hand_qty,available_qty,safety_stock_qty,in_transit_qty,planned_arrival_at,estimated_arrival_at\nC3-INV-001,C3-MAT-001,C3-WH-001,C3上海仓,480,420,600,500,2030-01-02T00:00:00+00:00,2030-01-03T00:00:00+00:00\n'],
] as const;

async function login(page: Page, account: string) {
  await page.context().clearCookies();
  await page.goto('/user/login');
  await page.locator('#account').fill(account);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: /登.*录/ }).first().click();
  await expect(page).toHaveURL(/\/(dashboard|onboarding)$/);
}

function token(page: Page) {
  return page.context().cookies().then((cookies) => cookies.find((item) => item.name === 'chainguard_token')?.value || '');
}

test('C3 Chromium API：空租户引导、真实导入、真实决策、显式演示与隔离/权限', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await login(page, 'c3-admin-a@chainguard.test');
  const adminToken = await token(page);
  const empty = await page.request.get(apiUrl('/onboarding/status'), { headers: { Authorization: `Bearer ${adminToken}` } });
  expect((await empty.json() as { guideVisible: boolean }).guideVisible).toBe(true);

  await page.goto('/onboarding');
  await expect(page.getByText('从真实业务数据开始')).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '01-empty-tenant-guide.png'), fullPage: true });
  await login(page, 'c3-finance-a@chainguard.test');
  await page.goto('/onboarding');
  await expect(page.getByText('你没有数据导入权限')).toBeVisible();
  const noPermission = await page.request.post(apiUrl('/onboarding/demo-dataset'), { headers: { Authorization: `Bearer ${await token(page)}` }, data: { values: { confirmed: true } } });
  expect(noPermission.status()).toBe(403);
  await page.screenshot({ path: resolve(evidenceDir, '02-no-import-permission.png'), fullPage: true });
  await login(page, 'c3-admin-a@chainguard.test');
  await page.goto('/onboarding');
  await page.getByRole('button', { name: '开始真实导入' }).click();
  await page.getByRole('button', { name: /直接上传/ }).click();
  await page.locator('input[type="file"][multiple]').first().setInputFiles(files.map(([name, content]) => ({ name, mimeType: 'text/csv', buffer: Buffer.from(content, 'utf8') })));
  await expect(page.getByText('materials.csv', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一步' }).click();
  await expect(page.getByText('执行前人工确认')).toBeVisible({ timeout: 45_000 });
  await page.getByRole('button', { name: '确认并执行' }).click();
  await expect(page.getByText('真实业务数据已准备完成')).toBeVisible({ timeout: 90_000 });
  await page.screenshot({ path: resolve(evidenceDir, '03-real-import-complete.png'), fullPage: true });

  const afterImport = await page.request.get(apiUrl('/onboarding/status'), { headers: { Authorization: `Bearer ${adminToken}` } });
  const ready = await afterImport.json() as { guideVisible: boolean; phase: string; entitySummary: { decisionReady: boolean; hasRealData: boolean } };
  expect(ready).toMatchObject({ guideVisible: false, phase: 'ready', entitySummary: { decisionReady: true, hasRealData: true } });
  const incident = await page.request.post(apiUrl('/incidents'), { headers: { Authorization: `Bearer ${adminToken}` }, data: { riskIds: [riskId], title: 'C3 真实导入后的供应风险', type: 'supplier_shutdown', loss: 0, cost: 0 } });
  expect(incident.ok(), await incident.text()).toBeTruthy();
  const incidentId = (await incident.json() as { id: string }).id;
  await page.goto(`/decision/generate/${incidentId}`);
  await page.getByRole('button', { name: '生成方案' }).click();
  await expect(page.getByText('多 Agent 推演完成')).toBeVisible({ timeout: 90_000 });
  await page.screenshot({ path: resolve(evidenceDir, '04-real-tenant-decision.png'), fullPage: true });

  await login(page, 'c3-admin-b@chainguard.test');
  await page.goto('/onboarding');
  await expect(page.getByText('从真实业务数据开始')).toBeVisible();
  await page.getByRole('button', { name: '改为注入演示数据集' }).click();
  const demoConfirm = page.locator('.ant-modal-confirm:visible');
  await expect(demoConfirm).toContainText('确认注入演示数据集？');
  await demoConfirm.getByRole('button', { name: '确认注入演示数据' }).click();
  await expect(page.getByText('演示数据已准备完成')).toBeVisible({ timeout: 45_000 });
  const tenantBToken = await token(page);
  const tenantB = await page.request.get(apiUrl('/onboarding/status'), { headers: { Authorization: `Bearer ${tenantBToken}` } });
  expect(await tenantB.json()).toMatchObject({ phase: 'demo_ready', entitySummary: { hasDemoData: true, hasRealData: false } });
  const tenantAStillReal = await page.request.get(apiUrl('/onboarding/status'), { headers: { Authorization: `Bearer ${adminToken}` } });
  expect(await tenantAStillReal.json()).toMatchObject({ phase: 'ready', entitySummary: { hasRealData: true, hasDemoData: false } });
  await page.screenshot({ path: resolve(evidenceDir, '05-explicit-demo-tenant-b.png'), fullPage: true });
});
