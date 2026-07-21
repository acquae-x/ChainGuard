# Phase 5B 收尾批 C02/C03「节点健康视图」交付材料（2026-07-20）

规格来源：`phase5b_c02_c03_实现范围.md`。本文只覆盖 C02/C03。
C2 / C1 / A03 / A04 均已验收完成，本批**未回退、未重写**其中任何一个。
**代码未提交，其他未提交文件未清理。**

---

## 1. 变更文件清单

### 后端（ChainGuard/）

| 文件 | 性质 | 说明 |
|---|---|---|
| `src/webapi/node_health.py` | 新 | C02/C03 主体：四类节点健康计算、角色范围派生、降级与限制披露 |
| `src/webapi/routers/business.py` | 改（+2 路由 +1 import） | 新增 `GET /dashboard/node-health`、`GET /dashboard/my-nodes`，均用既有 `dashboard:view` |
| `tests/test_phase5b_c02_c03_node_health.py` | 新 | 36 例（N1–N31） |
| `scripts/seed_phase5b_c02_c03_e2e.py` | 新 | 三个隔离租户 + 一线四角色 + boss + 空数据租户 |

**零数据库迁移**：纯查询模块，未加表、未加列。
**未触碰**：`context_builder.py` / `risk_recompute.py` / `risk_explanation.py` / `impact_scope.py` / `models.py` /
`config/*.yaml` / `data/*.json` / `app.py`（Streamlit 的 `render_node_detail` 原样保留）。

### 前端（chainguard-web/）

| 文件 | 性质 | 说明 |
|---|---|---|
| `src/components/NodeHealthPanel/index.tsx` | 新 | 四档计数 + 类型/状态筛选 + 节点明细表 + 原因/阈值/传播来源 + 跳转；零本地推算 |
| `src/components/NodeHealthPanel/NodeHealthPanel.test.tsx` | 新 | 9 例（F1–F8 + mine 范围说明） |
| `src/components/index.ts` | 改（+1） | 导出面板 |
| `src/pages/Dashboard/index.tsx` | 改（+3） | 新增 `nodeHealth` / `myNodes` 两个 section |
| `src/pages/Dashboard/dashboardConfig.ts` | 改 | **删除四个写死的节点类 KPI 字面量**；一线四角色挂 `myNodes`，管理者侧挂 `nodeHealth` |
| `src/services/dashboard.ts` | 改（+2 函数） | `getNodeHealth` / `getMyNodes`，双模式；mock 模式如实返回不可用 |
| `playwright.node-health-api.config.ts` | 新 | 独立端口 8444/8445 与独立 DB |
| `e2e/node-health-api-acceptance.spec.ts` | 新 | E1–E10 |

---

## 2. 实际执行的命令与原始结果

全部在 Windows 本机（用户环境）实跑，**不是沙箱推断**。

### 2.1 C02/C03 后端单测

```
> python -m pytest tests/test_phase5b_c02_c03_node_health.py -q --no-header
36 passed, 2 warnings in 3.24s
```

### 2.2 后端全量回归

```
> python -m pytest tests/ -q --no-header
1 failed, 683 passed, 4 skipped, 14 warnings in 173.41s (0:02:53)

唯一失败：
  tests/test_phase5b_c2_entities.py::test_migration_upgrade_downgrade_upgrade_and_sqlite_constraints
```

**这条失败是改动前就存在的**，已用同口径基线锁定（把 `business.py` 换回 HEAD 版本，同一环境同一命令）：

```
> git stash push -- src/webapi/routers/business.py
> python -m pytest tests/test_phase5b_c2_entities.py::test_migration_upgrade_downgrade_upgrade_and_sqlite_constraints -q
1 failed, 1 warning in 2.24s          ← 基线同样失败
> git stash pop
```

其根因是子进程读取 alembic 输出时的 `UnicodeDecodeError: 'gbk' codec ...`（中文 Windows 控制台编码），
与 C02/C03 无关。A04 交付材料 §2.3 已记录同一条失败。

### 2.3 A03/A04/C1/C2 定向零回归

```
> python -m pytest tests/test_phase5b_a03_risk_explanation.py tests/test_phase5b_a03_risk_recompute.py \
    tests/test_phase5b_a04_impact_scope.py tests/test_phase5b_c1_tenant_decision.py \
    tests/test_phase5b_c2_entities.py tests/test_entities_c2.py tests/test_webapi.py -q
1 failed, 138 passed, 5 warnings in 39.21s     ← 失败集合与 §2.2 一致（同一条 migration）
```

