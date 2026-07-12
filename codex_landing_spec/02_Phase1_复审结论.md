# Phase 1 复审结论（通过）

复审时间：2026-07-11。复审方式：直接读取磁盘文件逐项核对修复点 + 审阅 `phase1_交付材料.md` 中的 pytest/curl/迁移实录。

## 重要更正

上一轮评审报告（01）中"多个文件被截断"的一票否决项，经查是**评审方沙盒文件同步的读取伪影**，用户磁盘上的文件一直是完整的。该项误判撤回，向 Codex 更正。上一轮报告中的设计问题（死锁、假迁移等）依据的代码内容真实，仍然成立且本轮已验证修复。

## 修复项逐条核验结果

| 评审项 | 结果 |
|---|---|
| 线程池自死锁 | ✅ 调度池/决策池分离（jobs.py，附解释注释），新增 4 作业并发测试 |
| 假 Alembic 迁移 | ✅ 显式 op.create_table/create_index（15 表），api.py 移除 create_all，且有测试断言防回归；up/down 均实测 |
| 决策作业与事件无关 | ✅ 按要求在 jobs.py/proposal_mapper.py 注释明示为 MVP 占位，并列入已知限制 |
| 事件硬编码 loss=860000 | ✅ 改为可传参，默认 manual/0/0；860000 仅存在于 seed 演示数据（应在位置） |
| 转办不校验接收人 | ✅ 非本租户/非 active 用户返回 422 CG-2404，有测试 |
| serialize 隐藏 account | ✅ 白名单机制，管理员用户列表返回 account，密码哈希仍禁止，有测试 |
| 上传无限制 | ✅ 仅 csv/xlsx + MAX_IMPORT_BYTES（默认 20MB），超限 413 CG-2604，有测试 |
| requirements.txt | ✅ pdfplumber/psutil 恢复，psycopg[binary] 补全并注释 |
| QwenLLMClient | ✅ 真实 DashScope 调用：10s 超时、3 次退避重试、失败降级 Mock 并打日志、QWEN_REMOTE_ENABLED 显式开关 |
| 测试证据 | ✅ 484 passed 完整原始输出 + 8 步 curl 全链路（登录→事件→异步方案→审批→任务→审计）+ 迁移 up/down 实录 |

## 遗留事项（不阻塞，带入后续阶段）

1. 决策作业接入真实事件上下文（Phase 1 已声明为占位，建议 Phase 2 或独立任务解决）。
2. PostgreSQL 尚未在真实服务上跑迁移与全量测试（Phase 3 部署时必须补）。
3. `data/audit_log.jsonl` 的既有 275 行增量属用户工作区改动，未回滚，需用户自行确认是否提交。

## 结论

Phase 1 验收通过，可以向 Codex 下达 Phase 2（前端接入真实后端，见总指令）。下达时附一句："Phase 1 已通过复审（见 codex_landing_spec/02_Phase1_复审结论.md），Phase 2 开始前先读总指令 Phase 2 节和遗留事项。"
