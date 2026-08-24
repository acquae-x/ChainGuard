import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { test, expect, type Page } from '@playwright/test';
import { expectNoHorizontalOverflow, gotoApp } from './helpers';

const evidenceDir = resolve(process.env.C2_EVIDENCE_DIR || '../ChainGuard/output/phase5b-c2-closeout-api/screenshots');
const account = process.env.C2_ACCOUNT || 'c2-closeout-a8a53701@chainguard.demo';
const password = process.env.C2_PASSWORD || 'C2Closeout@2026!';
const apiBaseUrl = `http://127.0.0.1:${Number(process.env.C2_API_PORT || 8300)}`;
const apiUrl = (path: string) => `${apiBaseUrl}/api/v1${path}`;
const materialCsv = Buffer.from([
  'material_id,material_name,category,unit,daily_consumption,standard_cost,criticality',
  'MAT-E2E-001,Playwright验收物料,电子元件,件,24,12.5,high',
  ',缺少业务主键的拒绝行,电子元件,件,10,8.5,low',
].join('\n'), 'utf8');

async function capture(page: Page, name: string) {
  await page.screenshot({ path: resolve(evidenceDir, name), fullPage: true });
}

async function expectTotal(page: Page, total: number) {
  await expect(page.getByText(new RegExp(`总共\\s*${total}\\s*条`))).toBeVisible();
}

