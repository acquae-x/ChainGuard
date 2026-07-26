#!/usr/bin/env node
/**
 * 统一验收门禁：把全部 API-mode Playwright 验收套件收进一条命令。
 *
 * 每个套件拿到自己的 GUID SQLite 库（alembic upgrade head + 可选 seed），
 * 各自的端口来自对应的 playwright.*.config.ts，串行执行互不污染。
 * 之前这些套件散落在若干手工命令和一个 bash 脚本里，不会自然进入发布门禁。
 *
 *   node scripts/run-acceptance-gate.mjs              # 全跑
 *   node scripts/run-acceptance-gate.mjs --only erp-mapping,account
 *   node scripts/run-acceptance-gate.mjs --list
 *
 * 结果判定不看进程退出码，改读 JSON reporter 的结构化输出。原因：Playwright 对
 * 跳过的用例（test.skip / test.fixme）返回 0，门禁因此把"10/10 通过"和"其中一条
 * 主路径根本没跑"这两件事显示成同一个绿灯。每个套件必须在 expectedSkips 里显式
 * 申报允许跳过的条数，实际跳过数超出即判失败——跳过必须是一个需要有人签字的决定，
 * 而不是一条静默通道。
 */

import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, existsSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { resolve, relative } from 'node:path';

const WEB_DIR = resolve(import.meta.dirname, '..');
const API_DIR = resolve(WEB_DIR, '../ChainGuard');
const WORKSPACE = resolve(API_DIR, '.workspace/gate');
// JSON 报告与失败 trace 的归档位置。CI 用 upload-artifact 收这个目录。
const ARTIFACTS = resolve(WORKSPACE, 'artifacts');

const PYTHON = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');
// 直接用当前 node 跑 Playwright 的 JS 入口，不经 npx：Node 24 起在 Windows 上
// 拒绝无 shell 地 spawn `.cmd`（EINVAL），而开 shell 又要给参数做转义。
const PLAYWRIGHT_CLI = resolve(WEB_DIR, 'node_modules/@playwright/test/cli.js');

