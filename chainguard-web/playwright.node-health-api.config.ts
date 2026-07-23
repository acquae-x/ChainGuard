import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

// C02/C03 节点健康的独立验收配置：与 A03/A04/calibration/erp/experience 同构，
// 单独的端口与数据库，避免与既有验收套件互相污染。
const apiPort = Number(process.env.NODE_HEALTH_API_PORT || 8444);
const webPort = Number(process.env.NODE_HEALTH_WEB_PORT || 8445);
const databaseUrl = process.env.NODE_HEALTH_DATABASE_URL;
if (!databaseUrl) throw new Error('NODE_HEALTH_DATABASE_URL must point to a migrated isolated database');

const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const pythonCommand = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');

export default defineConfig({
  testDir: './e2e',
  testMatch: 'node-health-api-acceptance.spec.ts',
  // 覆盖 8 个角色的登录，会撞上 /auth/login 的 5 次/分钟 IP 限流，
  // 用例内部按配额排队等待（见 spec 的 waitForLoginQuota），因此超时放宽到 8 分钟。
  timeout: 480_000,
  expect: { timeout: 20_000 },
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    headless: true,
    actionTimeout: 20_000,
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      name: 'ChainGuard C02/C03 isolated API',
      command: `${pythonCommand} -m uvicorn src.api:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: resolve(__dirname, '../ChainGuard'),
      env: {
        ...process.env,
        DATABASE_URL: databaseUrl,
        CHAINGUARD_REQUIRE_GUID_DB: '1',
        CHAINGUARD_DISABLE_SCHEDULER: '1',
        JWT_SECRET: process.env.JWT_SECRET || 'phase5b-c02-e2e-secret-only-not-for-deployment',
      } as Record<string, string>,
      url: `http://127.0.0.1:${apiPort}/readyz`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'ChainGuard C02/C03 API-mode web',
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
