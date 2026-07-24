# ChainGuard 供应链应急响应系统

## 项目简介

ChainGuard 是供应链中断场景下的应急决策系统，产品形态是 FastAPI 后端 + React（Umi + Ant Design Pro）多租户前端。完整的多 Agent 博弈、约束仲裁、自学习经验检索和审计闭环由本目录 `src/` 下的决策内核实现，Web 层通过 `src/webapi` 暴露为 `/api/v1`。系统面向制造企业的供应链、采购、物流、财务和客户交付团队，用于在断供、延期或需求冲击真正扩大前，给出可解释、可审计、可人工确认的应急方案。

> 本 README 说明的是**决策内核（`src/`）**：它无 Web/数据库依赖，可独立测试与复用。完整产品的启动见仓库根目录 `start-demo.ps1` / `start-demo.sh`。

当前版本支持并演示以下 5 类中断事件：

- `port_shutdown`：港口停运或台风导致运输节点暂停
- `supplier_shutdown`：供应商停产、断电或产能不可用
- `route_blockage`：运输路线阻断、通关延迟或节点中断
- `demand_surge`：客户需求突增导致库存和产能承压
- `quality_recall`：质量召回、批次隔离和替代供应切换

## 核心能力

1. **库存监控前置触发**  
   基于库存可支撑小时数、安全库存缺口率、关键订单覆盖率、在途延误和外部风险分，提前计算库存风险指数并触发应急流程。

2. **多 Agent 策略生成**  
   采购、物流、财务 Agent 从供应可得性、运输时效、成本利润和客户优先级出发，生成可评分的候选方案。

3. **博弈收益与约束仲裁**  
   PayoffModel 构造 3 个参与者 × 3 个策略选项的效用空间，ConstraintSolver 枚举 27 个组合，在约束内选择系统效用更高的方案。

4. **证据驱动辩论与解释**  
   DebateEngine 和 `generate_rebuttal` 记录冲突、证据和折中建议；DecisionExplainer 在无 LLM 时使用模板解释，在可选 Qwen/Ollama 可用时增强表达。

5. **经验检索与自学习闭环**  
   ExperienceFeedback 使用 TF-IDF/Embedding 检索历史经验卡片，将 `risk_hints` 和 `confidence_adjustment` 注入方案字段，便于说明历史经验如何进入决策链。

6. **审计与人工确认**  
   AuditLog 以 JSONL 形式记录关键决策结果，并输出 `human_approval_required`，避免系统直接替代管理责任。

## 技术架构

```text
ScenarioLoader (SQLite) → DecisionOrchestrator
  ├── PayoffModel (3 Agents × 3 Options)
  ├── ConstraintSolver (27 combos)
  ├── DebateEngine (evidence-driven)
  ├── arbitrate
  ├── ExperienceFeedback (TF-IDF / Embedding)
  ├── DecisionExplainer (Qwen / template)
  └── AuditLog (JSONL, human_approval)
HistoryPipeline → TrainingDataset → ModelRegistry
```

## 项目目录结构

```text
ChainGuard/
  requirements.txt
  requirements-dev.txt
  README.md
  benchmarks/
    test_history_scale.py
  config/
    risk_weights.yaml
    thresholds.yaml
  data/
    inventory.json
    orders.json
    suppliers.json
    transport_options.json
    events.json
    experience_cards.json
    retrieval_eval.json
    sample_enterprise_data_schema.md
  demo_assets/
    enterprise/
      database/chainguard_enterprise_demo.db
      csv/
      json/
    erp_api/
      openapi.yaml
  docs/
    demo_script.md
    defense_qa.md
    enterprise_demo_data.md
    coordination/
  scripts/
    build_history_features.py
    generate_enterprise_demo_data.py
    mock_erp_server.py
  src/
    agents.py
    arbitrator.py
    audit.py
    benchmark.py
    constraint_solver.py
    debate.py
    explainer.py
    feedback.py
    game_model.py
    history_pipeline.py
    model_registry.py
    orchestrator.py
    scenario_loader.py
    sensitivity.py
    training_dataset.py
    vector_store.py
  tests/
    test_*.py
```

