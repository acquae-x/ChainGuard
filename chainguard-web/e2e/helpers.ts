import { Page, expect } from '@playwright/test';

// mock 模式统一演示密码；账号为 {roleCode}@chainguard.demo。
export const DEMO_PASSWORD = 'Demo@1234';

/**
 * 进入应用页面，并等待 umi dev server 完成首次编译。
 *
 * 为什么需要它：`webServer.url` 探活只保证端口有响应，而 umi dev 在 MFSU
 * 编译期间返回的是一个 "Bundling... NN%" 占位页。此时 DOM 里没有任何应用
 * 内容，后续任何 getByRole 都会一路等到 actionTimeout 超时，且报错指向业务
 * 定位器（"waiting for getByRole('menuitem')"），与真实原因完全无关——
 * 这正是 data-import 在 CI 上连续三跑失败、本地却从不复现的原因。
 *
 * 为什么放在共享助手里：十个验收套件共用同一份 src/.umi 与 MFSU 缓存，
 * 只有**第一个**执行的套件付冷编译成本，其余都命中热缓存。所以这不是某个
 * 套件的问题——谁排第一谁失败。一旦有人调整 run-acceptance-gate.mjs 里的
 * SUITES 顺序，问题就会转移到另一个套件上。
 *
 * 冷编译只发生一次，热缓存下该等待立即返回，不会拖慢其余套件。
 */
export async function gotoApp(page: Page, path = '/') {
  await page.goto(path);
  // 占位页不存在时 toBeHidden 立即通过；存在时一直等到编译结束、页面被替换。
  await expect(page.getByRole('heading', { name: /Bundling/i }))
    .toBeHidden({ timeout: 240_000 });
}

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