async function registerTenant(page: Page, phone: string, companyName: string) {
  const response = await page.request.post(apiUrl('/auth/register'), {
    data: {
      phone,
      password,
      companyName,
      industry: '电子制造',
      scale: '50-200',
      ownerRole: '供应链负责人',
      plan: 'trial',
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json() as Promise<{ token: string; tenant: { id: string } }>;
}

async function useAccessToken(page: Page, token: string) {
  if (page.url() === 'about:blank') await page.goto('/user/login');
  await page.context().addCookies([{
    name: 'chainguard_token',
    value: token,
    url: new URL(page.url()).origin,
  }]);
}

async function importMaterialThroughApi(page: Page, token: string) {
  const headers = { Authorization: `Bearer ${token}` };
  const uploaded = await page.request.post(apiUrl('/imports/upload?type=auto&mode=structured'), {
    headers,
    multipart: { file: { name: 'materials.csv', mimeType: 'text/csv', buffer: materialCsv } },
  });
  expect(uploaded.ok(), await uploaded.text()).toBeTruthy();
  const job = await uploaded.json() as { id: string };
  const preflight = await page.request.post(apiUrl(`/imports/${job.id}/preflight`), { headers, data: {} });
  expect(preflight.ok(), await preflight.text()).toBeTruthy();
  const confirmed = await page.request.post(apiUrl(`/imports/${job.id}/confirm`), {
    headers,
    data: { values: { confirmedType: 'material', manualConfirmed: false, duplicatePolicy: 'merge', onlyValidRows: true } },
  });
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
  const executed = await page.request.post(apiUrl(`/imports/${job.id}/execute`), { headers, data: {} });
  expect(executed.ok(), await executed.text()).toBeTruthy();
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const progress = await page.request.get(apiUrl(`/imports/${job.id}`), { headers });
    const current = await progress.json() as { status: string; result?: { successRows?: number; rejectedRows?: number } };
    if (current.status === 'succeeded') return { jobId: job.id, current };
    if (current.status === 'failed') throw new Error(`API import failed: ${JSON.stringify(current)}`);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error('API import polling timed out');
}

// 这里借用 page 渲染一张 OCR 素材图，属于对共享状态的临时改动：改完把视口
// 还回去，避免后续断言隐式依赖一个 360px 高的视口。
//
// 注：这条还原**不是** CI 上那次菜单点击超时的原因（我一度这样判断，后来被
// DOM 快照证伪——真实原因是 umi dev 首次冷编译，见 helpers.ts 的 gotoApp）。
// 保留它只是因为辅助函数改共享状态不还原本身就该修。
async function renderOcrImage(page: Page, headers: string, row: string) {
  const previous = page.viewportSize();
  await page.setViewportSize({ width: 1400, height: 360 });
  await page.setContent(`<!doctype html><html><body style="margin:0;background:white"><pre style="margin:48px;font:48px/1.8 'Microsoft YaHei','Segoe UI',sans-serif;color:#000;white-space:pre">${headers}\n${row}</pre></body></html>`);
  const shot = await page.screenshot({ type: 'png' });
  if (previous) await page.setViewportSize(previous);
  return shot;
}

async function uploadThroughCurrentImportUi(page: Page, image: Buffer, fileName: string) {
  // Umi dev server only serves the SPA shell at `/`; enter the target route
  // through the rendered navigation so this remains a real UI flow.
  await gotoApp(page);
  await page.getByRole('menuitem', { name: /数据管理/ }).click();
  await page.getByRole('menuitem', { name: '数据导入' }).click();
  await expect(page.getByText('数据导入', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: /直接上传/ }).click();
  const fileChooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: '选择 ZIP / 多个文件' }).click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles({ name: fileName, mimeType: 'image/png', buffer: image });
  await expect(page.getByText(fileName)).toBeVisible({ timeout: 30_000 });
}

async function openDataPage(page: Page, pageName: '数据导入' | '物料') {
  await gotoApp(page);
  await page.getByRole('menuitem', { name: /数据管理/ }).click();
  await page.getByRole('menuitem', { name: pageName }).click();
  await expect(page.getByText(pageName, { exact: true }).first()).toBeVisible();
}

async function importOcrMaterialThroughUi(
  page: Page,
  image: Buffer,
  fileName: string,
  sources: Array<{ source: string; option: RegExp }>,
) {
  await uploadThroughCurrentImportUi(page, image, fileName);

  const typeSelect = page.locator('.ant-table-tbody').getByRole('combobox').first();
  await typeSelect.click();
  await page.locator('.ant-select-dropdown:visible').getByText('物料主数据 · 主数据', { exact: true }).click();
  await page.getByRole('button', { name: '下一步' }).click();
  await expect(page.getByRole('table', { name: `${fileName} 字段映射` })).toBeVisible({ timeout: 45_000 });

  for (const field of sources) {
    const target = page.getByRole('combobox', { name: `${field.source} 目标字段` });
    await expect(target).toBeVisible();
    const selectedText = await target.evaluate((element) => element.closest('.ant-select')?.textContent || '');
    expect(selectedText).toMatch(field.option);
  }
  await page.getByRole('checkbox', { name: /已核对原文、类型和关键字段/ }).click();
  await page.getByRole('button', { name: '确认并执行' }).click();

  await expect(page.getByText('导入批次执行完成')).toBeVisible({ timeout: 45_000 });
  const resultRow = page.locator('.ant-table-tbody > .ant-table-row').first();
  await expect(resultRow.locator('td').nth(2)).toContainText('succeeded');
  await expect(resultRow.locator('td').nth(3)).toHaveText('1');
  await expect(resultRow.locator('td').nth(4)).toHaveText('0');
}

test('OCR 真实 Chromium 中文三字段闭环、英文回归与乱码安全降级', async ({ page }) => {
  const suffix = String(Date.now()).slice(-8);
  const tenant = await registerTenant(page, `137${suffix}`, `OCR界面验收-${suffix}`);
  await useAccessToken(page, tenant.token);
  const chineseId = `MAT-UI-ZH-${suffix}`;
  const englishId = `MAT-OCR-EN-${suffix}`;

  const chineseImage = await renderOcrImage(page, '物料编码,物料名称,成本', `${chineseId},中文界面验收芯片,12.50`);
  await importOcrMaterialThroughUi(page, chineseImage, `ocr-cn-${suffix}.png`, [
    { source: '物料编码', option: /物料编号.*material_id/ },
    { source: '物料名称', option: /物料名称.*material_name/ },
    { source: '成本', option: /单位成本.*standard_cost/ },
  ]);

  await openDataPage(page, '物料');
  const chineseRow = page.locator('.ant-table-row').filter({ hasText: chineseId });
  await expect(chineseRow).toContainText('中文界面验收芯片');
  await expect(chineseRow).toContainText('12.5');

  const englishImage = await renderOcrImage(page, 'material_id,material_name,standard_cost', `${englishId},English OCR Material,23.75`);
  await importOcrMaterialThroughUi(page, englishImage, `ocr-en-${suffix}.png`, [
    { source: 'material_id', option: /物料编号.*material_id/ },
    { source: 'material_name', option: /物料名称.*material_name/ },
    { source: 'standard_cost', option: /单位成本.*standard_cost/ },
  ]);

  await openDataPage(page, '物料');
  const englishRow = page.locator('.ant-table-row').filter({ hasText: englishId });
  await expect(englishRow).toContainText('English OCR Material');
  await expect(englishRow).toContainText('23.75');

  const garbledImage = await renderOcrImage(page, '????,????,??', 'MAT-GARBLED-UI,??????,12.50');
  const garbledName = `ocr-garbled-${suffix}.png`;
  await uploadThroughCurrentImportUi(page, garbledImage, garbledName);
  await page.locator('.ant-table-tbody').getByRole('combobox').first().click();
  await page.locator('.ant-select-dropdown:visible').getByText('物料主数据 · 主数据', { exact: true }).click();
  await page.getByRole('button', { name: '下一步' }).click();
  await expect(page.getByText(/OCR 无法安全形成字段映射（OCR_GARBLED_TEXT）/)).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText(/重新上传清晰、端正且保留表头和列分隔符/)).toBeVisible();
  await expect(page.getByText(/CSV\/Excel 上传，或人工录入/)).toBeVisible();
  await expect(page.getByRole('checkbox', { name: /已核对原文、类型和关键字段/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: '确认并执行' })).toBeDisabled();
});