// seed 为 null 表示该套件用 /auth/register 自助建租户，只需要一个已迁移的空库。
// seedArgs 用于需要参数化 provisioning 的套件：拿到 { dbPath, workspace } 返回 argv。
// expectedSkips 省略即视为 0：该套件不允许有任何跳过的用例。
const SUITES = [
  // data-import 的"C2 产品界面收尾验收"用例断言的是整套企业演示资产
  // （批次 import-phase5b-c2-a8a53701、111460 行、物料 240/供应商 60/…），
  // 自助注册的空租户里不存在这些数据，必须走 C2 provisioning 脚本。
  // account/password 与 spec 内的默认值保持一致，spec 因此无需外部注入。
  {
    name: 'data-import',
    config: 'playwright.api-acceptance.config.ts',
    dbEnv: 'C2_DATABASE_URL',
    seed: 'phase5b_c2_acceptance.py',
    seedArgs: ({ dbPath, workspace }) => [
      '--database', dbPath,
      '--data-dir', 'demo_assets/enterprise/csv',
      '--tenant-id', 'tenant-phase5b-c2-a8a53701',
      '--job-id', 'import-phase5b-c2-a8a53701',
      '--account', 'c2-closeout-a8a53701@chainguard.demo',
      '--password', 'C2Closeout@2026!',
      '--output', resolve(workspace, 'data-import-c2-report.json'),
    ],
  },
  // 三条用例全部实跑：拒绝路径 + 人工确认主路径 + 漂移告警。夹具由
  // ChainGuard/scripts/generate_calibration_e2e_fixture.py 固化在 e2e/fixtures/calibration。
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

/**
 * 从 JSON reporter 产物里取各状态计数。
 *
 * 优先用 Playwright 自带的 stats（1.40+ 提供），但不依赖它：老版本或 reporter 中途
 * 崩溃时 stats 可能缺失，此时退回遍历 suites/specs/tests 自行统计。两条路都拿不到
 * 结果时返回 null，调用侧按"结果不可解析"判失败——绝不静默当作通过。
 */
function readOutcome(jsonPath) {
  if (!existsSync(jsonPath)) return null;
  let report;
  try {
    report = JSON.parse(readFileSync(jsonPath, 'utf8'));
  } catch {
    return null;
  }

  const s = report.stats;
  if (s && typeof s.expected === 'number') {
    return {
      passed: s.expected, failed: s.unexpected ?? 0,
      skipped: s.skipped ?? 0, flaky: s.flaky ?? 0,
      errors: (report.errors ?? []).length,
    };
  }

  const counts = { passed: 0, failed: 0, skipped: 0, flaky: 0, errors: (report.errors ?? []).length };
  const walk = (suite) => {
    for (const spec of suite.specs ?? []) {
      for (const test of spec.tests ?? []) {
        // test.status 是聚合后的判定；results 是每次重试的原始记录。
        const status = test.status ?? (test.results ?? []).at(-1)?.status;
        if (status === 'skipped') counts.skipped += 1;
        else if (status === 'flaky') counts.flaky += 1;
        else if (status === 'expected' || status === 'passed') counts.passed += 1;
        else counts.failed += 1;
      }
    }
    for (const child of suite.suites ?? []) walk(child);
  };
  for (const suite of report.suites ?? []) walk(suite);
  return counts;
}

mkdirSync(WORKSPACE, { recursive: true });
mkdirSync(ARTIFACTS, { recursive: true });

// 演示企业库自举。demo_assets 下的 CSV/PDF/xlsx 都在版本库里，唯独 *.db 被
// .gitignore 排除；而 erp-integration / erp-mapping 的 mock ERP
// （ChainGuard/scripts/mock_erp_server.py，默认就读这个库）缺了它起不来。
//
// 干净检出上的症状是 "Process from config.webServer was not able to start.
// Exit code: 1"——只字不提缺的是数据库，而且只挂这两个套件（其余套件不起 mock ERP），
// 看起来更像 ERP 功能坏了。实测排查代价远大于这几行。
//
// 此前唯一的兜底是 CI 里一行 generate，等于把这个前置条件藏在流水线里：
// 本地 clone 下来直接跑门禁必踩，而 CI 永远绿，缺陷因此没有暴露渠道。
const DEMO_DB = resolve(API_DIR, 'demo_assets/enterprise/database/chainguard_enterprise_demo.db');
if (!existsSync(DEMO_DB)) {
  console.log(`=== 演示企业库缺失，正在生成：${relative(WEB_DIR, DEMO_DB)} ===`);
  // --db-only：只重建库，不碰 demo_assets 下那 60+ 个受版本控制的资产。
  if (run(PYTHON, ['scripts/generate_enterprise_demo_data.py', '--db-only'], { cwd: API_DIR }) !== 0) {
    console.error('演示企业库生成失败；erp-* 套件必然起不来，提前终止而不是让它们以 webServer 错误收场。');
    process.exit(1);
  }
}

const results = [];
for (const suite of suites) {
  console.log(`\n=== [${suite.name}] provisioning ===`);
  // src/webapi/database.py 的验收守卫要求绝对路径 + 文件名含 GUID。
  const dbPath = resolve(WORKSPACE, `${suite.name}-${randomUUID()}.db`).replace(/\\/g, '/');
  const databaseUrl = `sqlite:///${dbPath}`;
  const provisionEnv = { ...baseEnv, DATABASE_URL: databaseUrl };

  let status = run(PYTHON, ['-m', 'alembic', 'upgrade', 'head'], { cwd: API_DIR, env: provisionEnv });
  if (status === 0 && suite.seed) {
    const seedArgs = suite.seedArgs ? suite.seedArgs({ dbPath, workspace: WORKSPACE }) : [];
    status = run(PYTHON, [`scripts/${suite.seed}`, ...seedArgs], { cwd: API_DIR, env: provisionEnv });
  }
  if (status !== 0) {
    console.error(`[${suite.name}] provisioning failed`);
    results.push({ name: suite.name, ok: false, stage: 'provision', reason: 'provisioning failed' });
    continue;
  }

  console.log(`=== [${suite.name}] running ${suite.config} ===`);
  const jsonPath = resolve(ARTIFACTS, `${suite.name}-report.json`);
  const outputDir = resolve(ARTIFACTS, `${suite.name}-output`);
  // list 给人看进度，json 落文件给门禁判定；--trace/--output 从命令行覆盖，
  // 免得为了归档 trace 去改十个 playwright.*.config.ts。
  status = run(
    process.execPath,
    [
      PLAYWRIGHT_CLI, 'test', `--config=${suite.config}`,
      '--reporter=list,json',
      '--trace=retain-on-failure',
      `--output=${outputDir}`,
    ],
    {
      cwd: WEB_DIR,
      env: { ...baseEnv, [suite.dbEnv]: databaseUrl, PLAYWRIGHT_JSON_OUTPUT_NAME: jsonPath },
    },
  );

  const outcome = readOutcome(jsonPath);
  const expectedSkips = suite.expectedSkips ?? 0;
  if (!outcome) {
    results.push({ name: suite.name, ok: false, stage: 'test', reason: 'JSON 报告缺失或无法解析', outputDir });
    continue;
  }

  const reasons = [];
  if (outcome.failed > 0) reasons.push(`${outcome.failed} 个用例失败`);
  if (outcome.errors > 0) reasons.push(`${outcome.errors} 个套件级错误`);
  if (outcome.flaky > 0) reasons.push(`${outcome.flaky} 个 flaky`);
  // 跳过数必须与申报值一致。超出＝有主路径悄悄没跑；少于＝申报值过时，
  // 说明有人修好了用例却没下调 expectedSkips，同样要求改一行代码来确认。
  if (outcome.skipped > expectedSkips) {
    reasons.push(`跳过 ${outcome.skipped} 个，超出申报的 expectedSkips=${expectedSkips}`);
  } else if (outcome.skipped < expectedSkips) {
    reasons.push(`跳过 ${outcome.skipped} 个，少于申报的 expectedSkips=${expectedSkips}，请下调该值`);
  }
  // 计数全对但退出码非 0：reporter 之外的失败（webServer 起不来等），不能放过。
  if (!reasons.length && status !== 0) reasons.push(`playwright 退出码 ${status}`);

  results.push({
    name: suite.name, ok: reasons.length === 0, stage: 'test',
    reason: reasons.join('；'), outcome, expectedSkips, outputDir,
  });
}

console.log('\n===== acceptance gate summary =====');
for (const r of results) {
  const counts = r.outcome
    ? ` [pass ${r.outcome.passed} / fail ${r.outcome.failed} / skip ${r.outcome.skipped}(申报 ${r.expectedSkips}) / flaky ${r.outcome.flaky}]`
    : '';
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${counts}${r.ok ? '' : `  <- ${r.stage}: ${r.reason}`}`);
}

const failed = results.filter((r) => !r.ok);
const totalSkipped = results.reduce((sum, r) => sum + (r.outcome?.skipped ?? 0), 0);
console.log(`${results.length - failed.length}/${results.length} suites passed，累计跳过 ${totalSkipped} 个用例`);

if (failed.length) {
  console.log('\n失败套件的 trace / 截图：');
  for (const r of failed) {
    if (r.outputDir && existsSync(r.outputDir)) {
      console.log(`  ${r.name}: ${relative(WEB_DIR, r.outputDir)}`);
      console.log(`    npx playwright show-trace ${relative(WEB_DIR, r.outputDir)}/**/trace.zip`);
    }
  }
  console.log(`  JSON 报告：${relative(WEB_DIR, ARTIFACTS)}`);
}
process.exit(failed.length ? 1 : 0);
