import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

/**
 * Phase 5B 收尾批「账户完善」真实浏览器验收（API 模式，真后端 + 真 mock IdP）。
 *
 * 关于限流：后端要用 LOGIN_IP_RATE_LIMIT=100/minute 启动。这不是绕过防护，而是把
 * 两条独立防线拆开观测——IP 维度的默认 5/minute 由 pytest
 * (test_ip_rate_limit_is_independent_of_account_lock) 锁定，本文件专门验证账号维度
 * 的"连续 5 次失败锁 15 分钟"。不放宽 IP 预算，第 6 个请求会被 429 挡住，
 * 账号锁定根本无从观测。
 */

const apiPort = Number(process.env.ACCT_API_PORT || 8460);
const idpPort = Number(process.env.ACCT_IDP_PORT || 8470);
const apiUrl = (path: string) => `http://127.0.0.1:${apiPort}/api/v1${path}`;
const idpBase = `http://127.0.0.1:${idpPort}`;
const evidenceDir = resolve(process.env.ACCT_EVIDENCE_DIR || '../ChainGuard/output/phase5b-account/screenshots');

const password = 'AcctE2E@2026!';
const ADMIN_A = 'acct-admin-a@chainguard.test';
const MEMBER_A = 'acct-member-a@chainguard.test';
const LOCKME_A = 'acct-lockme-a@chainguard.test';
const ADMIN_B = 'acct-admin-b@chainguard.test';
const TENANT_A = 'tenant-acct-e2e-a';
// mock_oidc_server 的默认主体
const SSO_EMAIL = 'sso.user@sso-demo.test';
const SSO_DOMAIN = 'sso-demo.test';
const CLIENT_ID = 'chainguard-e2e';
const CLIENT_SECRET = 'chainguard-e2e-secret-0123456789';

const shot = (name: string) => resolve(evidenceDir, name);

/**
 * umi dev server 会往 body 上挂一个全屏调试 iframe，它会拦掉长页面下半部分的点击。
 * 应用本身不使用任何 iframe，所以这里直接摘掉这个开发期产物——测的是产品 UI，
 * 不是脚手架的浮层。
 */
async function dropDevOverlay(page: Page) {
  await page.evaluate(() => document.querySelectorAll('body > iframe').forEach((node) => node.remove()));
}

async function login(page: Page, account: string, secret = password) {
  await page.context().clearCookies();
  await page.goto('/user/login');
  await page.locator('#account').fill(account);
  await page.locator('#password').fill(secret);
  await page.getByRole('button', { name: /登.*录/ }).first().click();
}

function token(page: Page) {
  return page.context().cookies().then((items) => items.find((item) => item.name === 'chainguard_token')?.value || '');
}

async function loginAndWait(page: Page, account: string, secret = password) {
  await login(page, account, secret);
  await expect(page).toHaveURL(/\/(dashboard|onboarding)$/);
  return token(page);
}

test.describe.configure({ mode: 'serial' });

