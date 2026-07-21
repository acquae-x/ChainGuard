# Phase 5B 收尾批 A03「实时风险解释」交付材料（2026-07-19）

规格来源：`phase5b_a03_实现范围.md`。本文只覆盖 A03，未开工 A04 / C02 / C03 或其他收尾模块。
**代码未提交。**

---

## 1. 变更文件清单

### 后端（ChainGuard/）

| 文件 | 性质 | 说明 |
|---|---|---|
| `src/webapi/context_builder.py` | 改（+101/−25） | 抽 `build_material_snapshot()` / `snapshot_for_material_id()` / `MaterialSnapshot`；`build()` 在其上补事件、运输、派生段。纯重构，行为不变 |
| `src/webapi/risk_recompute.py` | 新 | 库存风险重算：确定性 id、幂等、状态机。分数一律由 `calculate_inventory_risk` 算出 |
| `src/webapi/risk_explanation.py` | 新 | A03 解释主体：verdict / drivers / deltas / evidence / provenance / decisionLink / limitations |
| `src/webapi/routers/business.py` | 改 | `POST /api/v1/risks/recompute`（`risk:manage`）、`GET /api/v1/risks/{id}/explanation`（`risk:view`） |
| `src/webapi/seed.py` | 改 | 去硬编码：先落实体再重算；`risk-1` 标注为外部录入来源 |
| `tests/test_phase5b_a03_risk_recompute.py` | 新 | 17 例 |
| `tests/test_phase5b_a03_risk_explanation.py` | 新 | 18 例 |
| `scripts/seed_phase5b_a03_e2e.py` | 新 | 两个隔离租户 + 只读账号 + 无库存物料 |

### 前端（chainguard-web/）

| 文件 | 性质 | 说明 |
|---|---|---|
| `src/services/risk.ts` | 改 | `getRiskExplanation` / `recomputeRisks`，双模式；mock 模式如实返回"仅 api 模式可用"，不编造解释 |
| `src/components/RiskExplanationDrawer/index.tsx` | 新 | 四段式抽屉：结论 / 驱动因素 / 证据来源 / 数据来源与限制 |
| `src/components/RiskExplanationDrawer/RiskExplanationDrawer.test.tsx` | 新 | 7 例（F1–F5 + 外部来源 + 快照） |
| `src/components/index.ts` | 改 | 导出抽屉 |
| `src/pages/Risk/List.tsx` | 改 | 每行「风险解释」入口（`risk:view` 即可） |
| `src/pages/Risk/Overview.tsx` | 改 | 「重新扫描风险」按钮，`access.canManageRisk` 门槛 |
| `src/pages/Incident/Detail.tsx` | 改 | 来源风险逐条可点开同一抽屉 |
| `playwright.risk-explanation-api.config.ts` | 新 | 独立端口 8440/8441 与独立 DB |
| `e2e/risk-explanation-api-acceptance.spec.ts` | 新 | E1–E9 |

**零数据库迁移**：新数据全部落 `risks.details` JSON，实体表未加列。

---

## 2. 实际执行的命令与原始结果

全部在 **Linux 沙箱**执行（限制见 §4）。DB 重定向到 `/tmp`，因为 `test_tmp/` 在挂载盘上会 `disk I/O error`。

```
$ python3 -m pytest tests/test_phase5b_a03_risk_recompute.py -q
17 passed, 4 warnings in 4.31s                                    exit=0

$ python3 -m pytest tests/test_phase5b_a03_risk_explanation.py -q
18 passed, 4 warnings in 4.45s                                    exit=0

$ python3 -m pytest tests/test_phase5b_a03_risk_recompute.py tests/test_phase5b_a03_risk_explanation.py -q
35 passed, 4 warnings in 6.85s                                    exit=0

$ python3 -m pytest tests/test_webapi.py tests/test_entities_c2.py \
    tests/test_phase5b_c2_entities.py tests/test_phase5b_c2_batch2.py \
    tests/test_phase5b_c1_tenant_decision.py -q
3 failed, 74 passed, 4 warnings, 18 errors in 18.50s

# 同口径 HEAD 基线（把 4 个改动文件换回 HEAD 版本后重跑）
3 failed, 74 passed, 4 warnings, 18 errors in 15.99s

$ diff <失败集合-基线> <失败集合-改动后>
无差异：失败集合完全一致

$ python3 -m ruff check src/webapi/risk_explanation.py src/webapi/risk_recompute.py \
    tests/test_phase5b_a03_risk_explanation.py scripts/seed_phase5b_a03_e2e.py
All checks passed!
```

那 3 failed / 18 errors 全部是沙箱文件系统问题（`disk I/O error` ×32、`PermissionError` ×13、
`Operation not permitted` ×8，指向 `.workspace/imports/` 与 SQLite 落盘），
改动前后逐条一致，且整份日志里 `context_builder` / `risk_recompute` / `risk_explanation` 出现 0 次。

---