> **想直接看完整产品（FastAPI + React 前端）？** 回到仓库根目录执行
> `.\start-demo.ps1`（Windows）或 `./start-demo.sh`（Linux/macOS），
> 一条命令完成依赖、迁移、播种、构建与启动，单进程单端口 8000。

## 安装方式

在本目录（仓库的 `ChainGuard/` 子目录）下执行：

```powershell
pip install -r requirements.txt
```

如需运行测试：

```powershell
pip install -r requirements-dev.txt
```

## 运行方式

完整产品（FastAPI + React）从仓库根目录一键启动：

```powershell
.\start-demo.ps1
```

单独运行 FastAPI 决策 API（需先配置 `JWT_SECRET` 等环境变量，见 `.env.example`）：

```powershell
python -m uvicorn src.api:app --port 8000
```

决策内核本身无 Web 依赖，可作为库直接调用或跑测试单独验证（见文末「测试」）。

## 决策链步骤

以下是决策内核产出的完整链条，现由 React 前端的 `DecisionTrace` 组件呈现（早期曾由已下线的 Streamlit 演示页逐步展示）：

| 步骤 | 内容 |
| --- | --- |
| Step 1 | 库存风险指数（4 维分解 + 预警等级） |
| Step 2 | 中断事件卡片（event_type, severity） |
| Step 3 | 三 Agent 策略提案 + 各维度评分 |
| Step 4 | 方案评分排序 + 冲突检测 |
| Step 5 | 辩论文本（generate_rebuttal 输出） |
| Step 6 | 仲裁结论（final_decision_title, execution_plan） |
| Step 7 | 当次生成的经验卡片 |
| Step 8 | 约束求解结果 + DebateEngine 收敛 |
| Step 9 | 历史经验检索结果（risk_hints, confidence_adjustment） |
| Step 10 | Qwen/模板解释（llm_used=True/False） |
| Step 11 | 审计 JSON（decision_id, human_approval_required） |
| 敏感性 | current_stock → risk_index 变化曲线 |

## 当前能力清单

### 已真实实现（离线可运行）

- PayoffModel 效用计算（3 参与者 × 3 策略 = 27 组合）
- ConstraintSolver 约束枚举与社会福利最大化
- 证据驱动辩论（DebateEngine + generate_rebuttal）
- TF-IDF 经验检索（ExperienceFeedback）
- AuditLog 审计链（JSONL，含 human_approval_required）
- ModelRegistry + PriorClassifier 频率先验基线
- 企业场景切换（ScenarioLoader，SQLite，11 万条合成数据）
- current_stock 敏感性分析，只调用库存风险计算，不重跑完整 orchestrator

### 可选增强（有离线降级）

- sentence-transformers 语义检索（降级到 TF-IDF）
- Qwen（Ollama）LLM 解释（降级到模板）
- Chroma 向量数据库（降级到内存 TF-IDF）

## 演示数据说明

默认固定演示场景仍包含台风导致宁波港暂停作业、供应商发货延误、核心控制芯片库存不足和关键客户订单交付压力。复赛版本同时提供企业级合成数据资产：

- SQLite 场景数据库：`demo_assets/enterprise/database/chainguard_enterprise_demo.db`
- 企业 CSV 明细：库存、订单、供应商、物流、质量、历史决策等
- OpenAPI 示例：`demo_assets/erp_api/openapi.yaml`
- 历史经验与检索评测数据：`data/experience_cards.json`、`data/retrieval_eval.json`

这些数据均用于离线演示和答辩，不依赖外部 ERP 服务即可启动主流程。

## 当前限制

- Qwen/Ollama、sentence-transformers、Chroma 都是可选增强；不可用时会降级到模板或 TF-IDF。
- Agent 策略、效用、约束和经验检索均可离线运行，但真实企业上线仍需数据脱敏、权限、审批流和部署方案。
- 经验卡片语料量会影响 `experience_hints` 是否丰富；批量历史决策转经验卡片由后续改进任务继续增强。

## 测试

```powershell
python -m pytest tests -q           # 决策内核 + Web 层全量
python -m pytest benchmarks -v -s   # scale benchmark
```

当前测试覆盖配置读取、库存监控、场景加载、Agent 策略、收益模型、约束求解、辩论、仲裁、经验检索、审计、解释器、敏感性分析、历史管道和训练数据基线。
