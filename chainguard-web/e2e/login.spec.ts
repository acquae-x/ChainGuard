import { test, expect } from '@playwright/test';
import { login, DEMO_PASSWORD } from './helpers';

test.describe('登录跳转（P0-四修复回归）', () => {
  test('成功登录后跳转到工作台', async ({ page }) => {
    await login(page, 'scm_lead@chainguard.demo', DEMO_PASSWORD);
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByText('工作台').first()).toBeVisible();
  });

  test('登录失败：停留在登录页并提示错误', async ({ page }) => {
    await login(page, 'scm_lead@chainguard.demo', 'wrong-password');
    // 不跳转
    await expect(page).toHaveURL(/\/user\/login$/);
    // 出现错误提示（antd message）
    await expect(page.locator('.ant-message-error, .ant-message-notice').first()).toBeVisible();
  });

  test('登录成功后 redirect 查询参数仅放行站内安全路径', async ({ page }) => {
    // 外部 URL 不得被跳转，退回默认 /dashboard
    await page.goto('/user/login?redirect=https://evil.example.com');
    await page.locator('#account').fill('scm_lead@chainguard.demo');
    await page.locator('#password').fill(DEMO_PASSWORD);
    await page.getByRole('button', { name: /登.*录/ }).first().click();
    await expect(page).toHaveURL(/127\.0\.0\.1:\d+\/(dashboard|onboarding)$/);
  });
});
