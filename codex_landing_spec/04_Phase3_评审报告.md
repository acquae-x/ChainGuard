# Phase 3 评审报告（结论：复审后有条件通过，见文末复审补记）

评审时间：2026-07-12。评审方式：直读磁盘逐文件核对（评审方沙盒不可用，未实际起容器——但阻断缺陷靠静态核对即可坐实）。

## 核验通过项

| 验收项 | 结果 |
|---|---|
| docker-compose | ✅ 五服务编排正确：secrets 全部 `:?` 强制注入无默认密码；migrate 一次性（alembic+seed）且 api 依赖其成功；postgres 仅内网 expose；healthcheck 齐全 |
| 前端镜像 | ✅ node 构建 + nginx-unprivileged 非 root；`/api/` 反代 api:8000 保留 URI（与后端 /api/v1 前缀吻合）；SPA fallback 正确 |
| 后端镜像 | ✅ 多阶段 wheel 构建、非 root appuser（但见缺陷 1） |
| 备份 | ✅ 02:00 cron gzip pg_dump、保留 7 天、恢复命令见部署文档 |
| CI | ✅ 后端 ruff+alembic+pytest / 前端 tsc+build，单仓与双仓两套工作流 |
| .gitignore | ✅ dist、.umi*、db-journal 已忽略 |
| refresh token | ✅ 全 HttpOnly Cookie（path 限定 /api/v1/auth）、登录/刷新轮换、响应体不再携带、Secure 可配 |
| 注册 | ✅ /auth/register 真实建租户+9 角色+首管理员，前端 registerTenant 已接；顺带消解了 Phase 2 的角色切换混合态风险 |
| backlog 五条 | ✅ data:view 改资源域授权（buyer 只能读 supplier）；通知已读入库+跨用户 404；imports confirm 状态机（failed 须显式 force，前端已传）；admin 补只读码且不加 readonly——处理得比要求更细 |
| 交付诚实度 | ✅ 如实声明无 docker 环境未跑容器验收、全量 pytest 在 Windows 工作区的既有失败未掩饰 |

## 缺陷

1. **【阻断】镜像内缺 `config/` 与 `data/`，容器里生成方案必失败**。新 Dockerfile 只 COPY `alembic.ini/alembic/src`；而决策作业链路 `run_demo → load_thresholds()` 读 `config/thresholds.yaml`，文件不存在直接 `FileNotFoundError`（config_loader.py:63 无兜底），作业以 CG-2502 失败。验收标准"注册→导入→演练"中的"演练"（生成方案）在部署栈上跑不通。`test_deployment.py` 只断言了排除 demo_assets，没测必需资产的存在。修法：Dockerfile 增加 `COPY --chown=appuser:appgroup config ./config` 和 `COPY --chown=appuser:appgroup data ./data`（data 目录容器内还有审计 jsonl 写入，需可写；建议 compose 给 /app/data 挂卷或明确接受临态）；test_deployment 补断言 config/data 在镜像内。
2. **【中】`src/db.py` 不认 compose 注入的 `postgresql+psycopg://` scheme**（只匹配 `postgresql://`），旧版 /scenarios、run_scenario、企业数据读取在容器内抛 ValueError。这些是 deprecated 演示端点，不阻断新链路，但要么 db.py 兼容 `postgresql+psycopg://`，要么在文档标注容器内旧端点不可用。
3. **【低】部署文档健康检查 URL 错误**：`http://localhost:8080/api/healthz` 经 nginx 保留 URI 转发为后端 `/api/healthz`，该路由不存在（healthz 在根路径）。容器 healthcheck 是直连的所以没事，但照文档冒烟会 404。改文档或在 nginx 加 `/healthz` 转发。

## 新增 backlog（不阻塞）

刷新令牌轮换是无状态 JWT，旧 refresh token 在到期前仍有效（无服务端吊销/重用检测）；企业级可加 jti 白名单或重用检测，列 Phase 4/加固项。

## 打回指令（原样转发实现方）

