import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const apiPort = Number(process.env.ERP_E2E_API_PORT || 8470);
const webPort = Number(process.env.ERP_E2E_WEB_PORT || 8471);
const erpPort = Number(process.env.ERP_E2E_MOCK_PORT || 8472);
const databaseUrl = process.env.ERP_E2E_DATABASE_URL;
if (!databaseUrl) throw new Error('ERP_E2E_DATABASE_URL must point to a migrated isolated database');

// 跨平台可执行名：`npm.cmd` 只在 Windows 存在，写死会让 Linux CI 以 exit 127 起不来。
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const pythonCommand = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');

export default defineConfig({
  testDir: './e2e', testMatch: 'erp-integration-api-acceptance.spec.ts', timeout: 180_000, expect: { timeout: 45_000 }, workers: 1, fullyParallel: false, reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${webPort}`, headless: true, actionTimeout: 30_000, ...devices['Desktop Chrome'] },
  webServer: [
    { name: 'mock ERP', command: `${pythonCommand} scripts/mock_erp_server.py --port ${erpPort}`, cwd: resolve(__dirname, '../ChainGuard'), env: { ...process.env, MOCK_ERP_API_KEY: 'erp-e2e-token' } as Record<string, string>, url: `http://127.0.0.1:${erpPort}/health`, timeout: 120_000, reuseExistingServer: false, stdout: 'pipe', stderr: 'pipe' },
    { name: 'ChainGuard ERP API', command: `${pythonCommand} -m uvicorn src.api:app --host 127.0.0.1 --port ${apiPort}`, cwd: resolve(__dirname, '../ChainGuard'), env: { ...process.env, DATABASE_URL: databaseUrl, CHAINGUARD_REQUIRE_GUID_DB: '1', CHAINGUARD_DISABLE_SCHEDULER: '1', JWT_SECRET: process.env.JWT_SECRET || 'phase5b-erp-e2e-secret-only', CHAINGUARD_ENCRYPTION_KEY: process.env.CHAINGUARD_ENCRYPTION_KEY || 'phase5b-erp-e2e-encryption-key' } as Record<string, string>, url: `http://127.0.0.1:${apiPort}/readyz`, timeout: 120_000, reuseExistingServer: false, stdout: 'pipe', stderr: 'pipe' },
    { name: 'ERP API-mode web', command: `${npmCommand} run dev`, cwd: __dirname, env: { ...process.env, DATA_MODE: 'api', PORT: String(webPort), API_PROXY_TARGET: `http://127.0.0.1:${apiPort}` } as Record<string, string>, url: `http://127.0.0.1:${webPort}`, timeout: 240_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' },
  ],
});
