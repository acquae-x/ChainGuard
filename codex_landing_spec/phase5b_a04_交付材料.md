# Phase 5B 收尾批 A04「影响范围完整版」交付材料（2026-07-19）

规格来源：`phase5b_a04_实现范围.md`。本文只覆盖 A04。
A03 已验收完成，本批**未回退、未重写** A03；C02/C03 未开工。
**代码未提交。**

---

## 1. 变更文件清单

### 后端（ChainGuard/）

| 文件 | 性质 | 说明 |
|---|---|---|
| `src/webapi/impact_scope.py` | 新 | A04 主体：沿 C2 真实外键两跳遍历、去重、分组；`latest_batches()` 公共批次解析 |
| `src/webapi/risk_explanation.py` | 改（−30/+3） | `_provenance` 的批次解析抽出为 `impact_scope.latest_batches()` 并改为调用它。**响应结构逐字段不变** |
| `src/webapi/decision_detail.py` | 改（+12） | 补 `is_tier_key()`：客户等级字段按键名脱敏（见 §3 的说明，这是修既有漏洞） |
| `src/webapi/routers/business.py` | 改 | 新增 `GET /api/v1/risks/{id}/impact-scope`（`risk:view`）；`GET /api/v1/incidents/{id}/impact` 就地替换实现 |
| `tests/test_phase5b_a04_impact_scope.py` | 新 | 24 例 |
| `scripts/seed_phase5b_a04_e2e.py` | 新 | 两个隔离租户 + buyer + 无 incident:view 账号 + 孤立物料 |
| `output/phase5b-a04/verify_api.py` | 新 | 对真实运行服务的 HTTP 端到端验收脚本（47 项断言） |

### 前端（chainguard-web/）

| 文件 | 性质 | 说明 |
|---|---|---|
| `src/components/ImpactScopePanel/index.tsx` | 新 | 分组计数 + 可展开明细表 + 跳转；空组显式说明；不做任何本地推算 |
| `src/components/ImpactScopePanel/ImpactScopePanel.test.tsx` | 新 | 9 例（F1–F5 + 间接徽标 + 批次口径 + prefix + loading/error） |
| `src/components/index.ts` | 改 | 导出面板 |
| `src/components/RiskExplanationDrawer/index.tsx` | 改 | 新增第五段「影响范围」，独立加载、独立失败 |
| `src/components/RiskExplanationDrawer/RiskExplanationDrawer.test.tsx` | 改 | 补 `getRiskImpactScope` mock（不补会让 A03 的 8 例全挂） |
| `src/pages/Incident/Detail.tsx` | 改 | 影响范围页签换成面板；**删除硬编码的「客户等级 A」「预计延误 2 天」「替代供应商数 1」** |
| `src/services/risk.ts` | 改 | 新增 `getRiskImpactScope`，双模式 |
| `src/services/workflowStore.ts` | 改 | mock 的 `getImpact` 改为如实返回"仅 api 模式可用" |
| `playwright.impact-scope-api.config.ts` | 新 | 独立端口 8442/8443 与独立 DB；**按平台选 npm/npm.cmd**（既有配置写死 `npm.cmd`，非 Windows 一律起不来） |
| `e2e/impact-scope-api-acceptance.spec.ts` | 新 | E1–E8 |

**零数据库迁移**：纯查询模块，未加表、未加列。

---

## 2. 实际执行的命令与原始结果

后端全部在 Linux 沙箱执行。DB 重定向到 `/tmp`（挂载盘上 SQLite 落盘会 `disk I/O error`）。

### 2.1 A04 后端单测

```
$ python3 -m pytest tests/test_phase5b_a04_impact_scope.py -q
24 passed, 3 warnings in 3.93s                                    exit=0
```

### 2.2 A03 / C1 零回归

```
$ python3 -m pytest tests/test_phase5b_a03_risk_explanation.py \
    tests/test_phase5b_a03_risk_recompute.py \
    tests/test_phase5b_c1_tenant_decision.py -q
47 passed, 3 warnings in 7.93s                                    exit=0
```

### 2.3 全量回归

