import { test, expect } from '@playwright/test';
import { login, expectNoHorizontalOverflow } from './helpers';

// #3/#4：375px 顶栏无横向溢出、通知铃铛可见可点、点击通知后弹层关闭。
test.describe('375px 顶栏可访问', () => {
  test('375px 工作台无横向溢出且通知铃铛在视口内', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await login(page);
    await expect(page).toHaveURL(/\/dashboard$/);
    await page.waitForTimeout(400);
    await expectNoHorizontalOverflow(page);

    const bell = page.getByRole('button', { name: '通知' });
    await expect(bell).toBeVisible();
    const inViewport = await bell.evaluate((el) => el.getBoundingClientRect().right <= window.innerWidth + 1);
    expect(inViewport, '通知铃铛必须落在视口内').toBe(true);

    // 搜索/上报/租户 收进「更多」
    await expect(page.getByRole('button', { name: '更多' })).toBeVisible();
  });

  test('375px 点击通知后弹层关闭再跳转', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await login(page);
    await page.getByRole('button', { name: '通知' }).click();
    const drawer = page.locator('.ant-drawer-open');
    await expect(drawer).toBeVisible();
    const firstItem = drawer.locator('.ant-list-item').first();
    if (await firstItem.count()) {
      await firstItem.click();
      // 关层：抽屉消失（跳转前已 setOpen(false)）
      await expect(page.locator('.ant-drawer-open')).toHaveCount(0);
    }
  });
});
