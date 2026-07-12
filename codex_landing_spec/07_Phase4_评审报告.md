# Phase 4 评审报告（结论：已通过并关闭，见文末实测记录）

评审时间：2026-07-12。评审方式：直读磁盘逐项对照 05 清单核验代码与配置。

## 核验通过项（全范围）

| 项 | 结果 |
|---|---|
| A1 | ✅ 上传后立即调服务端 preflight 并在向导展示"最终口径"报告；浏览器解析仅保留交互用途，不再裁决 |
| A2 | ✅ 任务统一由 `_create_execution_tasks` 创建（幂等）：负责人为本租户 active 真实用户 id、高 T+1/中 T+3 截止、改派校验 CG-2404，有测试 |
| A3 | ✅ mapper 对齐引擎真实键（proposal_title/proposal/reasoning，已与 agents.py 输出核对）；缺失字段 `explanation.dataMissing` 显式标记，不再伪造序号兜底，有测试锁定 |
| A4 | ✅ 按风险关键词匹配 data_records 尽力返回四维影响，逐维 dataMissing 标记 |
| A5 | ✅ 状态机：高风险 approve→pending_countersign→会签/超时放行→approved→建任务；拒签必填理由回 planning；`COUNTERSIGN_TIMEOUT_HOURS` 可配；启动线程每 5 分钟扫描（系统首个调度器）；超时放行审计+通知财务追认。审批测试按要求显式重写并新增三条（会签前无任务/超时放行/拒签打回），未改弱断言 |
| B1–B5 | ✅ 全部 apiMode 门控：无 Demo@1234 预填与提示、验证码 tab 隐藏、注册企业名为普通输入（autoComplete=organization）、授权码 disabled"即将上线"、演练/切换角色隐藏 |
| B6/B7 | ✅ 文档补手动备份命令；webhookConfig 接真实 GET/PUT 端点 |
| E-2 | ✅ 白名单扩 pdf/png/jpg；ingest_files 级联，成功则落 normalized.csv 复用既有管线；无 OCR 后端时 manual_required + 原文件留 staging + 明确文案（符合三选一判定第三种）；前端 accept 同步、二进制不进 SheetJS |
| F1 | ✅ export/import-images.ps1 + 文档离线安装节 |
| F2 | ✅ OperationalError/DBAPIError → 503 CG-5030，前端黄条自动生效 |
| F3/F4 | ✅ json-file 50m×5 轮转；api 2CPU/2G、postgres 1CPU/1G；容量口径入文档 |
| F5 短期 | ✅ 备份容器只读挂 appdata，tar 归档 + 7 天清理 |
| F7–F9 | ✅ TLS（Caddy/nginx）、RPO/RTO 与 WAL 选项、.env ACL 与密钥轮换（含 JWT 换钥全员下线告知）均入文档 |
| 交付诚实度 | ✅ 495 passed 原始输出 + E-2 降级路径 TestClient 实录；沙盒受限处（Windows 权限、esbuild EPERM）如实注明并在可用环境重跑 |

## 须修项

1. **【须修】会签超时起算点错误**：`release_expired_countersigns` 用 `approval.created_at`（提交时刻）判断超时，而非进入 `pending_countersign`（boss 批准）时刻。若 boss 在提交 4 小时后才批准，下一轮扫描（≤5 分钟内）立即自动放行——财务被完全绕过，D1 的管控意图在迟批场景下失效。修法：批准动作发生时记录进入会签态的时间（approval.history 已含 approve 动作时间，扫描时解析最后一次 approve 的 time；或新增 `countersign_requested_at` 列更干净）。补回归测试："提交 5 小时后 boss 批准 → 立即扫描 → 不放行"。

## 建议项（可并入同批小修或 backlog）

2. 调度器在每个 uvicorn worker 各跑一份（4 workers=4 个扫描器），同一审批单存在并发放行的良性竞态（任务创建有幂等保护，但仍建议扫描查询加 `with_for_update(skip_locked=True)`，SQLite 路径跳过）。
3. impact 关键词集合含风险 details 的数值（如评分 92、延误小时数），子串匹配易误命中无关记录；建议仅取字符串值且长度 ≥2。

## 结论

范围完整、质量高、证据可信。修复须修项 1（含回归测试）并跑通 `pytest tests/test_webapi.py -q` 后 Phase 4 通过；届时用户本机做一轮增量实测（高风险审批会签链路 + 导入一张图片看 manual_required + 停 postgres 看黄条）即可关闭。

## 复核补记（2026-07-12）

须修项 1 修复核验通过：`_countersign_requested_at` 解析 history 最后一次 approve 时间（时区安全、无记录保守不放行）；建议项 2 一并完成（`with_for_update(skip_locked=True)`）；"迟批不放行"回归测试到位，22 项审批测试通过。复核发现一处残留：approve 写 history 用无时区 `datetime.now()`，扫描器按 UTC 解读，非 UTC 主机上超时窗口偏移（东八区 4h→实际 12h；容器内 UTC 无影响）——已由评审方一行修正为 `astimezone()` 带时区写入。**待用户本机重跑 `pytest tests/test_webapi.py -q` 确认后，Phase 4 进入增量实测。**建议项 3（impact 数值误匹配）转入 backlog。

## 增量实测发现与修复（2026-07-12，评审方直接修复）

实测确认状态机正确（boss 批准→待会签黄条+审批链更新+任务为空），同时暴露 4 个问题，均已修复：

1. **待会签状态下审批动作未按状态隐藏**：boss 仍见批准/驳回/重算/转交。修复：Approval.tsx 增加 `awaitingReview` 状态门控；ApprovalActionBar 新增 `rejectOnly` 能力位——会签人只见"会签+拒签"，主审动作仅待审状态显示。
2. **登录页吞错误信息**：所有失败硬编码为"请检查账号密码"，把限流 429 的真实原因掩盖，误导用户以为密码错误。修复：透传错误信封 message，api 模式失败 ≥3 次提示限流规则。
3. **mock 时代的图形验证码/锁定 UI 泄漏到 api 模式**：修复为 `!apiMode` 门控。
4. **【工业级缺陷】限流与审计 IP 被 nginx 反代掩盖**：uvicorn 未启用 --proxy-headers，后端看到的 client IP 恒为 nginx 容器 IP → 全体用户共享同一 5/min 登录限流桶、审计日志 IP 失真（用户实测正是因此被集体限流并收到误导报错）。修复：compose api 命令加 `--proxy-headers --forwarded-allow-ips "*"`（api 仅 expose 于内网，唯一入口是 nginx，可信）。

## 实测通过记录（2026-07-12，Phase 4 关闭）

六项验证全部通过：①boss 批准后"待会签"黄条+审批链更新；②任务列表为空（批准不直接生成任务）；③finance 视角仅"会签/驳回"按钮（修复生效），会签后审批通过；④5 条任务生成，截止 T+1、负责人为真实用户；⑤PNG 导入返回 manual_required + 原文件留 staging + "仍要导入"显式闸门；⑥停 postgres 刷新出"依赖服务不可用"黄条（503 新路径）。

遗留化妆品级小项（转 backlog）：任务负责人列显示用户 ID 而非姓名；会签完成后审批链第 3 步图标未打勾。

**Phase 4 正式关闭。**