test('C2 真实 API 产品界面收尾验收', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/user/login');
  await page.locator('#account').fill(account);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: /登.*录/ }).first().click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.goto('/data/import?tab=wizard');
  await expect(page.getByText('智能混合导入：文件夹 / ZIP')).toBeVisible();
  await expect(page.getByText('执行结果')).toBeVisible();
  await capture(page, '01-import-entry-1280.png');

  for (const width of [1099, 1280, 375]) {
    await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });
    await page.goto('/data/import?tab=wizard');
    await expect(page.getByText('智能混合导入：文件夹 / ZIP')).toBeVisible();
    await expect(page.getByText('执行结果')).toBeVisible();
    const upload = page.getByRole('button', { name: /直接上传/ });
    await expect(upload).toBeVisible();
    expect(await upload.evaluate((element) => element.getBoundingClientRect().right)).toBeLessThanOrEqual(width + 1);
    await expectNoHorizontalOverflow(page);
    await capture(page, `02-import-responsive-${width}.png`);
  }

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/data/import?tab=wizard');
  await page.getByRole('tab', { name: '导入历史' }).click();
  await expect(page).toHaveURL(/tab=history/);
  const importRow = page.locator('.ant-table-row').filter({ hasText: 'import-phase5b-c2-a8a53701' });
  await expect(importRow).toBeVisible();
  const importCells = importRow.locator('td');
  await expect(importCells.nth(3)).toHaveText('111460');
  await expect(importCells.nth(4)).toHaveText('0');
  await capture(page, '03-import-history-111460.png');

  await page.goto('/data/material');
  await expectTotal(page, 240);
  await capture(page, '04-material-240.png');

  await page.goto('/data/supplier');
  await expectTotal(page, 60);
  const supplierRow = page.locator('.ant-table-row').first();
  await expect(supplierRow).toBeVisible();
  await expect(supplierRow).not.toContainText('null');
  await capture(page, '05-supplier-60-default-relation.png');
  await supplierRow.getByRole('button').last().click();
  await expect(page.getByRole('region', { name: '供货关系明细' })).toBeVisible();
  await expect(page.getByText('默认主供')).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '可用应急量' })).toBeVisible();
  await capture(page, '06-supplier-detail-relations.png');
  const relationScroller = page.locator('.ant-drawer .ant-table-content');
  await relationScroller.evaluate((element) => {
    element.scrollLeft = element.scrollWidth;
  });
  await expect(page.getByRole('columnheader', { name: '关系' })).toBeVisible();
  await capture(page, '06b-supplier-detail-default-qualified.png');
  // Ant Design exposes the drawer close control as "Close" even under the
  // Chinese locale; accept both accessible names across supported versions.
  await page.getByRole('button', { name: /关闭|Close/ }).click();

  await page.goto('/data/customer');
  await expectTotal(page, 120);
  await capture(page, '07-customer-120.png');

  await page.goto('/data/order');
  await expectTotal(page, 3500);
  await capture(page, '08-order-3500.png');

  await page.goto('/data/inventory');
  await expectTotal(page, 1440);
  const supportText = (await page.locator('.ant-table-row').first().locator('td').nth(4).innerText()).trim();
  expect(supportText).toMatch(/^\d+(?:\.\d{1,2})? 小时$/);
  await capture(page, '09-inventory-1440-formatted.png');

  expect(pageErrors, `React/page errors: ${pageErrors.join(' | ')}`).toEqual([]);
});

