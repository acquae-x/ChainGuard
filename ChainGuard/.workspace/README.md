# 协作工作区说明

本目录用于「架构/测试验收（Claude）」与「代码生成（Codex）」的分工协作。

## 分工

- **Claude（本角色）**：架构设计、任务拆解、验收标准（测试用例/DoD）、代码评审、回归验证。
- **Codex**：根据 `tasks/` 中的指令文件实现具体代码。

## 目录结构

```
.workspace/
  README.md              本说明
  architecture/           架构设计文档、技术方案、ADR（Architecture Decision Record）
  tasks/                  下发给 Codex 的可执行任务指令（按序号命名，如 TASK-001-xxx.md）
  reviews/                Claude 对已完成任务的验收报告
  acceptance/             测试用例与验收标准（pytest 用例、检查清单）
```

## 工作流程

1. 用户提出需求 → Claude 在 `architecture/` 中输出/更新设计方案。
2. Claude 将设计拆解为可执行任务，写入 `tasks/TASK-XXX-<slug>.md`，包含：
   - 背景与目标
   - 涉及文件/模块
   - 具体实现要求（接口、数据结构、边界条件）
   - 验收标准（对应 `acceptance/` 中的测试或检查项）
   - 明确的完成定义（DoD）
3. Codex 按任务文件实现代码。
4. Claude 运行/审查测试，产出 `reviews/TASK-XXX-review.md`（通过/不通过 + 问题列表）。
5. 不通过则在原任务文件追加「修复要求」章节，退回 Codex。

## 任务文件命名规则

`TASK-<三位序号>-<英文短横线slug>.md`，例如 `TASK-001-inventory-risk-index.md`。

## 状态标记

任务文件顶部使用 YAML front matter 标记状态：

```yaml
status: draft | ready_for_codex | in_progress | review | done | blocked
```