## 3. 逐项验收对照

| 编号 | 验收点 | 状态 | 证据 |
|---|---|---|---|
| B1 | 分数等于引擎函数输出（逐位） | ✅ | `test_b1_recomputed_score_equals_engine_function_output` |
| B2 | 贡献之和 == 风险指数 | ✅ | `test_b2_*`（模块级 + API 级各一） |
| B3 | 当前值 vs 阈值显式（15h / 红线 24h） | ✅ | `test_b3_current_value_versus_threshold_is_explicit` |
| B4 | 租户配置 vs 专家默认标注 | ✅ | `test_b4_threshold_source_is_labelled_expert_default_without_tenant_config` |
| B5 | 证据覆盖四类实体 + 真实更新时间 | ✅ | `test_b5_evidence_covers_four_entity_kinds_with_real_update_times` |
| B6/B7/B8 | 无物料/无日消耗/无库存 → 可渲染限制 | ✅ | `test_b6_*`、`test_b7_b8_*`（断言响应中无任何数字） |
| B9 | 已消除 → 快照且标注 | ✅ | `test_b9_*`、`test_ignored_risk_is_also_reported_as_a_snapshot` |
| B10 | 估算值自曝 | ✅ | `test_b10_estimated_order_financials_are_disclosed_in_limitations` |
| B11 | 跨租户 404 且响应体不含对方物料/仓库/供应商名 | ✅ | `test_b11_cross_tenant_explanation_is_404_and_leaks_nothing` |
| B12 | 重算不跨租户 | ✅ | `test_b12_recompute_never_crosses_tenants` |
| B13 | 无 `field:*:view` → 金额 `***` | ✅ | `test_b13_requester_without_field_permissions_sees_masked_money` |
| B14 | 权限门槛（解释 `risk:view`，重算 `risk:manage`） | ✅ | `test_b14_*`、`test_recompute_still_requires_risk_manage_*` |
| B15 | C1 零回归 | ✅ | C1 12 passed；基线失败集合一致 |
| B16 | 阈值与 C1 配置解析同源 | ✅ | `test_b16_trigger_threshold_matches_the_c1_configuration_path` |
| B17 | ignored / incident_created 不被覆盖 | ✅ | `test_b17_*` ×2、`test_watching_is_a_human_mark_*` |
| B18 | 幂等（连 `updated_at` 都不动） | ✅ | `test_b18_second_recompute_writes_nothing_at_all` |
| B19/B20/B22 | resolved 产生 / 复发 / 不漂移 | ✅ | 对应三例 |
| B21 | 不碰非重算来源风险 | ✅ | `test_b21_external_and_manual_risks_are_untouched_by_recompute` |
| B23 | seed 去硬编码 | ✅ | `test_b23_*` ×2（含源码不含字面量分数断言） |
| B24 | 外部来源风险标注而非伪造 | ✅ | `test_b24_external_event_risk_is_labelled_not_fabricated` |
| F1–F5 + 2 | 前端抽屉 7 例 | ⚠️ 未执行 | 见 §4 |
| E1–E9 | Chromium E2E | ⚠️ 未执行 | 见 §4 |

---

## 4. 未完成的验收（必须在 Windows 上补）

**这是本次交付最重要的一段，不粉饰。**

1. **前端单测未执行**。沙箱里 `npx vitest` 启动失败：`Cannot find module @rollup/rollup-linux-x64-gnu`
   ——`node_modules` 是 Windows 上装的，缺 Linux 原生二进制。修它需要 `npm i`，
   而 `node_modules` 在挂载盘上，重装会破坏你 Windows 侧的安装，**故意没做**。
2. **`DATA_MODE=api npm run build` 未执行**，同上。
3. **全项目 `tsc --noEmit` 未跑完**，挂载盘上超过 4 分钟未结束，已终止。
   所以前端代码**没有经过任何编译期验证**，这是本批最大的未验证面。
4. **Chromium E2E 未执行**。E2E 需要同时起 uvicorn 与 `npm.cmd run dev`（配置里就是 `npm.cmd`，Windows 专用）。
5. **截图为零**。E2E 没跑，`output/phase5b-a03/screenshots/` 下没有任何文件。
   规格里要求的"真实产品界面截图"**本次没有交付**。

### Windows 上的补验收命令

```powershell
# 后端
pytest tests/test_phase5b_a03_risk_recompute.py -q        # 期望 17 passed
pytest tests/test_phase5b_a03_risk_explanation.py -q      # 期望 18 passed
pytest tests/test_phase5b_c1_tenant_decision.py -q        # 期望 12 passed
pytest tests/ -q                                          # 全量，沙箱未能跑完

# 前端
cd chainguard-web
npx vitest run src/components/RiskExplanationDrawer       # 期望 7 passed
$env:DATA_MODE="api"; npm run build                       # 期望 0 error

# E2E（先建隔离库并灌数据）
$env:RISK_EXPLAIN_DATABASE_URL="sqlite:///<guid>.db"
python ..\ChainGuard\scripts\seed_phase5b_a03_e2e.py
npx playwright test --config=playwright.risk-explanation-api.config.ts
```

