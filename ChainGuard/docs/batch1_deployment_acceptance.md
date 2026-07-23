# 批次 1 验收报告：部署态数据持久化与限流正确性

验收日期：2026-07-23
验收范围：产品界面、HTTP/API、4 worker 进程、PostgreSQL、Redis AOF、Docker
命名卷与备份、启动故障恢复、配置 fail-closed、代码与全量回归。

## 结论

**通过（发现 2 个问题并修复后复验通过）。**

- 校准注册表由 `workspace` 命名卷持久化，API 容器重建前后文件字节数与 SHA-256
  完全一致，治理页面状态不变。
- `workspace` 已进入真实备份范围；生成的归档包含租户
  `calibration_registry/<tenant-digest>/model_registry.json`。
- 登录限流计数由 Redis 在 4 个 API worker 间共享。连续 6 次真实界面提交中，前
  5 次进入登录校验，第 6 次返回 429；生产配置缺少共享存储时 API 进程拒绝启动。
- Redis AOF 命名卷在容器重建后保留尚未过期的计数；重建前后同一键的值均为 3，
  之后继续请求得到 `401、401、429`。
- 进程重启遗留的过期 `pending` / `running` 作业均会被原子回收为 `failed`；
  新鲜作业不受影响，4 worker 并发只认领一次。

## 界面到部署态证据

### 1. 登录限流

在生产 Web 镜像的 `/user/login` 页面通过真实表单连续提交 6 次：

| 次数 | 页面结果 |
|---:|---|
| 1—5 | 单条“账号或密码错误” |
| 6 | 单条“请求过于频繁，请稍后重试” |

API 日志对应前 5 次 401、第 6 次 429。Redis 键为登录路由的固定窗口桶，证明请求
未落到各 worker 私有内存。

验收中发现 429 原本会显示两个相同 toast：网络层与登录页各弹一次。登录请求现以
`silent: true` 调用统一网络层，由登录页独占错误呈现；前端回归锁定该契约。

### 2. 校准注册表持久化

管理员登录后打开 `/settings/thresholds`，页面真实展示“校准治理面板”“尚未确认，
不影响决策”“漂移体检：正常”。随后检查容器文件：

- 路径：`/app/.workspace/calibration_registry/<tenant-digest>/model_registry.json`
- 大小：490 字节
- 重建前 SHA-256：
  `96d3fd6184ba7324e03cfe06cc1384f19fb305831a78fc74177a89ce59f7de53`
- 强制重建 API 容器后：大小与 SHA-256 均不变
- 浏览器刷新后：上述治理状态仍正常展示

### 3. 真实备份

一次性执行 `postgres-backup` 后生成 PostgreSQL、`appdata`、`workspace` 三份归档。
`workspace` 归档的目录清单包含：

```text
./imports/
./calibration_registry/
./calibration_registry/<tenant-digest>/model_registry.json
```

### 4. Redis 容器重建

在隔离 Redis 写入 3 次登录计数，等待 AOF `everysec` 落盘后强制重建容器：

| 时点 | 计数 | TTL |
|---|---:|---:|
| 重建前 | 3 | 37 秒 |
| 重建后 | 3 | 16 秒 |

随后 3 次请求依次返回 `401、401、429`，证明重建没有制造“计数清零、瞬间不限流”
窗口。

### 5. 生产漏配 fail-closed

一次性 API 探针使用非 SQLite 数据库并显式移除 `RATE_LIMIT_STORAGE_URI`，进程在
导入应用时以 `RateLimitStorageNotConfigured` 退出（exit 1），未开始监听端口。

### 6. 遗留作业恢复

真实 PostgreSQL 中插入三条部署探针并重建 4-worker API：

| 探针 | 重建后 |
|---|---|
| 过期 `running` | `failed / CG-2503 / progress=100` |
| 过期 `pending` | `failed / CG-2503 / progress=100` |
| 新鲜 `running` | 保持 `running / progress=10` |

首次验收发现实现只回收 `running`，会让进程内队列遗留的 `pending` 永久命中去重
条件。修复后同时覆盖两态，并用“观测状态 + `updated_at`”双 CAS 守卫：既保证多
worker 只认领一次，也避免扫描后误杀刚被活跃 worker 推进的作业。

## 自动化验证

- 后端批次 1 定向回归：`30 passed`
- 后端全量回归（清除会把随机 localhost 测试服务代理成 403 的本机代理变量）：
  `842 passed, 4 skipped`
- 前端全量 Vitest：`74 passed`
- 生产前端构建：Webpack compiled successfully，postbuild 成功
- Python 静态检查：Ruff passed
- Compose 解析：`docker compose config --quiet` passed
- 补充检查：`git diff --check` passed

告警均为既有技术债：FastAPI `on_event` 弃用提示、scikit-learn SVC
`probability` 弃用提示、Alembic `path_separator` 提示，以及 jsdom
`getComputedStyle` 未实现噪声；未发现由本批次引入的回归。

## 本批次实现边界

- Redis 只承载带 TTL 的限流计数，不纳入业务备份；AOF 用于避免重启清零窗口。
- `workspace` 中包含不可静默丢失的校准基线，因此与 `appdata` 一起纳入备份。
- SQLite 单进程开发模式允许自动使用 `memory://`；非 SQLite 部署若未明确配置共享
  存储则拒绝启动。显式 `memory://` 仅供部署方确认单进程风险后使用。