test('账户完善 Chromium API：邀请码、账号锁定、重置降级、SSO、隔离与权限', async ({ page }) => {
  test.setTimeout(240_000);
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 960 });

  // ---------------------------------------------------------------- 邀请码
  const adminToken = await loginAndWait(page, ADMIN_A);
  await page.goto('/settings/users');
  await expect(page.getByRole('heading', { name: '企业邀请码' })).toBeVisible();
  await page.screenshot({ path: shot('01-user-management.png'), fullPage: true });

  await page.getByRole('button', { name: '生成邀请码' }).click();
  const inviteDrawer = page.locator('.ant-drawer-open');
  await expect(inviteDrawer.locator('.ant-drawer-title')).toHaveText('生成企业邀请码');
  // antd Select 的可点区域是 .ant-select-selector，label 关联的 input 是隐藏的搜索框
  await inviteDrawer.locator('#roleCode').locator('xpath=ancestor::div[contains(@class,"ant-select")][1]').click();
  await page.locator('.ant-select-dropdown:visible').getByText('采购人员', { exact: true }).click();
  await inviteDrawer.locator('#maxUses').fill('1');
  await inviteDrawer.locator('#note').fill('验收用：采购部新同事');
  await inviteDrawer.getByRole('button', { name: '生成邀请码' }).click();

  const codeModal = page.locator('.ant-modal-confirm:visible');
  await expect(codeModal).toContainText('仅显示这一次');
  const invitationCode = (await codeModal.getByTestId('invitation-code').innerText()).trim();
  expect(invitationCode).toHaveLength(12);
  // 抽屉收起、弹窗完成淡入后再截图，否则证据是一张过渡态的糊图
  await expect(inviteDrawer).toBeHidden();
  await page.waitForTimeout(400);
  await page.screenshot({ path: shot('02-invitation-generated.png'), fullPage: true });
  await codeModal.locator('.ant-btn-primary').click();

  // 列表只保留掩码：明文在页面上必须再也找不到
  await expect(page.getByText(`${invitationCode.slice(0, 4)}********`)).toBeVisible();
  await expect(page.locator('body')).not.toContainText(invitationCode);

  const invitationsApi = await page.request.get(apiUrl('/settings/invitations'), { headers: { Authorization: `Bearer ${adminToken}` } });
  expect(await invitationsApi.text()).not.toContain(invitationCode);

  // ------------------------------------------------- 受邀人加入（落点=签发租户）
  const joiner = `acct-joiner-${Date.now()}@chainguard.test`;
  await page.context().clearCookies();
  await page.goto('/user/join');
  await page.getByLabel('邀请码').fill(invitationCode);
  await page.getByLabel('姓名').fill('受邀采购同事');
  await page.getByLabel('邮箱').fill(joiner);
  await page.getByLabel('密码').fill('Joined@2026!');
  await page.screenshot({ path: shot('03-join-form.png'), fullPage: true });
  await page.getByRole('button', { name: '加入企业' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const joinerToken = await token(page);
  const joinerMe = await (await page.request.get(apiUrl('/auth/me'), { headers: { Authorization: `Bearer ${joinerToken}` } })).json();
  expect(joinerMe.tenant.id).toBe(TENANT_A);
  expect(joinerMe.currentUser.roleCode).toBe('buyer');
  await page.screenshot({ path: shot('04-joined-tenant-a.png'), fullPage: true });

  // 用尽后不能再用；管理员侧能看到使用留痕
  const reuse = await page.request.post(apiUrl('/auth/join'), {
    data: { code: invitationCode, name: '第二位', email: `dup-${Date.now()}@chainguard.test`, password: 'Joined@2026!' },
  });
  expect(reuse.status()).toBe(400);

  await loginAndWait(page, ADMIN_A);
  await page.goto('/settings/users');
  const usedRow = page.locator('tr', { hasText: `${invitationCode.slice(0, 4)}********` });
  await expect(usedRow).toContainText('受邀采购同事');
  await expect(usedRow.getByText('已用尽', { exact: true })).toBeVisible();
  await expect(usedRow).toContainText('1/1');
  await page.screenshot({ path: shot('05-invitation-exhausted-with-trail.png'), fullPage: true });

  // 失效一枚仍可用的邀请码后，加入必须被拒
  const spare = await page.request.post(apiUrl('/settings/invitations'), {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: { roleCode: 'buyer', maxUses: 5, validHours: 24, note: '验收用：待失效' },
  });
  const spareBody = await spare.json();
  await page.reload();
  const spareRow = page.locator('tr', { hasText: `${spareBody.code.slice(0, 4)}********` });
  await spareRow.getByRole('button', { name: '失效' }).click();
  await page.getByRole('button', { name: '确认失效' }).click();
  await expect(spareRow.getByText('已失效', { exact: true })).toBeVisible();
  await page.screenshot({ path: shot('06-invitation-revoked.png'), fullPage: true });
  const afterRevoke = await page.request.post(apiUrl('/auth/join'), {
    data: { code: spareBody.code, name: '被拒者', email: `late-${Date.now()}@chainguard.test`, password: 'Joined@2026!' },
  });
  expect(afterRevoke.status()).toBe(400);

  // ---------------------------------------------------------------- 账号锁定
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await login(page, LOCKME_A, 'definitely-wrong-password');
    await page.waitForTimeout(400);
  }
  await expect(page.getByText('账号已锁定', { exact: false }).first()).toBeVisible();
  await page.screenshot({ path: shot('07-account-locked-login.png'), fullPage: true });

  // 锁定期内密码正确也进不去
  await login(page, LOCKME_A);
  await expect(page).toHaveURL(/\/user\/login/);
  await expect(page.getByText('账号已锁定', { exact: false }).first()).toBeVisible();

  await loginAndWait(page, ADMIN_A);
  await page.goto('/settings/users');
  const lockedRow = page.locator('tr', { hasText: 'acct-lockme-a' });
  await expect(lockedRow.getByText('已锁定')).toBeVisible();
  await page.screenshot({ path: shot('08-admin-sees-locked.png'), fullPage: true });
  await lockedRow.getByRole('button', { name: '解锁' }).click();
  await page.getByRole('button', { name: '确认解锁' }).click();
  await expect(page.getByText('的账号已解锁', { exact: false })).toBeVisible();
  await page.screenshot({ path: shot('09-admin-unlocked.png'), fullPage: true });

  await loginAndWait(page, LOCKME_A);
  await page.screenshot({ path: shot('10-unlocked-login-succeeds.png'), fullPage: true });

  // ------------------------------------------------------------ 找回密码降级
  await page.context().clearCookies();
  await page.goto('/user/reset');
  await page.getByLabel('账号（手机号/邮箱）').fill(MEMBER_A);
  await page.getByRole('button', { name: '提交找回申请' }).click();
  await expect(page.getByText('当前无法自助重置，请走管理员兜底')).toBeVisible();
  await expect(page.getByText('尚未配置邮件/短信通道', { exact: false })).toBeVisible();
  // 通道未配置就绝不能出现"已发送"字样
  await expect(page.locator('body')).not.toContainText('重置链接已发送');
  await page.screenshot({ path: shot('11-reset-degraded.png'), fullPage: true });

  await loginAndWait(page, ADMIN_A);
  await page.goto('/settings/users');
  await expect(page.getByText('条待处理的找回密码申请', { exact: false })).toBeVisible();
  await page.screenshot({ path: shot('12-admin-reset-backlog.png'), fullPage: true });
  const resetRow = page.locator('tr', { hasText: 'acct-member-a' });
  await resetRow.getByRole('button', { name: '重置密码' }).click();
  await page.getByRole('button', { name: '确认重置' }).click();
  const resetModal = page.locator('.ant-modal-confirm:visible');
  await expect(resetModal).toContainText('一次性临时密码');
  const temporary = (await resetModal.locator('strong').first().innerText()).trim();
  await page.screenshot({ path: shot('13-admin-temporary-password.png'), fullPage: true });
  await resetModal.locator('.ant-btn-primary').click();

  await login(page, MEMBER_A, temporary);
  await expect(page).toHaveURL(/\/user\/profile$/);  // 首登强制改密守卫
  await page.screenshot({ path: shot('14-temporary-password-forces-change.png'), fullPage: true });

  // ------------------------------------------------------------ SSO 未配置
  await page.context().clearCookies();
  await page.goto('/user/login');
  await page.locator('#account').fill(MEMBER_A);
  await page.getByRole('button', { name: '企业单点登录（SSO）' }).click();
  await expect(page.getByText('未配置企业单点登录', { exact: false }).first()).toBeVisible();
  await page.screenshot({ path: shot('15-sso-not-configured.png'), fullPage: true });

  // ------------------------------------------------------------ SSO 配置与成功回调
  const adminTokenB = await loginAndWait(page, ADMIN_A);
  await page.goto('/settings/integration');
  await expect(page.getByText('企业单点登录（OIDC SSO）')).toBeVisible();
  await expect(page.getByText('未配置客户端密钥')).toBeVisible();
  await page.screenshot({ path: shot('16-sso-card-unconfigured.png'), fullPage: true });

  await page.getByLabel('Issuer').fill(idpBase);
  await page.getByLabel('Client ID').fill(CLIENT_ID);
  await page.getByLabel('Client Secret').fill(CLIENT_SECRET);
  await page.getByLabel('Authorization Endpoint').fill(`${idpBase}/authorize`);
  await page.getByLabel('Token Endpoint').fill(`${idpBase}/token`);
  await page.getByLabel('允许的邮箱域名').fill(SSO_DOMAIN);
  await dropDevOverlay(page);
  await page.getByLabel('启用 SSO').click();
  await page.getByLabel('首次登录自动加入').click();
  await page.getByRole('button', { name: '保存 SSO 配置' }).click();
  await expect(page.getByText('SSO 已启用', { exact: false })).toBeVisible();
  await page.screenshot({ path: shot('17-sso-configured.png'), fullPage: true });

  // 保存后接口仍不回显密钥
  const ssoRead = await page.request.get(apiUrl('/settings/sso'), { headers: { Authorization: `Bearer ${adminTokenB}` } });
  expect(await ssoRead.text()).not.toContain(CLIENT_SECRET);
  expect((await ssoRead.json()).clientSecretSet).toBe(true);

  await page.context().clearCookies();
  await page.goto('/user/login');
  await page.locator('#account').fill(`anyone@${SSO_DOMAIN}`);
  await page.getByRole('button', { name: '企业单点登录（SSO）' }).click();
  // 浏览器真实走完 IdP 授权跳转 → 回调页 → 会话建立
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  const ssoToken = await token(page);
  const ssoMe = await (await page.request.get(apiUrl('/auth/me'), { headers: { Authorization: `Bearer ${ssoToken}` } })).json();
  expect(ssoMe.tenant.id).toBe(TENANT_A);
  expect(ssoMe.currentUser.email).toBe(SSO_EMAIL);
  await page.screenshot({ path: shot('18-sso-login-success.png'), fullPage: true });

  // ------------------------------------------------------------ 隔离与权限
  const adminBToken = await loginAndWait(page, ADMIN_B);
  await page.goto('/settings/users');
  const bInvitations = await (await page.request.get(apiUrl('/settings/invitations'), { headers: { Authorization: `Bearer ${adminBToken}` } })).json();
  expect(bInvitations.data).toHaveLength(0);
  await expect(page.getByText('还没有邀请码', { exact: false })).toBeVisible();
  // B 家看不到 A 家的 SSO 配置，也读不到密钥
  const bSso = await (await page.request.get(apiUrl('/settings/sso'), { headers: { Authorization: `Bearer ${adminBToken}` } })).json();
  expect(bSso.configured).toBe(false);
  expect(bSso.clientSecretSet).toBe(false);
  const crossRevoke = await page.request.post(apiUrl(`/settings/invitations/${spareBody.invitation.id}/revoke`), { headers: { Authorization: `Bearer ${adminBToken}` } });
  expect(crossRevoke.status()).toBe(404);
  // B 家不能抢注 A 家已占用的 SSO 域名
  const domainGrab = await page.request.put(apiUrl('/settings/sso'), {
    headers: { Authorization: `Bearer ${adminBToken}` },
    data: { enabled: true, issuer: idpBase, clientId: CLIENT_ID, clientSecret: CLIENT_SECRET,
            authorizationEndpoint: `${idpBase}/authorize`, tokenEndpoint: `${idpBase}/token`,
            redirectUri: 'http://127.0.0.1:8100/user/sso-callback', allowedDomains: [SSO_DOMAIN] },
  });
  expect(domainGrab.status()).toBe(409);
  await page.screenshot({ path: shot('19-tenant-b-isolated.png'), fullPage: true });

  // 普通成员：管理动作一律 403
  await login(page, MEMBER_A, temporary);
  // 该账号仍是临时密码，会被首登强制改密守卫送到 /user/profile；等落地后再取会话
  await expect(page).toHaveURL(/\/user\/profile$/);
  const memberToken = await token(page);
  const memberHeaders = { Authorization: `Bearer ${memberToken}` };
  expect((await page.request.get(apiUrl('/settings/invitations'), { headers: memberHeaders })).status()).toBe(403);
  expect((await page.request.post(apiUrl('/settings/invitations'), { headers: memberHeaders, data: { roleCode: 'buyer' } })).status()).toBe(403);
  expect((await page.request.get(apiUrl('/settings/sso'), { headers: memberHeaders })).status()).toBe(403);
  expect((await page.request.get(apiUrl('/settings/password-resets'), { headers: memberHeaders })).status()).toBe(403);
  expect((await page.request.post(apiUrl(`/settings/users/${joinerMe.currentUser.id}/unlock`), { headers: memberHeaders })).status()).toBe(403);
  expect((await page.request.post(apiUrl(`/settings/users/${joinerMe.currentUser.id}/reset-password`), { headers: memberHeaders })).status()).toBe(403);
  await page.screenshot({ path: shot('20-member-blocked.png'), fullPage: true });
});