**注意**：`seed()` 在 `tenant-demo` 已存在时直接返回，去硬编码逻辑不会生效——
验证 B23 必须用干净的库。

---

## 4b. E2E 选择器修复（2026-07-19 第二轮）

**你观察到的失败**：E2 步「界面数值等于接口数值」触发 Playwright strict mode，
同一数值被两个元素命中。

**根因**：断言依赖文案子串。结论区渲染「风险指数 78.75」，触发规则渲染
「库存风险指数 78.75 超过触发阈值 70」——后者包含前者，正则必然命中两处。
**这是验收脚本缺陷，不是产品功能错误**：两处都显示 78.75 正是预期行为
（结论给判定，规则给人话），产品侧无需改动。

**修法**：给抽屉补 19 个 `data-testid` 稳定锚点，断言全部改为唯一定位 + 精确文本比对。

| 锚点 | 用途 |
|---|---|
| `risk-explanation-drawer` | 抽屉内容根节点（与 antd Modal 同为 `role=dialog`，需区分） |
| `risk-explanation-index` / `-threshold` | 结论区指数与阈值，各自独立 span |
| `risk-explanation-rule` | 触发规则（含同一数值，正是污染源） |
| `risk-explanation-warning-level` / `-threshold-source` | 预警等级、阈值来源徽标 |
| `risk-driver-{key}-current` / `-threshold` | 四维当前值与红黄线 |
| `risk-evidence-{entity}-{id}` / `risk-evidence-link-{entity}-{id}` | 证据卡片与跳转按钮 |
| `risk-explanation-unavailable-title` / `-message` / `risk-explanation-code` / `-snapshot` | 降级与快照态 |
| `risk-explanation-declared-origin` / `-notice` / `-driven-impact` | 外部录入态 |
| `risk-limitation-{code}` | 逐条限制 |

锚点一律挂在原生 `span`/`div` 上，不依赖 antd 对 `Alert`/`Card` 的 `data-*` 透传
（该行为我无法在沙箱验证，不赌）。

**同一轮里主动修掉的另外三处同类隐患**（尚未跑到，但必然会踩）：

1. **行定位歧义**：外部录入风险的 `objectName`「A03主控芯片供应商」是计算型风险
   「A03主控芯片」的**超串**，`filter({hasText: /A03主控芯片/})` 会同时命中两行。
   改为先从接口取风险编号，再按 `code` 定位，并加 `toHaveCount(1)` 前置断言。
   E8 忽略、E5 快照三处一并改。
2. **`role=dialog` 冲突**：忽略弹窗（Modal）与解释抽屉（Drawer）同为 `role=dialog`，
   原先 `page.getByRole('dialog')` 在弹窗存在时会歧义。改为 testid 根节点 +
   `filter({hasText:'忽略风险'})` 分别锚定。
3. **E9 形同虚设**：原 E9 在没有外部录入风险的租户里断言「不是 declared」，
   等于没测。已在 `seed_phase5b_a03_e2e.py` 补一条真实的 `origin=external_event` 风险，
   E9 改为从界面验证来源标注、`CG-A034` 限制、以及"不渲染指标推导但渲染驱动影响"。

**前端单测同步收紧**：vitest 7 例 → 8 例，全部改用 testid，并新增一例专门锁定
「结论区指数锚点唯一，不被触发规则里的同一数值污染」——即这次失败的回归护栏。

修复后**仍未执行**：vitest、build、E2E 在沙箱都跑不了（原因见 §4），
上述修复是**未经运行的代码**。

---

## 5. 已知限制

1. **证据批次血缘为资源类型级，非行级**。实体表无 `source_import_job_id` 列，本批不加列不迁移。
   响应里 `provenance.scope = "resource_type"` 显式声明，前端文案写"最近一次导入批次（非本行血缘）"。
2. **重算只覆盖库存风险一类**。供应/物流/需求/质量四类没有对应引擎评分函数，
   仍需外部录入，在界面上以 `origin=external_event` 标注来源——**标注来源而不是伪造计算**。
3. **无调度器自动重算**，风险刷新依赖人工点「重新扫描风险」。同步单次，
   1 万物料级可能超时，未做分页/限流。
4. **重算不发 D3 通知**，高风险新增时用户不会收到铃铛提醒。
5. **`deltas` 需要至少两次重算**才有对比基线，首次显示"首次计算，无对比基线"。
6. **mock 模式没有风险解释**。`mockData.ts` 无结构化实体，服务层如实返回 `CG-A035`，
   不在演示态编造驱动因素。mock/api 双源不一致属既有问题（同 D3 铃铛），不在本批。
7. **A03 全程不调用 LLM**。叙述取自 `calculate_inventory_risk` 的 `explanation[]`。
