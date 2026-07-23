# ChainGuard — 供应链中断应急决策系统

面向制造企业的供应链中断**应急决策**系统。核心是一条可审计的决策链：
库存风险前置触发 → 三 Agent 并行提案 → 约束穷举仲裁 → 经验回注 → 人工确认落库。

**所有对外数字都可现场复算**：决策链上的每一个指标都由确定性代码算出，
不经大模型生成。大模型仅用于自然语言表达，且有模板兜底。

---

## 一键启动演示

需要 **Python 3.13+** 与 **Node.js 20+**，无需数据库服务（演示用 SQLite）。

```powershell
# Windows
.\start-demo.ps1
```

```bash
# macOS / Linux
./start-demo.sh
```

脚本会依次完成：依赖安装 → 数据库迁移 → 演示数据播种 → 前端构建 → 启动服务。
完成后访问 **http://127.0.0.1:8000**。

演示账号（9 个角色，密码同为 `Demo@2026`）：

| 账号 | 角色 |
| --- | --- |
| `admin@chainguard.demo` | 系统管理员 |
| `boss@chainguard.demo` | 企业负责人 |
| `scm_lead@chainguard.demo` | 供应链负责人 |
| `buyer` / `warehouse` / `sales` / `finance` / `planner` / `auditor` | 采购 / 仓储 / 销售 / 财务 / 计划 / 审计 |

常用参数：

```powershell
.\start-demo.ps1 -Port 8080      # 换端口
.\start-demo.ps1 -SkipInstall    # 依赖已装，跳过安装
.\start-demo.ps1 -Fresh          # 清空演示库重建
```

> 登录接口限流 5 次/分钟，连续切换多个角色时请稍作间隔。

### 演示态为什么是单进程

前端构建产物由 FastAPI 直接托管，不起 umi dev server。这样现场不存在
首屏现编译、开发服务器 OOM、前后端端口错配、CORS 配置错误这几类事故。
开发时仍可前后端分离启动，见 `ChainGuard/docs/local_walkthrough.md`。

---

## 目录结构

| 目录 | 内容 |
| --- | --- |
| `ChainGuard/src/` | 决策内核与 Web API（FastAPI，`/api/v1`） |
| `ChainGuard/src/agents.py` | 采购 / 物流 / 财务三 Agent 的效用模型与提案生成 |
| `ChainGuard/src/arbitrator.py`、`constraint_solver.py` | 约束穷举与仲裁 |
| `ChainGuard/alembic/` | 数据库迁移（SQLite 与 PostgreSQL 双路径） |
| `ChainGuard/config/` | 权重、阈值等全部可调参数 |
| `ChainGuard/docs/` | 技术详解、答辩 Q&A、演示脚本、集成与部署指南 |
| `chainguard-web/` | 前端（Umi + Ant Design Pro） |

---

## 文档索引

| 文档 | 用途 |
| --- | --- |
| [答辩技术详解](ChainGuard/docs/答辩技术详解.md) | 每一步的公式与设计理由 |
| [demo_script.md](ChainGuard/docs/demo_script.md) | 演示流程脚本 |
| [defense_qa.md](ChainGuard/docs/defense_qa.md) | 追问预演 Q&A |
| [integration_guide.md](ChainGuard/docs/integration_guide.md) | ERP 对接与集成 |
| [deploy_guide.md](ChainGuard/docs/deploy_guide.md) | 部署指南 |
| [技术方案说明书](ChainGuard/docs/技术方案说明书.md) | 架构、性能实测数据、落地路径、已知限制 |
| [api_sla.md](ChainGuard/docs/api_sla.md) | 接口 SLA |
| [production_db_migration.md](ChainGuard/docs/production_db_migration.md) | PostgreSQL 迁移路径 |

---

## 测试与验收

```powershell
cd ChainGuard
pip install -r requirements-dev.txt
pytest -q                      # 后端单元与集成测试
```

```powershell
cd chainguard-web
npm test                       # 前端单元测试
npm run test:e2e:gate          # 端到端验收门禁（各套件独立库与端口）
```

验收门禁按套件读 Playwright 的 JSON reporter 判定，**跳过的用例必须在
`scripts/run-acceptance-gate.mjs` 里显式申报**，实际跳过数与申报值不一致即判失败——
避免"用例没跑"和"用例通过"显示成同一个绿灯。

持续集成见 `.github/workflows/ci.yml`：后端测试、前端测试、PostgreSQL 迁移与
约束验证、端到端验收门禁四条独立流水线。
