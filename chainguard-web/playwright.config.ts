import { defineConfig, devices } from '@playwright/test';

// e2e 用 mock 数据模式：单一 umi dev 服务即可自洽，无需后端/seed，便于可重复运行。
const PORT = Number(process.env.E2E_PORT || 8100);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const DATA_MODE = process.env.E2E_DATA_MODE || 'mock';
const API_PROXY_TARGET = process.env.E2E_API_PROXY_TARGET || 'http://127.0.0.1:8000';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    headless: true,
    actionTimeout: 15_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `cross-env DATA_MODE=${DATA_MODE} API_PROXY_TARGET=${API_PROXY_TARGET} PORT=${PORT} max dev`,
    url: BASE_URL,
    timeout: 240_000,
    reuseExistingServer: !process.env.CI,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