```
$ python3 -m pytest tests/ -q --ignore=tests/test_ui_routing.py
7 failed, 635 passed, 5 skipped, 4 warnings in 36.62s

失败明细：
  test_phase5b_c2_entities.py::test_migration_upgrade_downgrade_upgrade_and_sqlite_constraints
  test_phase5b_ocr.py::（6 例）
```

`test_ui_routing.py` 被排除：它 `import streamlit`，沙箱未装 streamlit（重依赖，与 A04 无关）。
6 例 OCR 失败：沙箱未装 `rapidocr` / `onnxruntime`（同上）。

**那条 migration 失败是改动前就存在的**，用同口径基线对比锁定：

```
# 基线：把 decision_detail.py 与 business.py 换回 HEAD 版本，同一环境同一命令
$ python3 -m pytest tests/test_phase5b_c2_entities.py tests/test_phase5b_c2_batch2.py \
    tests/test_entities_c2.py tests/test_webapi.py -q
1 failed, 82 passed, 3 warnings in 21.77s          ← 基线

# 改动后：同一命令
1 failed, 82 passed, 3 warnings in 21.61s          ← A04

$ diff <基线失败集合> <改动后失败集合>
无差异（IDENTICAL failure set）
唯一失败：test_migration_upgrade_downgrade_upgrade_and_sqlite_constraints
```

整份日志里 `impact_scope` 出现 **0** 次。

> **注**：同一批测试在挂载盘上跑是 `3 failed / 62 passed / 18 errors`，在 `/tmp` 上跑是
> `1 failed / 82 passed`。差额全部是挂载盘的文件系统限制（`disk I/O error` ×32、
> `PermissionError` ×13、`Operation not permitted` ×8），不是代码问题。
> 基线与改动后都在 `/tmp` 同一环境跑，对比是同口径的。

### 2.4 真实服务 HTTP 端到端验收（**本批的主要证据**）

不是 TestClient，是真起 uvicorn、真走 HTTP、真用 seed 出来的两个租户数据：

```
$ python3 scripts/seed_phase5b_a04_e2e.py
已生成 A04 验收租户：tenant-a04-real-a / tenant-a04-real-b

$ python3 -m uvicorn src.api:app --host 127.0.0.1 --port 8442   （后台）
$ python3 output/phase5b-a04/verify_api.py

=== E1 事件影响范围：直接影响与真实计数 ===
  分组计数 (total/direct/indirect):
  {"material":"2/1/1","inventory":"3/3/0","warehouse":"2/2/0",
   "supplier":"1/1/0","order":"1/1/0","customer":"1/0/1","task":"1/1/0"}
  PASS  库存 3 条直接（seed 三条库存行）
  PASS  仓库去重为 2 条
  PASS  任务 1 条直接（tasks.incident_id 外键）
  PASS  分组顺序固定且七组齐全
=== E2 间接影响：关系与路径可追溯 ===
  PASS  客户关系路径真的经过订单
        — ['material:MCU-A04', 'order:SO-MCU-A04', 'customer:CUS-MCU-A04']
  PASS  兄弟物料经由 supplier_materials
  PASS  排除条数如实为 1
=== E3 跳转目标是真实资料页 ===
  PASS  仓库无资料页时 link 为 null（不给假链接）
=== E5 空数据降级：范围有限，不编造 ===
  PASS  明示 CG-A041 范围有限
  PASS  除起点外零关联 — {'total': 1, ...}
=== E6 跨租户隔离 ===
  PASS  跨租户风险 404 / 跨租户事件 404
  PASS  404 响应体零泄露 — leaked=[]
  PASS  租户 B 的影响范围不含租户 A 任何实体
=== E7 字段脱敏 ===
  PASS  订单金额 / 违约罚金 / 毛利 / 供应商报价 / 客户等级 均为 ***
  PASS  有权限者看到真值 — 1800000.0
=== E8 权限门槛 ===
  PASS  无 incident:view → 403
  PASS  有 risk:view → 风险影响范围仍可看
=== 两跳上限 ===
  PASS  客户的其他订单未被纳入（未超两跳）

============================================================
通过 47 项，失败 0 项                                          exit=0
```

---

## 3. 一处对已验收模块的行为修正（必须单独说明）

`decision_detail.mask_for_requester` 原先对客户等级只做**自然语言**清洗
（`A类`、`等级为 A`），对**结构化字段**里的裸值 `"A"` 完全不设防。
A04 的影响范围会直接输出 `fields.customerLevel = "A"`，于是暴露了这个既有漏洞：
`field:customerLevel:view` 权限对结构化字段形同虚设。

