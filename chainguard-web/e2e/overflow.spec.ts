import { test, expect } from '@playwright/test';
import { login, expectNoHorizontalOverflow } from './helpers';

const WIDTHS = [375, 768, 1280];

test.describe('审批页横向溢出（P1-二修复回归）', () => {
  for (const width of WIDTHS) {
    test(`审批中心在 ${width}px 无 document 横向溢出`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await login(page);
      await page.goto('/decision/approval?tab=pending');
      // 等列表就绪（ProTable 渲染或空态）
      await page.locator('.ant-pro-table, .ant-table, .ant-empty').first().waitFor({ state: 'visible' });
      await page.waitForTimeout(400);
      await expectNoHorizontalOverflow(page);
    });
  }

  test('推演抽屉在 375px 无 document 横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await login(page);
    await page.goto('/decision/approval?tab=pending');
    await page.locator('.ant-table, .ant-empty').first().waitFor({ state: 'visible' });

    // 375px（非 xl）点“审批详情”走抽屉详情
    await page.getByRole('button', { name: '审批详情' }).first().click();
    await page.locator('.ant-drawer-open').first().waitFor({ state: 'visible' });
    await expectNoHorizontalOverflow(page);

    // 打开“查看完整推演”抽屉
    await page.getByRole('button', { name: '查看完整推演' }).first().click();
    await expect(page.locator('.ant-drawer-title', { hasText: '完整推演' })).toBeVisible();
    await page.waitForTimeout(600);
    await expectNoHorizontalOverflow(page);

    // 推演内容区图表容器不超出视口宽度
    const overflowingCharts = await page.evaluate(() => {
      const vw = window.innerWidth;
      return [...document.querySelectorAll('.echarts-for-react')].filter((el) => el.getBoundingClientRect().right > vw + 1).length;
    });
    expect(overflowingCharts).toBe(0);
  });
});
