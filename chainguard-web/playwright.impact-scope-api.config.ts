import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

// A04 影响范围的独立验收配置：与 A03/calibration/erp/experience 同构，
// 单独的端口与数据库，避免与既有验收套件互相污染。
const apiPort = Number(process.env.IMPACT_SCOPE_API_PORT || 8442);
const webPort = Number(process.env.IMPACT_SCOPE_WEB_PORT || 8443);
const databaseUrl = process.env.IMPACT_SCOPE_DATABASE_URL;
if (!databaseUrl) throw new Error('IMPACT_SCOPE_DATABASE_URL must point to a migrated isolated database');

// 既有配置写死 npm.cmd（Windows 专用），本机之外一律起不来。
// 按平台选择可执行名，验收脚本因此能在 Windows 与 Linux/CI 上都跑。
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const pythonCommand = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');

export default defineConfig({
  testDir: './e2e',
  testMatch: 'impact-scope-api-acceptance.spec.ts',
  timeout: 120_000,
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
      name: 'ChainGuard A04 isolated API',
      command: `${pythonCommand} -m uvicorn src.api:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: resolve(__dirname, '../ChainGuard'),
      env: {
        ...process.env,
        DATABASE_URL: databaseUrl,
        CHAINGUARD_REQUIRE_GUID_DB: '1',
        CHAINGUARD_DISABLE_SCHEDULER: '1',
        JWT_SECRET: process.env.JWT_SECRET || 'phase5b-a04-e2e-secret-only-not-for-deployment',
      } as Record<string, string>,
      url: `http://127.0.0.1:${apiPort}/readyz`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'ChainGuard A04 API-mode web',
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