### 2.4 前端单测与构建

```
> npx vitest run src/components/NodeHealthPanel
Test Files  1 passed (1)
     Tests  9 passed (9)

> npx vitest run                       （全量）
Test Files  18 passed (18)
     Tests  56 passed (56)

> $env:DATA_MODE="api"; npm run build
event - Build index.html
> node scripts/generate-route-access-map.cjs
generated docs/route-access-map.md            exit=0，0 error
```

### 2.5 真实 Chromium E2E（本批主要界面证据）

```
> python scripts/seed_phase5b_c02_c03_e2e.py
已生成 C02/C03 验收租户：tenant-c02-real-a / tenant-c02-real-b / tenant-c02-real-empty

> npx playwright test --config=playwright.node-health-api.config.ts
Running 1 test using 1 worker
[限流排队] 等待 51s 后继续登录
[限流重试] c02-boss-a@chainguard.test 第 1 次未登入，整窗等待后重试
  ok 1 e2e/node-health-api-acceptance.spec.ts:99:5 › C02/C03：节点健康概览、筛选、原因、跳转、角色范围、降级、隔离与脱敏 (2.4m)
  1 passed (2.6m)
```

真起 uvicorn（8444）+ 真起 umi dev（8445）+ 真 Chromium + seed 出来的三个隔离租户。

### 2.6 A04 浏览器回归（本批动了共享的 `components/index.ts` 与 Dashboard）

```
> python scripts/seed_phase5b_a04_e2e.py
> npx playwright test --config=playwright.impact-scope-api.config.ts
  ok 1 e2e/impact-scope-api-acceptance.spec.ts:58:5 › A04：事件与风险影响范围… (10.0s)
  1 passed (19.2s)
```

---

## 3. 设计上的三个关键取舍（必须单独说明）

### 3.1 只有物料节点是「算」出来的，其余三类不是

`config/thresholds.yaml` 里只有 `inventory_warning` 一组阈值，**没有**供应商可靠性阈值、
没有交期临近阈值、没有仓库健康阈值。因此：

- **物料节点**：严格走 `calculate_inventory_risk` → `measure_material`，红/黄/正常三档直接映射为
  异常/预警/健康，阈值经 `TenantContextBuilder` 解析，与 A03 解释和 C1 决策链路同源。
- **仓库/供应商/订单**：只用两种东西——**实体行上的事实判据**（可用量 < 安全库存、状态命中中断词表、
  承诺交期已过）与**从物料节点的传播**。每条 `reasons[]` 都标明是哪一种，传播型带 `derivedFrom` 可点回源物料。

给这三类现编一套加权评分是新算法，越界。响应里恒带 `CG-C024` 把这件事讲明白，界面上逐条渲染。

### 3.2 传播最多把供应商拉到「预警」，不拉到「异常」

"我供的料缺货"不等于"这家供应商自己出事了"。判成异常就是在替用户下一个数据支持不了的结论。
仓库与订单则不同：物料异常直接构成"这个仓/这张单有麻烦"，故传播为异常。

### 3.3 刻意没有做的两件事

- **不用 `reliability_score` 判健康**：没有它的阈值配置，凭空定一个就是发明算法。仅作原值展示。
- **不做"临近交期"预警**：需要一个"提前多少小时算临近"的阈值，配置里没有。只判"已逾期"这一事实比较。

---

## 4. 一处对既有界面的伪造数据清理

`dashboardConfig.ts` 里四个节点类 KPI 是**写死的演示字面量**，且不在 `Dashboard/index.tsx`
的 `KPI_SOURCE` 真值映射内，因此无论后端返回什么都永远显示同一个数字：

| 角色 | 原 KPI | 处置 |
|---|---|---|
| buyer | 负责供应商异常数 `1` | 删除，改由「我的节点」面板给真实供应商节点计数 |
| warehouse | 本仓预警 SKU `4` | 删除，改由「我的节点」面板给真实仓库节点计数 |
| sales | 受影响订单 `3` | 删除，改由「我的节点」面板给真实订单节点计数 |
| planner | 物料缺口 SKU `1` | 删除，改由「我的节点」面板给真实物料节点计数 |

性质与 A04 删掉的「客户等级 A」「预计延误 2 天」相同：伪造的业务结论。
F8 用例锁定这四个 key 与 title 不再出现在任何角色配置里。

---

## 5. 逐项验收对照

### 5.1 后端 N1–N31

