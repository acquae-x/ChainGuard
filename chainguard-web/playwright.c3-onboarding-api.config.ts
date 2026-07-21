import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const apiPort = Number(process.env.C3_API_PORT || 8450);
const webPort = Number(process.env.C3_WEB_PORT || 8451);
const databaseUrl = process.env.C3_DATABASE_URL;
if (!databaseUrl) throw new Error('C3_DATABASE_URL must point to a migrated isolated database');

export default defineConfig({
  testDir: './e2e', testMatch: 'c3-onboarding-api-acceptance.spec.ts', timeout: 180_000, expect: { timeout: 45_000 }, workers: 1, fullyParallel: false, reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${webPort}`, headless: true, actionTimeout: 30_000, ...devices['Desktop Chrome'] },
  webServer: [
    { name: 'ChainGuard C3 isolated API', command: `python -m uvicorn src.api:app --host 127.0.0.1 --port ${apiPort}`, cwd: resolve(__dirname, '../ChainGuard'), env: { ...process.env, DATABASE_URL: databaseUrl, CHAINGUARD_REQUIRE_GUID_DB: '1', CHAINGUARD_DISABLE_SCHEDULER: '1', JWT_SECRET: process.env.JWT_SECRET || 'phase5b-c3-e2e-secret-only' } as Record<string, string>, url: `http://127.0.0.1:${apiPort}/readyz`, timeout: 120_000, reuseExistingServer: false, stdout: 'pipe', stderr: 'pipe' },
    { name: 'ChainGuard C3 API-mode web', command: 'npm.cmd run dev', cwd: __dirname, env: { ...process.env, DATA_MODE: 'api', PORT: String(webPort), API_PROXY_TARGET: `http://127.0.0.1:${apiPort}` } as Record<string, string>, url: `http://127.0.0.1:${webPort}`, timeout: 240_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' },
  ],
});
