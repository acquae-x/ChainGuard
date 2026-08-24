# 本地上手体验（api 模式，真实前后端）

面向"我要自己点一遍"的场景。全程约 5 分钟。Windows 上用 Git Bash 或 PowerShell 均可，
下面命令以 Git Bash 为准（PowerShell 把 `export A=B` 换成 `$env:A="B"`）。

## 0. 前提

- Python 依赖与前端依赖已装好（见 `chainguard-build-and-env`）。
- 需要两个终端窗口：一个跑后端，一个跑前端。

## 1. 建库 + 灌演示数据（终端 A，只需做一次）

```bash
cd ChainGuard
export DATABASE_URL=sqlite:///./_demo_run.db
export SEED_DEMO_PASSWORD=Demo@1234
export JWT_SECRET=dev-demo-secret

python -m alembic upgrade head
python -c "from src.webapi.seed import seed; seed()"
```

> `JWT_SECRET` 不设，登录会 500；`SEED_DEMO_PASSWORD` 不设，seed 会直接抛错。
> `_demo_run.db` 已在 .gitignore 里，是一次性的本地库，随时可删了重来。

## 2. 起后端（终端 A，保持运行）

```bash
python -m uvicorn src.api:app --port 8000
```

后端示例使用 8000；前端可通过 `API_PROXY_TARGET` 修改 `/api` 代理目标。

## 3. 起前端（终端 B，保持运行）

```bash
cd chainguard-web
PORT=8001 DATA_MODE=api npm run dev
```

`PORT=8001` 用于避免与后端的 8000 端口冲突。
`DATA_MODE=api` 表示走真后端；不加也默认 api，加上是为了明确。

打开 http://localhost:8001

## 4. 账号

统一密码 `Demo@1234`，账号是 `{角色}@chainguard.demo`：

| 账号 | 角色 | 看这个角色是为了 |
|---|---|---|
| `boss@chainguard.demo` | 老板 | 经营看板、审批高风险 |
| `scm_lead@chainguard.demo` | 供应链负责人 | 生成方案、提交审批（主线角色） |
| `admin@chainguard.demo` | 企业管理员 | 系统设置、用户与权限 |
| `buyer@chainguard.demo` | 采购 | 对照脱敏：看不到成本字段 |

> 登录限流 5 次/分钟。连续换号试的时候慢一点，否则第 6 次会静默失败。

## 5. 建议的体验路线

### A. 决策主线（scm_lead）
1. 「应急事件」→ 打开 `INC-20260709-001` 苏州芯片封测厂停产
2. 进「方案生成」→ 顶部会显示**数据质量提示**（本演示事件有一项估算字段）
3. 点「生成方案」→ 多 Agent 推演 → 出 3 个方案（1 个推荐、1 个备选、1 个不可行并说明违反了哪条硬约束）
4. 选推荐方案 → 提交审批

### B. 审批（boss）
「审批中心」→ 批准刚才提交的方案 → 系统自动派发 5 条执行任务给对应角色

### C. 报表（boss）
「报表看板 → 经营看板」：净收益 / 避免损失 / 风险事件数。
注意**「平均响应」显示"数据缺失"**——这是刻意的：没有已决审批就不可测量，不伪造成 0。
把右上角时间范围切到"近 3 个月"会重新请求后端，数字会变。

### D. 脱敏对照（buyer vs boss）
同一个方案页，`buyer` 看不到成本/利润字段（无 `field:cost:view` 权限），`boss` 能看到。

### E. 行级数据权限（admin）
1. 「系统设置 → 数据权限」→ 把「采购人员」改成「本部门」→ 保存
2. 换 `buyer` 登录 → 「应急事件」列表变成**暂无数据**（演示事件属于销售部，buyer 在财务部）
3. 直接访问该事件详情 URL → **404**（不是 403：403 等于确认记录存在，属于信息泄漏）
4. 改回「全企业」→ 事件立刻又出现

### F. 数据驱动参数（admin）
「系统设置 → 风险阈值」：左边是专家默认值、右边是数据驱动建议，
**建议不会自动生效**，必须点「人工确认并应用」才写入租户配置。
演示租户没导过历史决策，所以样本为 0；要看到真实建议需要先导入历史数据（见下）。

## 6. 想看"参数由数据算出来"的完整闭环

演示租户默认用的是专家参数。要跑数据驱动这条路：

1. 用 `admin` 或 `scm_lead` 进「数据管理 → 数据导入」
2. 上传 `ChainGuard/demo_assets/enterprise/csv/historical_decisions.csv`（600 条历史决策）
3. 走完预检 → 确认 → 执行
4. 回「系统设置 → 风险阈值」，此时会出现基于这 600 条算出的建议值

也可以不开界面，直接看算出来的数：

```bash
cd ChainGuard
python -c "
import csv, io
from src.parameter_calibration import calibrate_inventory_risk_weights, calibrate_trigger_threshold
from src.config_loader import load_risk_weights
rows = list(csv.DictReader(io.open('demo_assets/enterprise/csv/historical_decisions.csv', encoding='utf-8-sig')))
w = {k: v for k, v in calibrate_inventory_risk_weights(rows).items() if not k.startswith('_')}
print('专家值  :', load_risk_weights()['inventory_risk_weights'])
print('数据算出:', w)
print('触发阈值:', calibrate_trigger_threshold(rows, w))
"
```

## 7. 收摊

两个终端各按一次 `Ctrl+C`。想彻底重来就删掉 `ChainGuard/_demo_run.db` 再从第 1 步开始。