> Phase 3 评审不通过，按 `codex_landing_spec/04_Phase3_评审报告.md` 修复缺陷 1（必须）、2、3：
> 1. 后端 Dockerfile 补 COPY config/ 与 data/（保持 appuser 属主，data 可写），compose 为 /app/data 挂卷或书面说明临态可接受；test_deployment.py 补"镜像包含 config 与 data"断言。
> 2. src/db.py 兼容 postgresql+psycopg:// 前缀（或文档明示容器内旧演示端点不可用）。
> 3. 修正 deploy_guide.md 健康检查 URL（或 nginx 加 /healthz 路由）。
> 修完跑 `pytest tests/test_webapi.py tests/test_deployment.py -q` 贴原始输出，修复记录追加到 phase3_交付材料.md。

## 修复通过后的用户本机最终验收

1. `cd ChainGuard && cp .env.example .env` 填好五个必填变量。
2. `docker compose up -d --build`；`docker compose logs migrate` 确认迁移+seed 成功。
3. 浏览器 `http://localhost:8080`：注册新企业→登录→导入 csv→风险→事件→**生成方案（重点，缺陷 1 的验证点）**→审批→任务。
4. `docker compose stop api` 后刷新页面确认黄条降级；`docker compose start api` 恢复。
5. 次日检查 `ChainGuard/backups/postgres/` 出现备份文件（或手动 `docker compose run --rm postgres-backup` 触发一次）。
6. 推送到 GitHub 确认 CI 全绿。

## 复审补记（2026-07-12）

三处缺陷修复经评审方直读磁盘逐项核验，全部落地且质量良好：

1. ✅ Dockerfile 补 COPY config/data（appuser 属主）；实现方还自查出 `.dockerignore` 原本整体排除 `data/` 会让 COPY 失效的连带坑，改为仅排除运行时审计 jsonl——比打回指令要求的更完整。compose 为 /app/data 挂命名卷 appdata（首建自动以镜像内容初始化，判断正确）。test_deployment 新增 3 条断言（含 dockerignore 反例断言）。
2. ✅ db.py 兼容 `postgresql+psycopg://`，连接前归一化为 psycopg 可识别前缀，docstring 与报错文案同步更新。
3. ✅ 部署文档改为 compose ps / exec 内网探活，并解释 /api/healthz 404 为预期；选择改文档而非动 nginx 的理由（不触碰核验通过项）成立。

**未决项**：修复方与评审方的沙盒 VM 均故障，`pytest tests/test_webapi.py tests/test_deployment.py -q` 双方都未能实际运行（修复方已如实声明未运行、未伪造输出）。静态核对显示新增断言与被测文件逐字符一致，回归风险低。

**结论：有条件通过。** 条件：用户本机执行上述 pytest 命令回填输出至 phase3_交付材料.md「修复记录」，随后完成本报告六步最终验收（重点第 3 步容器内"生成方案"）。全部通过后 Phase 3 关闭，三阶段落地改造完成。

## 最终验收记录（2026-07-12，用户本机实测，Phase 3 关闭）

- pytest 27 passed（回填于 phase3_交付材料.md）。
- Docker Desktop + WSL2 就绪后 `docker compose up -d --build` 全栈启动（经历两个环境问题：拉镜像被墙→配 registry-mirrors 解决）。
- **实测发现并修复一个 Postgres-only 缺陷**：seed/注册在同一 flush 批次插入 tenants/roles/users，Postgres 外键校验拒绝（SQLite 不校验外键掩盖了该问题）。修复：seed.py 与 auth.py register 显式 `db.flush()` 固定插入顺序（评审方直接修复）。修复后迁移+seed 成功。
- 浏览器全链路通过：登录 → boss 终批（决策摘要/方案对比/审批链渲染正常）→ 自动生成 5 条任务 → 新建事件 → **容器内生成方案成功（3 方案，缺陷 1 修复的验证点）** → 注册新企业向导可走通。
- 停 api 刷新：登录页显示"后端服务暂不可用（502）"黄条，不白屏；start api 恢复。
- 手动备份成功：`backups/postgres/chainguard_20260712_123221.sql.gz`（注意：正确的手动触发命令是 `docker compose run --rm postgres-backup /usr/local/bin/backup-postgres`，不带脚本路径只会启动 02:00 定时器——部署文档待补，已列入改进清单）。
- CI：待用户推送 GitHub 后验证，不阻塞关闭。

验收中新发现的产品/工程问题统一登记于 `05_验收后改进清单.md`。
