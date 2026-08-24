import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const __dirname = import.meta.dirname;

// ERP 字段映射的独立验收配置：与 erp-integration/node-health 同构，
// 单独的端口与数据库，避免与既有验收套件互相污染。
// 端口默认值必须与 e2e/erp-field-mapping-api-acceptance.spec.ts 的默认值一致，
// spec 直接读 process.env 拼后端与 mock ERP 地址。
const apiPort = Number(process.env.MAP_E2E_API_PORT || 8480);
const webPort = Number(process.env.MAP_E2E_WEB_PORT || 8481);
const erpPort = Number(process.env.MAP_E2E_MOCK_PORT || 8482);
const databaseUrl = process.env.MAP_E2E_DATABASE_URL;
if (!databaseUrl) throw new Error('MAP_E2E_DATABASE_URL must point to a migrated isolated database seeded by scripts/seed_phase5b_erp_mapping_e2e.py');

// worker 进程也会加载本配置，写回 process.env 让 spec 读到与 webServer 一致的端口。
process.env.MAP_E2E_API_PORT = String(apiPort);
process.env.MAP_E2E_MOCK_PORT = String(erpPort);

const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const pythonCommand = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');

export default defineConfig({
  testDir: './e2e',
  testMatch: 'erp-field-mapping-api-acceptance.spec.ts',
  timeout: 180_000,
  expect: { timeout: 45_000 },
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
      name: 'mock ERP',
      command: `${pythonCommand} scripts/mock_erp_server.py --port ${erpPort}`,
      cwd: resolve(__dirname, '../ChainGuard'),
      // 必须与 spec 里填入「认证令牌」的值一致，否则连通测试会因鉴权失败而红。
      env: { ...process.env, MOCK_ERP_API_KEY: 'map-e2e-token' } as Record<string, string>,
      url: `http://127.0.0.1:${erpPort}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'ChainGuard mapping isolated API',
      command: `${pythonCommand} -m uvicorn src.api:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: resolve(__dirname, '../ChainGuard'),
      env: {
        ...process.env,
        DATABASE_URL: databaseUrl,
        CHAINGUARD_REQUIRE_GUID_DB: '1',
        CHAINGUARD_DISABLE_SCHEDULER: '1',
        JWT_SECRET: process.env.JWT_SECRET || 'phase5b-map-e2e-secret-only-not-for-deployment',
        CHAINGUARD_ENCRYPTION_KEY: process.env.CHAINGUARD_ENCRYPTION_KEY || 'phase5b-map-e2e-encryption-key',
      } as Record<string, string>,
      url: `http://127.0.0.1:${apiPort}/readyz`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'ChainGuard mapping API-mode web',
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