| 编号 | 验收点 | 状态 | 证据 |
|---|---|---|---|
| N1 | 物料健康与引擎输出逐值一致 | ✅ | `test_n1_*`（直接与 `measure_material` 比对 riskIndex/supportHours/阈值） |
| N2 | 正常 → healthy | ✅ | `test_n2_*` |
| N3 | 算不了 → unknown，不并入 healthy | ✅ | `test_n3_*`（含 `CG-C022` 条数） |
| N4 | 仓库聚合去重 + 无假链接 + `CG-C023` | ✅ | `test_n4_*`（含 `CG-C027` 无仓库标识条数） |
| N5 | 可用量低于安全库存 → critical | ✅ | `test_n5_*` |
| N6 | 仓库传播指得回源物料 | ✅ | `test_n6_*` |
| N7 | 供应商中断词表回显原值 | ✅ | `test_n7_*` |
| N8 | 供应商传播封顶 warning | ✅ | `test_n8_*` |
| N9 | 无状态无供货 → unknown | ✅ | `test_n9_*` |
| N9b | `reliability_score` 不驱动健康 | ✅ | `test_n9b_*`（遍历全部 reason） |
| N10 | 逾期是事实比较非阈值 | ✅ | `test_n10_*` |
| N11 | 订单传播 + 健康订单无 reason | ✅ | `test_n11_*` |
| N12 | 已关闭订单排除并披露条数 | ✅ | `test_n12_*` |
| N13 | summary/byType 与节点分布自洽 | ✅ | `test_n13_*` |
| N14 | 空类型显式出现 + emptyReason | ✅ | `test_n14_*` |
| N15 | 空租户 `CG-C021`，零统计数字 | ✅ | `test_n15_*` |
| N16 | 类型/状态/关键字筛选 | ✅ | `test_n16_*`（并锁定 summary 是全量、filtered 是筛选结果） |
| N17 | 跳转指向真实资料页 | ✅ | `test_n17_*` |
| N18 | `CG-C024` 恒常声明 | ✅ | `test_n18_*` |
| N19 | 跨租户零泄露（整份 JSON 子串） | ✅ | `test_n19_*` |
| N20 | 同 id 实体不串味 | ✅ | `test_n20_*` |
| N21 | 脱敏走既有 `mask_for_requester` | ✅ | `test_n21_*` |
| N22–N24 | 一线四角色范围 | ✅ | `test_n22_n24_*`（参数化，用 seed 真实内置角色权限） |
| N25 | boss/finance → `CG-C031` | ✅ | `test_n25_*` |
| N26 | scm_lead/auditor 全域四类 | ✅ | `test_n26_*` |
| N27 | 角色范围 + 空租户 | ✅ | `test_n27_*` |
| N27b | `scope_for` 纯函数、无新权限码 | ✅ | `test_n27b_*` |
| N28 | 未登录 401 且零泄露 | ✅ | `test_n28_*` |
| N29 | 500 条截断披露真实总数 | ✅ | `test_n29_*` |
| N30 | `updatedAt` 是真实实体行时间 | ✅ | `test_n30_*` |
| N31 | 不引用演示数据源/编排 | ✅ | `test_n31_*`（源码扫描） + §2.2/§2.3 回归 |

### 5.2 前端 F1–F8

| 编号 | 状态 | 证据 |
|---|---|---|
| F1 四档计数取自 summary | ✅ | `NodeHealthPanel.test.tsx` |
| F2 固定顺序 + emptyReason | ✅ | 同上 |
| F3 `available=false` 零计数零节点 | ✅ | 同上 |
| F4 筛选以新参数重新请求 | ✅ | 同上（断言 `fetcher` 收到 `health: 'critical'`） |
| F5 跳转参数正确 / 仓库无链接 | ✅ | 同上 |
| F6 原因带观测值阈值 + 传播可跳转 | ✅ | 同上 |
| F7 限制逐条渲染 | ✅ | 同上 |
| F8 四个伪造 KPI 已删除 | ✅ | 同上（key + title 双重断言） |

### 5.3 E2E E1–E10（真实 Chromium，逐项截图）

