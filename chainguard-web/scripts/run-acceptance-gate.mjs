#!/usr/bin/env node
/**
 * Phase 5B 统一验收门禁：把全部 API-mode Playwright 验收套件收进一条命令。
 *
 * 每个套件拿到自己的 GUID SQLite 库（alembic upgrade head + 可选 seed），
 * 各自的端口来自对应的 playwright.*.config.ts，串行执行互不污染。
 * 之前这些套件散落在若干手工命令和一个 bash 脚本里，不会自然进入发布门禁。
 *
 *   node scripts/run-acceptance-gate.mjs              # 全跑
 *   node scripts/run-acceptance-gate.mjs --only erp-mapping,account
 *   node scripts/run-acceptance-gate.mjs --list
 */

import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';

const WEB_DIR = resolve(import.meta.dirname, '..');
const API_DIR = resolve(WEB_DIR, '../ChainGuard');
const WORKSPACE = resolve(API_DIR, '.workspace/gate');

const PYTHON = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');
// 直接用当前 node 跑 Playwright 的 JS 入口，不经 npx：Node 24 起在 Windows 上
// 拒绝无 shell 地 spawn `.cmd`（EINVAL），而开 shell 又要给参数做转义。
const PLAYWRIGHT_CLI = resolve(WEB_DIR, 'node_modules/@playwright/test/cli.js');

// seed 为 null 表示该套件用 /auth/register 自助建租户，只需要一个已迁移的空库。
const SUITES = [
  { name: 'data-import', config: 'playwright.api-acceptance.config.ts', dbEnv: 'C2_DATABASE_URL', seed: null },
  { name: 'calibration', config: 'playwright.calibration-api.config.ts', dbEnv: 'CALIBRATION_DATABASE_URL', seed: null },
  { name: 'risk-explanation', config: 'playwright.risk-explanation-api.config.ts', dbEnv: 'RISK_EXPLAIN_DATABASE_URL', seed: 'seed_phase5b_a03_e2e.py' },
  { name: 'impact-scope', config: 'playwright.impact-scope-api.config.ts', dbEnv: 'IMPACT_SCOPE_DATABASE_URL', seed: 'seed_phase5b_a04_e2e.py' },
  { name: 'node-health', config: 'playwright.node-health-api.config.ts', dbEnv: 'NODE_HEALTH_DATABASE_URL', seed: 'seed_phase5b_c02_c03_e2e.py' },
  { name: 'c3-onboarding', config: 'playwright.c3-onboarding-api.config.ts', dbEnv: 'C3_DATABASE_URL', seed: 'seed_phase5b_c3_e2e.py' },
  { name: 'erp-integration', config: 'playwright.erp-integration-api.config.ts', dbEnv: 'ERP_E2E_DATABASE_URL', seed: 'seed_phase5b_erp_e2e.py' },
  { name: 'erp-mapping', config: 'playwright.erp-mapping-api.config.ts', dbEnv: 'MAP_E2E_DATABASE_URL', seed: 'seed_phase5b_erp_mapping_e2e.py' },
  { name: 'experience', config: 'playwright.experience-api.config.ts', dbEnv: 'EXPERIENCE_DATABASE_URL', seed: 'seed_phase5b_experience_e2e.py' },
  { name: 'account', config: 'playwright.account-api.config.ts', dbEnv: 'ACCT_DATABASE_URL', seed: 'seed_phase5b_account_e2e.py' },
];

const args = process.argv.slice(2);
if (args.includes('--list')) {
  for (const s of SUITES) console.log(s.name);
  process.exit(0);
}

const onlyArg = args.find((a) => a.startsWith('--only'));
let suites = SUITES;
if (onlyArg) {
  const raw = onlyArg.includes('=') ? onlyArg.split('=')[1] : args[args.indexOf(onlyArg) + 1];
  const wanted = new Set(String(raw || '').split(',').map((s) => s.trim()).filter(Boolean));
  const unknown = [...wanted].filter((w) => !SUITES.some((s) => s.name === w));
  if (unknown.length) {
    console.error(`unknown suite(s): ${unknown.join(', ')}\nknown: ${SUITES.map((s) => s.name).join(', ')}`);
    process.exit(2);
  }
  suites = SUITES.filter((s) => wanted.has(s.name));
}

// 门禁自用的非生产密钥。真跑发布门禁时由外部注入同名变量即可覆盖。
const baseEnv = {
  ...process.env,
  JWT_SECRET: process.env.JWT_SECRET || 'phase5b-acceptance-gate-secret-only-not-for-deployment',
  CHAINGUARD_ENCRYPTION_KEY: process.env.CHAINGUARD_ENCRYPTION_KEY || 'phase5b-acceptance-gate-encryption-key',
};

function run(command, cmdArgs, options) {
  const result = spawnSync(command, cmdArgs, { stdio: 'inherit', ...options });
  if (result.error) throw result.error;
  return result.status ?? 1;
}

mkdirSync(WORKSPACE, { recursive: true });

const results = [];
for (const suite of suites) {
  console.log(`\n=== [${suite.name}] provisioning ===`);
  // src/webapi/database.py 的验收守卫要求绝对路径 + 文件名含 GUID。
  const dbPath = resolve(WORKSPACE, `${suite.name}-${randomUUID()}.db`).replace(/\\/g, '/');
  const databaseUrl = `sqlite:///${dbPath}`;
  const provisionEnv = { ...baseEnv, DATABASE_URL: databaseUrl };

  let status = run(PYTHON, ['-m', 'alembic', 'upgrade', 'head'], { cwd: API_DIR, env: provisionEnv });
  if (status === 0 && suite.seed) {
    status = run(PYTHON, [`scripts/${suite.seed}`], { cwd: API_DIR, env: provisionEnv });
  }
  if (status !== 0) {
    console.error(`[${suite.name}] provisioning failed`);
    results.push({ name: suite.name, status, stage: 'provision' });
    continue;
  }

  console.log(`=== [${suite.name}] running ${suite.config} ===`);
  status = run(process.execPath, [PLAYWRIGHT_CLI, 'test', `--config=${suite.config}`], {
    cwd: WEB_DIR,
    env: { ...baseEnv, [suite.dbEnv]: databaseUrl },
  });
  results.push({ name: suite.name, status, stage: 'test' });
}

console.log('\n===== acceptance gate summary =====');
for (const r of results) {
  console.log(`${r.status === 0 ? 'PASS' : 'FAIL'}  ${r.name}${r.status === 0 ? '' : ` (${r.stage})`}`);
}
const failed = results.filter((r) => r.status !== 0);
console.log(`${results.length - failed.length}/${results.length} suites passed`);
process.exit(failed.length ? 1 : 0);