test('真实上传闭环、部分拒绝、重复签名与租户隔离', async ({ page }) => {
  const suffix = String(Date.now()).slice(-8);
  const tenantA = await registerTenant(page, `139${suffix}`, `Playwright租户A-${suffix}`);
  await useAccessToken(page, tenantA.token);

  await page.goto('/data/import?tab=wizard');
  await page.getByRole('button', { name: /直接上传/ }).click();
  const batchInput = page.locator('input[type="file"][multiple][accept*=".csv"]').first();
  await batchInput.setInputFiles({ name: 'materials.csv', mimeType: 'text/csv', buffer: materialCsv });
  await expect(page.getByText('materials.csv')).toBeVisible();
  await page.getByRole('button', { name: '下一步' }).click();
  await expect(page.getByText('通过')).toBeVisible();
  await page.getByRole('button', { name: '确认并执行' }).click();
  await expect(page.getByText('存在被拒绝的数据行，请展开对应批次查看逐表报告。')).toBeVisible({ timeout: 30_000 });

  const resultRow = page.locator('.ant-table-row').first();
  await expect(resultRow).toContainText('succeeded');
  const jobId = (await resultRow.innerText()).match(/import-[0-9a-f]+/)?.[0];
  expect(jobId).toBeTruthy();
  await resultRow.locator('.ant-table-row-expand-icon').click();
  const resultReport = page.getByRole('table', { name: `${jobId} 逐表导入报告` });
  await expect(resultReport).toBeVisible();
  await expect(resultReport.getByRole('row', { name: /materials\s+2\s+1\s+1/ })).toBeVisible();
  const rejectionDetails = page.getByRole('table', { name: `${jobId} 逐行拒绝明细` });
  await expect(rejectionDetails).toBeVisible();
  await expect(rejectionDetails).toContainText('缺业务主键/必填字段');
  await expect(rejectionDetails).toContainText('修正字段映射后重新导入');

  await page.getByRole('tab', { name: '导入历史' }).click();
  const historyRow = page.locator('.ant-tabs-tabpane-active .ant-table-row').filter({ hasText: jobId! });
  await expect(historyRow).toBeVisible();
  const historyReport = page.getByRole('table', { name: `${jobId} 逐表导入报告` });
  if (!await historyReport.isVisible()) {
    await historyRow.locator('.ant-table-row-expand-icon:visible').click();
  }
  await expect(historyReport).toBeVisible();

  await page.goto('/data/material');
  await expect(page.getByText('MAT-E2E-001')).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Playwright验收物料', exact: true })).toBeVisible();

  await page.goto('/data/import?tab=wizard');
  await page.getByRole('button', { name: /直接上传/ }).click();
  await page.locator('input[type="file"][multiple][accept*=".csv"]').first().setInputFiles({ name: 'materials.csv', mimeType: 'text/csv', buffer: materialCsv });
  await page.getByRole('button', { name: '下一步' }).click();
  await page.getByRole('button', { name: '确认并执行' }).click();
  await expect(page.getByText(/D04：相同签名文件已导入/).first()).toBeVisible({ timeout: 20_000 });

  const tenantB = await registerTenant(page, `138${suffix}`, `Playwright租户B-${suffix}`);
  const tenantBHeaders = { Authorization: `Bearer ${tenantB.token}` };
  const hiddenJob = await page.request.get(apiUrl(`/imports/${jobId}`), { headers: tenantBHeaders });
  expect(hiddenJob.status()).toBe(404);
  const beforeImport = await page.request.get(apiUrl('/data/material'), { headers: tenantBHeaders });
  expect(await beforeImport.json()).toMatchObject({ total: 0, data: [] });

  const tenantBImport = await importMaterialThroughApi(page, tenantB.token);
  expect(tenantBImport.current.result).toMatchObject({ successRows: 1, rejectedRows: 1 });
  const afterImport = await page.request.get(apiUrl('/data/material'), { headers: tenantBHeaders });
  const tenantBMaterials = await afterImport.json() as { total: number; data: Array<{ id: string }> };
  expect(tenantBMaterials.total).toBe(1);
  expect(tenantBMaterials.data.map((item) => item.id)).toContain('MAT-E2E-001');
});