**处置：在共享脱敏路径上补 `is_tier_key()` 按键名兜底**，而不是在 A04 里绕开。
理由：绕开只会让 A04 自己安全，decision-detail 与 A03 evidence 里的
`customerLevel` 仍然裸奔；这是权限体系的漏洞，该在权限体系里补。

**影响面**：无 `field:customerLevel:view` 的用户，在 decision-detail、JSON/PDF 导出、
A03 证据里看到的 `customerLevel` 类字段从明文变为 `***`。
这是**该权限本来就承诺的行为**，属于修复而非回归。
已用 §2.2 / §2.3 的回归锁定：A03 47 例全绿，全量失败集合与基线一致。

---

## 4. 逐项验收对照

| 编号 | 验收点 | 状态 | 证据 |
|---|---|---|---|
| B1 | 直接影响覆盖库存/供应商/订单 | ✅ | `test_b1_*` + HTTP E1 |
| B1b | 空分组仍显式出现 | ✅ | `test_b1b_*` |
| B2 | 客户为间接、路径经由订单 | ✅ | `test_b2_*` + HTTP E2 |
| B3 | 兄弟物料经共用供应商为间接 | ✅ | `test_b3_*` |
| B4 | 去重（一供应商供两物料只出现一次） | ✅ | `test_b4_*` |
| B5 | direct 优先于 indirect | ✅ | `test_b5_*` |
| B6 | 仓库聚合去重 + CG-A042 | ✅ | `test_b6_*`、`test_b6b_*` |
| B7 | 事件任务（tasks.incident_id） | ✅ | `test_b7_*` |
| B8 | 已关闭订单排除且披露条数 | ✅ | `test_b8_*` |
| B9 | 无起点 → CG-2511 且零泄露 | ✅ | `test_b9_*`（整份 JSON 子串断言） |
| B10 | 零关联 → CG-A041 范围有限 | ✅ | `test_b10_*` |
| B11 | 事件无来源风险 → CG-A043 | ✅ | `test_b11_*` |
| B12 | 跨租户 404 且响应体零泄露 | ✅ | `test_b12_*` + HTTP E6 |
| B13 | 同名同 id 实体不跨租户串味 | ✅ | `test_b13_*` |
| B14 | 事件端点就地替换为实体图谱 | ✅ | `test_b14_*`（断言 `dataMissing` 已消失） |
| B15 | 脱敏（金额 + 客户等级） | ✅ | `test_b15_*` + HTTP E7 |
| B16 | 权限门槛 403 | ✅ | `test_b16_*` + HTTP E8 |
| B17 | A03 零回归 | ✅ | 47 passed |
| B18 | C1/C2 零回归 | ✅ | 基线失败集合一致 |
| B19 | 两跳上限 | ✅ | `test_b19_*` + HTTP |
| B20 | 500 条截断且披露真实总数 | ✅ | `test_b20_*` |
| B21 | 关系表名真实、路径起于起点 | ✅ | `test_b21_*`、`test_b21b_*` |
| — | 供应商起点（外部录入型风险） | ✅ | `test_supplier_seeded_risk_*` |
| F1–F5 + 4 | 前端面板 9 例 | ⚠️ **未执行** | 见 §5 |
| E1–E8 | Chromium 浏览器 E2E | ⚠️ **未执行** | 见 §5 |

---

## 5. 未完成的验收（不粉饰）

**浏览器 E2E 与界面截图本次没有交付。** 原因是环境的硬限制，不是"忘了跑"：

1. **umi dev 无法启动**。`max dev` 启动时要 `rimraf src/.umi/`，挂载盘拒绝 `unlink`：
   ```
   Error: EPERM: operation not permitted, unlink
     '.../chainguard-web/src/.umi/appData.json'
   ```
   没有 dev server 就没有可截图的界面。
2. **Linux 无 Playwright 浏览器**。`~/.cache/ms-playwright` 不存在，系统也没有 chromium。
3. **vitest 卡死**。补齐了 `@rollup/rollup-linux-x64-gnu` 与 `@esbuild/linux-x64`
   两个 Linux 原生二进制后，vitest 能启动但在挂载盘上无限期停在 `RUN` 不出结果
   （挂载盘元数据操作极慢，`du -sh node_modules` 都会超时）。
