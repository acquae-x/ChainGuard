import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const apiPort = Number(process.env.EXPERIENCE_API_PORT || 8430);
const webPort = Number(process.env.EXPERIENCE_WEB_PORT || 8431);
const databaseUrl = process.env.EXPERIENCE_DATABASE_URL;
if (!databaseUrl) throw new Error('EXPERIENCE_DATABASE_URL must point to a migrated isolated database');

// 跨平台可执行名：`npm.cmd` 只在 Windows 存在，写死会让 Linux CI 以 exit 127 起不来。
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const pythonCommand = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');

export default defineConfig({
  testDir: './e2e', testMatch: 'experience-loop-api-acceptance.spec.ts', timeout: 120_000, expect: { timeout: 20_000 }, workers: 1, fullyParallel: false, reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${webPort}`, headless: true, actionTimeout: 20_000, ...devices['Desktop Chrome'] },
  webServer: [
    { name: 'ChainGuard E3 isolated API', command: `${pythonCommand} -m uvicorn src.api:app --host 127.0.0.1 --port ${apiPort}`, cwd: resolve(__dirname, '../ChainGuard'), env: { ...process.env, DATABASE_URL: databaseUrl, CHAINGUARD_REQUIRE_GUID_DB: '1', CHAINGUARD_DISABLE_SCHEDULER: '1', JWT_SECRET: process.env.JWT_SECRET || 'phase5b-experience-e2e-secret-only' } as Record<string, string>, url: `http://127.0.0.1:${apiPort}/readyz`, timeout: 120_000, reuseExistingServer: false, stdout: 'pipe', stderr: 'pipe' },
    { name: 'ChainGuard E3 API-mode web', command: `${npmCommand} run dev`, cwd: __dirname, env: { ...process.env, DATA_MODE: 'api', PORT: String(webPort), API_PROXY_TARGET: `http://127.0.0.1:${apiPort}` } as Record<string, string>, url: `http://127.0.0.1:${webPort}`, timeout: 240_000, reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' },
  ],
});
