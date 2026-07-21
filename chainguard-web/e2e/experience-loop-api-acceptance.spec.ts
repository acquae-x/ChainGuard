import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const apiPort = Number(process.env.EXPERIENCE_API_PORT || 8430);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const evidenceDir = resolve(process.env.EXPERIENCE_EVIDENCE_DIR || '../ChainGuard/output/phase5b-experience/screenshots');
const password = 'ExperienceE2E@2026!';
const incidentId = 'inc-e3-real-a';

async function login(page: Page, account: string) {
  await page.context().clearCookies();
  await page.goto('/user/login');
  await page.locator('#account').fill(account);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: /登.*录/ }).first().click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test('API 模式 Chromium：真实租户经验写入、命中展示与跨租户隔离', async ({ page }) => {
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await login(page, 'e3-real-a@chainguard.test');

  // First real decision produces the card.  The second is intentionally run
  // from the product UI so the history badge is evidence from the shipped view.
  const token = (await page.context().cookies()).find((item) => item.name === 'chainguard_token')?.value;
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  const first = await page.request.post(apiUrl(`/incidents/${incidentId}/proposals:generate`), { headers });
  expect(first.ok(), await first.text()).toBeTruthy();
  const firstJob = await first.json() as { jobId: string };
  for (let index = 0; index < 60; index += 1) {
    const job = await page.request.get(apiUrl(`/jobs/${firstJob.jobId}`), { headers });
    const body = await job.json() as { status: string };
    if (body.status === 'succeeded') break;
    if (body.status === 'failed') throw new Error('first real decision failed');
    await page.waitForTimeout(250);
  }
  const cards = await page.request.get(apiUrl('/experiences'), { headers });
  expect((await cards.json() as { total: number }).total).toBe(1);

  await page.goto(`/decision/generate/${incidentId}`);
  await page.getByRole('button', { name: '生成方案' }).click();
  await expect(page.getByText('引用历史经验（1）').first()).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText(/关键结论：/).first()).toBeVisible();
  await expect(page.getByText(/来源：/).first()).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '01-tenant-a-proposal-history-hit.png'), fullPage: true });

  await page.goto('/case/experience');
  await expect(page.getByText('E3 真实租户经验闭环').first()).toBeVisible();
  await expect(page.getByText('真实租户决策作业已完成，待审批/执行结果回填。').first()).toBeVisible();
  await page.screenshot({ path: resolve(evidenceDir, '02-tenant-a-experience-card.png'), fullPage: true });

  await login(page, 'e3-real-b@chainguard.test');
  await page.goto('/case/experience');
  await expect(page.getByText('暂无本租户经验卡')).toBeVisible();
  const tokenB = (await page.context().cookies()).find((item) => item.name === 'chainguard_token')?.value;
  const isolated = await page.request.get(apiUrl('/experiences'), { headers: { Authorization: `Bearer ${tokenB}` } });
  expect(await isolated.json()).toEqual({ data: [], total: 0, success: true });
  await page.screenshot({ path: resolve(evidenceDir, '03-tenant-b-experience-isolated.png'), fullPage: true });
});
