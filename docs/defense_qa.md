# 企业历史数据答辩问答

## 1. 企业历史数据集很大，系统怎么处理？

不会一次性读全量明细。`HistoryPipeline.ingest_incremental()` 按 `created_at` 水位分批读取 SQLite，清洗、去重、隔离坏记录，再生成可版本化训练快照。

## 2. 怎么防止未来信息泄漏到训练集？

`build_training_snapshot()` 只读取 `cutoff_time` 前的数据；`split_by_time()` 按事件时间切分训练、验证、测试集，不做随机跨期拆分。

## 3. 大模型是怎么“训练”的？要全量数据一次性入库吗？

不是把明细塞进 LLM。历史明细先转成脱敏特征、标签和经验摘要；模型或参数离线小批量校准，在线决策只读取已发布版本。

## 4. 如果新版本效果变差，怎么办？

`ModelRegistry.should_replace_stable()` 只有在新指标严格优于当前稳定版时才允许替换；否则保留上一稳定版本，并可用 `rollback()` 回退。

## 5. 在线决策是否依赖训练完成？

不依赖。训练、快照和注册是离线流程；在线链路只读取已发布参数、特征和索引。训练失败时继续使用上一稳定版本。

## 6. 脱敏和数据安全如何保证？

T13 原型只处理结构化字段和脱敏摘要，不把原始企业明细发送给 Qwen 或外部模型；坏记录进入隔离清单，导入与版本记录可审计。

以上答辩口径对应 `src/history_pipeline.py`、`src/training_dataset.py`、`src/model_registry.py` 的实际实现，所有行为可通过单元测试验证。

## 7. 仲裁是怎么得出最终方案的？

仲裁分四步，每步结果在 Step 6「仲裁决策」的「仲裁推导过程」展开栏中实时可见：

1. **评分排名**：`attach_total_scores` 对三个 Agent 提案按 5 维权重（供应能力、
   时效、成本控制、风险降低、客户满足）加权计算 `total_score`，排出最高分提案。

2. **冲突检测**：`detect_conflict` 检查最高最低分差距是否超过阈值（默认 15 分）；
   冲突成立则 `conflict_penalty = 2`，否则为 0。

3. **辩论反驳**：`generate_rebuttal` 对最低分提案从成本分、时效分等结构化字段
   出发提出改进建议；反驳成功则 `rebuttal_bonus = 4`，否则为 0。

4. **分数推导与动态输出**：
   `final_score = best_score + rebuttal_bonus - conflict_penalty`
   `final_decision_title` 由 `event_type` 子串匹配生成行动短语，
   拼接 `material_name` 组成标题；`execution_plan` 每步从 `context` 实时取值。

UI 验证：点开 Step 6 底部的「仲裁推导过程」，可看到每步的具体数字和加减分明细。

## 8. 博弈的"均衡"是什么？

系统采用**约束优化下的社会福利最大化**：`ConstraintSolver` 枚举 3³=27 个策略组合，
在满足供给覆盖率≥30%、交期≤72h、成本倍数≤5 的可行解中，选取三个 Agent
系统效用之和（`Σ system_utility_i`）最高的组合（`optimal_system_utility`）。

对比基准是"各 Agent 独立最优"——每个 Agent 各自选择最大化 own_utility 的策略
（`individual_system_utility`）。社会最优通常高于自私选择，差值（协调收益）
可在 Step 8「约束驾驶舱」页面的「博弈效用对比」直接看到。

与纳什均衡的区别：本系统中 `own_utility` 只依赖 Agent 自身策略，不依赖他人策略，
不存在战略互动，因此纳什均衡不是本系统对应的解概念；`ConstraintSolver` 充当
社会计划者，直接求解使全体受益最大的约束下最优解。

## 9. 自学习具体改变了哪个决策变量？

已落实两层，Step 9 页面可当场验证：

**第一层（经验检索，I03 已实现）**：`ExperienceFeedback` 检索历史经验卡片，
将检索结果注入每个 Agent 提案两个字段：
- `proposals[i]["experience_hints"]`（`list[str]`）：相关历史案例的风险提示
- `proposals[i]["experience_confidence"]`（`float`，0~0.3）：检索到 1 条相关案例
  加 0.1，最多 3 条上限 0.3

**第二层（参数校准，I09 已实现）**：用 `historical_decisions` 表中的
真实结果字段，通过皮尔逊相关系数反向校准库存风险各维度权重。
以 600 条历史数据为例：

| 权重维度 | 专家默认值 | 数据驱动校准值 | 变化 |
|---|---|---|---|
| shortage_urgency | 0.35 | 0.235 | ↓ |
| order_importance | 0.25 | 0.446 | ↑ |
| transit_delay | 0.20 | 0.141 | ↓ |
| external_event | 0.20 | 0.178 | ↓ |

UI 验证：Step 9 底部"参数校准对比"展开栏展示完整对比表，
数值来自实时调用 `calibrate_inventory_risk_weights(600条记录)`。
校准建议值需人工审批后更新至 `config/risk_weights.yaml`，不自动覆盖生产配置。
