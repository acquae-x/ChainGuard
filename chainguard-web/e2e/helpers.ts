import { Page, expect } from '@playwright/test';

// mock 模式统一演示密码；账号为 {roleCode}@chainguard.demo。
export const DEMO_PASSWORD = 'Demo@1234';

export async function login(page: Page, account = 'scm_lead@chainguard.demo', password = DEMO_PASSWORD) {
  await page.goto('/user/login');
  await page.locator('#account').fill(account);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: /登.*录/ }).first().click();
}

// 断言当前文档没有横向溢出：documentElement.scrollWidth <= window.innerWidth。
export async function expectNoHorizontalOverflow(page: Page) {
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(metrics.scrollWidth, `scrollWidth ${metrics.scrollWidth} <= innerWidth ${metrics.innerWidth}`).toBeLessThanOrEqual(metrics.innerWidth);
}
