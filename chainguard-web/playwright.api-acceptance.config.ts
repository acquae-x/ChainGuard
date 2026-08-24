import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const __dirname = import.meta.dirname;

const apiPort = Number(process.env.C2_API_PORT || 8300);
const webPort = Number(process.env.C2_WEB_PORT || 8301);
const databaseUrl = process.env.C2_DATABASE_URL;

if (!databaseUrl) {
  throw new Error('C2_DATABASE_URL is required and must point to a migrated isolated acceptance database');
}

export default defineConfig({
  testDir: './e2e',
  testMatch: 'data-import-api-acceptance.spec.ts',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    headless: true,
    actionTimeout: 20_000,
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      name: 'ChainGuard isolated API',
      command: `python -m uvicorn src.api:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: resolve(__dirname, '../ChainGuard'),
      env: {
        ...process.env,
        DATABASE_URL: databaseUrl,
        CHAINGUARD_REQUIRE_GUID_DB: '1',
        CHAINGUARD_DISABLE_SCHEDULER: '1',
        JWT_SECRET: process.env.JWT_SECRET || 'phase5b-c2-frontend-acceptance-secret-only',
      } as Record<string, string>,
      url: `http://127.0.0.1:${apiPort}/readyz`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'ChainGuard API-mode web',
      command: 'npm run dev',
      cwd: __dirname,
      env: {
        ...process.env,
        DATA_MODE: 'api',
        PORT: String(webPort),
        API_PROXY_TARGET: `http://127.0.0.1:${apiPort}`,
      } as Record<string, string>,
      url: `http://127.0.0.1:${webPort}`,
      timeout: 240_000,
      reuseExistingServer: false,
      stdout: 'ignore',
      stderr: 'pipe',
    },
  ],
});