| 编号 | 场景 | 状态 | 截图 |
|---|---|---|---|
| E1 | 管理者概览四档计数与后端逐值一致 | ✅ | `E1-manager-node-health-overview.png` |
| E2 | 「异常」+「供应商」筛选 | ✅ | `E2-node-health-filter-critical-supplier.png` |
| E3 | 异常原因含观测值、阈值与判据来源 | ✅ | `E3-node-health-reasons-and-limitations.png` |
| E4 | 跳转落在 `/data/material?id=` | ✅ | `E4-node-health-jump-to-material.png` |
| E5 | 一线四角色各自只见对口节点 | ✅ | `E5-my-nodes-{warehouse,supplier,material,order}.png` |
| E6 | boss 无对口类型 → `CG-C031` | ✅ | `E6-boss-overview-only.png` |
| E7 | 空租户 → `CG-C021`，页面无编造计数 | ✅ | `E7-empty-tenant-degraded.png` |
| E8 | 跨租户隔离（双向页面文本断言） | ✅ | `E8-tenant-b-isolated.png` |
| E9 | 脱敏（sales 无 `field:cost:view`） | ✅ | `E9-my-nodes-masked-amounts.png` |
| E10 | 375px 窄屏不横向溢出 | ✅ | `E10-my-nodes-mobile-375.png` |

截图目录：`ChainGuard/output/phase5b-c02-c03/screenshots/`。

---

## 6. 界面验收中发现并修掉的两处缺陷

跑完 E2E 后逐张看截图，发现两处**产品缺陷**（不是脚本问题），已修并重跑全部用例：

1. **节点表列宽失控**：原用 `scroll={{x:'max-content'}}`，异常原因文案很长时会把该列撑开，
   把「关键字段 / 数据更新时间 / 操作」整体挤出可视区，跳转按钮实际上看不见。
   改为固定列宽 + `tableLayout="fixed"` + `scroll={{x:1260}}`。
2. **限制文案里的 markdown 星号裸露**：`CG-C024` 的消息里带 `**不是独立评分模型**`，
   界面按纯文本渲染，用户看到的是字面的星号。已去掉标记符号。

---

## 7. E2E 里对登录限流的处理（需知悉）

`/auth/login` 是 **5 次/分钟的 IP 限流**（`src/webapi/routers/auth.py:43`），
本用例要覆盖 8 个角色账号，必然撞上。

**处置：在测试脚本里按配额排队 + 整窗重试**（`waitForLoginQuota` / `login`），
而**不是**去放宽生产端的限流阈值。限流是真实的安全约束，为了跑通验收把它调松，
就是在测一个不存在的系统。代价是该套件单次耗时约 2.6 分钟，配置超时相应放宽到 8 分钟。

---

## 8. 已知限制

1. **只有物料节点由引擎计算**。仓库/供应商/订单的健康 = 实体行事实判据 + 物料节点传播，
   **不是独立评分模型**；系统没有它们的阈值配置，本批不发明（恒落 `CG-C024`，界面上逐条可见）。
2. **不给节点健康分数**。四档是分类结论不是数字；给 0–100 分需新写加权公式，越界。
3. **不用 `reliability_score` 判定供应商健康**——无阈值配置，仅作原值展示。
4. **不做"临近交期"预警**——需要"提前多少小时"阈值，配置里没有；只判"已逾期"这一事实。
5. **仓库无独立主数据**，为 `inventory.warehouse_id/name` 聚合结果，恒落 `CG-C023`，
   `link` 为 `null` 而不是假链接；没有仓库标识的库存行如实计入 `CG-C027`，不静默丢弃。
6. **供应商中断判定依赖固定状态词表**（停产/停供/中断/暂停/受事件影响/已终止 + 4 个英文词）。
   词表外的自定义状态词会被判为 healthy——词表是可核对的常量，但确实是本方案的覆盖边界。
7. **批次血缘为资源类型级，非行级**（沿用 A03/A04 限制，实体表无 `source_import_job_id` 列）。
8. **单类 500 条截断**，超出时明示真实总数，未做分页游标。物料节点还受此约束保护：
   否则 11 万条数据下会对每个物料建一次快照。
9. **物流/路线不是节点**：`/data/logistics` 无对应 C2 实体表。
10. **mock 模式没有节点健康**。服务层如实返回 `CG-C033`，不在演示态编造节点。
11. **不改 Streamlit**：`app.py` 的 `render_node_detail` 原样保留。它读的是演示场景包的
    `scan_supply_chain(...).all_nodes`（其"节点"其实是演示事件），与本批的 C2 实体节点
    不是同一个概念，两者数据源不同、互不影响。
12. **全程不调用 LLM**，无任何生成文本；状态标签、原因标签与原因文案模板都是固定中文常量。
13. **未触碰**：`config/*.yaml`、`data/*.json`、风险/评分公式、orchestrator、`run_demo`。
    演示输出（70.25）不受影响。
