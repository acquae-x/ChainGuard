import { test, expect } from '@playwright/test';
import { expectNoHorizontalOverflow } from './helpers';

async function openDataImport(page: import('@playwright/test').Page) {
  await page.setViewportSize({ width: 1280, height: 812 });
  await page.route('**/api/v1/imports/catalog', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      modes: [],
      types: Array.from({ length: 18 }, (_, index) => ({
        value: `type-${index}`, label: `资料${index}`, group: '真实业务资料',
        source_table: `table_${index}`, erp_resource: `resource-${index}`, entity: index < 7,
      })),
    }),
  }));
  await page.goto('/user/login');
  await page.context().addCookies([{
    name: 'chainguard_token', value: 'demo-token-scm_lead',
    url: new URL(page.url()).origin,
  }]);
  await page.goto('/data/import?tab=wizard');
  await expect(page).toHaveURL(/\/data\/import\?tab=wizard/);
  await expect(page.getByText('智能混合导入：文件夹 / ZIP')).toBeVisible();
}

test.describe('数据导入页签与响应式回归', () => {
  for (const width of [1099, 1280, 375]) {
    test(`${width}px 无 document 横向溢出且入口完整可见`, async ({ page }) => {
      await openDataImport(page);
      await page.setViewportSize({ width, height: 812 });
      await expect(page.getByText('执行结果')).toBeVisible();
      const upload = page.getByRole('button', { name: /直接上传/ });
      await expect(upload).toBeVisible();
      const right = await upload.evaluate((element) => element.getBoundingClientRect().right);
      expect(right).toBeLessThanOrEqual(width + 1);
      await expectNoHorizontalOverflow(page);
    });
  }

  test('导入历史点击即时切换，刷新及前进后退保持正确', async ({ page }) => {
    await openDataImport(page);
    await page.setViewportSize({ width: 1099, height: 812 });

    await page.getByRole('tab', { name: '导入历史' }).click();
    await expect(page).toHaveURL(/tab=history/);
    await expect(page.getByRole('columnheader', { name: '批次' })).toBeVisible();
    await expect(page.getByText('智能混合导入：文件夹 / ZIP')).not.toBeVisible();
    await page.reload();
    await expect(page.getByRole('columnheader', { name: '批次' })).toBeVisible();

    await page.goBack();
    await expect(page.getByText('智能混合导入：文件夹 / ZIP')).toBeVisible();
    await page.goForward();
    await expect(page.getByRole('columnheader', { name: '批次' })).toBeVisible();
  });
});