4. **`DATA_MODE=api npm run build` 未执行**，同 1/3。
5. **`tsc --noEmit` 未跑完**，挂载盘上超过 3 分钟未结束。

**所以前端代码（面板组件、两处挂载、9 例 vitest、E2E spec）没有经过任何运行时或编译期
验证，这是本批最大的未验证面**，与 A03 交付时的情况相同。

后端则相反：24 例单测 + 全量回归 + **47 项真实 HTTP 端到端**全部实跑通过。

### Windows 上的补验收命令

```powershell
# 后端（应与沙箱结果一致）
pytest tests/test_phase5b_a04_impact_scope.py -q      # 期望 24 passed
pytest tests/ -q                                       # 全量

# 前端
cd chainguard-web
npx vitest run src/components/ImpactScopePanel          # 期望 9 passed
npx vitest run src/components/RiskExplanationDrawer     # 期望 8 passed（A03 回归）
$env:DATA_MODE="api"; npm run build                     # 期望 0 error

# E2E（先建隔离库并灌数据）
$env:IMPACT_SCOPE_DATABASE_URL="sqlite:///<guid>.db"
python ..\ChainGuard\scripts\seed_phase5b_a04_e2e.py
npx playwright test --config=playwright.impact-scope-api.config.ts

# A03 回归（本批动了 risk_explanation 与共享脱敏路径）
$env:RISK_EXPLAIN_DATABASE_URL="sqlite:///<guid>.db"
python ..\ChainGuard\scripts\seed_phase5b_a03_e2e.py
npx playwright test --config=playwright.risk-explanation-api.config.ts
```

### 沙箱里对 node_modules 的两处增量写入（需知悉）

为让 vitest 能启动，向挂载盘的 `node_modules` **增量写入**了两个 Linux 原生包：
`vitest/node_modules/@rollup/rollup-linux-x64-gnu/` 与 `@esbuild/linux-x64/`。
挂载盘不允许删除文件，故**未能清理**。二者按平台加载，不影响 Windows 侧运行；
`node_modules` 在 .gitignore 内，不会进入提交。如需清除，Windows 上直接删除这两个目录即可。
（另有一个 0 字节探针文件 `node_modules/.a04probe`，同样无法删除，同样无影响。）

---

## 6. 已知限制

1. **两跳上限**。第三跳（客户的其他订单、供应商的其他客户）不纳入——跳数越多"影响"的
   因果关系越弱，在 11 万条企业数据下只会制造噪音。
2. **仓库无独立主数据**。系统没有仓库表，仓库分组是 `inventory.warehouse_id/name` 的
   聚合结果，恒落 `CG-A042` 说明；仓库因此也没有资料页，`link` 为 `null` 而不是假链接。
3. **批次血缘为资源类型级，非行级**（沿用 A03 §2；实体表无 `source_import_job_id` 列，本批不加列）。
4. **不计算影响程度与损失金额**。A04 只回答"波及了哪些真实对象、经由什么关系"；
   缺口量/延误天数/损失估算属决策链路职责，在影响范围里给数字就必须新写评估公式，越界。
   这也正是旧版界面里「预计延误 2 天」之类字面量被删除而不是被"接上真数据"的原因——
   那个数字在当前模型下**没有真实来源**。
5. **单类 500 条截断**，超出时明示真实总数，未做分页游标。
6. **物流/路线未纳入**：`/data/logistics` 没有对应的 C2 实体表，无法沿真实外键遍历。
7. **mock 模式没有影响范围**。`workflowStore` 的演示数据之间不存在外键关系，
   服务层如实返回 `CG-A046`，不在演示态编造关系。这会让 mock 模式的事件详情
   「影响范围」页签从"四张表"变成一句说明——**这是有意的**：那四张表原本就是
   互不相干的演示数据并排摆放，并非影响范围。
8. **A04 全程不调用 LLM**，无任何生成文本；关系标签是固定中文常量。
9. **未触碰**：`config/*.yaml`、`data/*.json`、风险/评分公式、orchestrator、`run_demo`。
   演示输出（70.25）不受影响。
