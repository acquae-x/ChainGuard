import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const __dirname = import.meta.dirname;

// Phase 5B「账户完善」的独立验收配置：把原先 scripts/run_phase5b_account_acceptance.sh
// 手工编排的后端 + mock IdP + API 模式前端收进单一配置，使其能进统一发布门禁。
//
// IdP 默认端口用 8462 而非 spec 里的 8470：8470 已被 erp-integration 套件的后端占用，
// 两套配置共存时会撞端口。这里显式写回 process.env，spec 读到的即为此处的值。
const apiPort = Number(process.env.ACCT_API_PORT || 8460);
const webPort = Number(process.env.ACCT_WEB_PORT || 8461);
const idpPort = Number(process.env.ACCT_IDP_PORT || 8462);
const databaseUrl = process.env.ACCT_DATABASE_URL;
if (!databaseUrl) throw new Error('ACCT_DATABASE_URL must point to a migrated isolated database seeded by scripts/seed_phase5b_account_e2e.py');

process.env.ACCT_API_PORT = String(apiPort);
process.env.ACCT_IDP_PORT = String(idpPort);

const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const pythonCommand = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');

export default defineConfig({
  testDir: './e2e',
  testMatch: 'account-lifecycle-api-acceptance.spec.ts',
  timeout: 300_000,
  expect: { timeout: 30_000 },
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    headless: true,
    actionTimeout: 30_000,
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      name: 'mock OIDC IdP',
      command: `${pythonCommand} scripts/mock_oidc_server.py --port ${idpPort}`,
      cwd: resolve(__dirname, '../ChainGuard'),
      env: { ...process.env } as Record<string, string>,
      // mock_oidc_server 只实现 /authorize 与 /token，没有 discovery 端点，
      // 因此这里等端口监听而不是等某个 URL 返回 2xx。
      port: idpPort,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'ChainGuard account isolated API',
      command: `${pythonCommand} -m uvicorn src.api:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: resolve(__dirname, '../ChainGuard'),
      env: {
        ...process.env,
        DATABASE_URL: databaseUrl,
        CHAINGUARD_REQUIRE_GUID_DB: '1',
        CHAINGUARD_DISABLE_SCHEDULER: '1',
        // 见 spec 顶部注释：放宽 IP 预算是为了单独观测账号维度锁定，
        // IP 维度的 5/minute 由 pytest test_ip_rate_limit_is_independent_of_account_lock 锁定。
        LOGIN_IP_RATE_LIMIT: '100/minute',
        JWT_SECRET: process.env.JWT_SECRET || 'phase5b-acct-e2e-secret-only-not-for-deployment',
        CHAINGUARD_ENCRYPTION_KEY: process.env.CHAINGUARD_ENCRYPTION_KEY || 'phase5b-acct-e2e-encryption-key',
      } as Record<string, string>,
      url: `http://127.0.0.1:${apiPort}/readyz`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'ChainGuard account API-mode web',
      command: `${npmCommand} run dev`,
      cwd: __dirname,
      env: {
        ...process.env,
        DATA_MODE: 'api',
        PORT: String(webPort),
        API_PROXY_TARGET: `http://127.0.0.1:${apiPort}`,
      } as Record<string, string>,
      url: `http://127.0.0.1:${webPort}`,
      timeout: 300_000,
      reuseExistingServer: false,
      stdout: 'ignore',
      stderr: 'pipe',
    },
  ],
});
