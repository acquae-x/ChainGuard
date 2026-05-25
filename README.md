# ChainGuard 供应链应急响应系统

## 项目简介

ChainGuard 是一个用于比赛初赛答辩的 Streamlit 单机 MVP，面向供应链中断场景，展示从库存风险监控、多源态势感知、多 Agent 协同决策、辩论仲裁，到经验卡片自学习的完整闭环。

当前固定演示案例为：台风导致宁波港暂停作业，A供应商发货延误72小时，核心控制芯片库存只能支撑36小时，关键客户订单将在48小时后交付。

## 核心创新

1. 库存监控前置触发  
   系统不是等订单延期后再处理，而是在库存可支撑小时数、安全库存缺口率、在途延误和外部风险分超过阈值时提前触发应急决策。

2. 多 Agent 协同决策  
   采购 Agent、物流 Agent、财务 Agent 从不同目标出发提出方案，分别关注备用供应商、运输时效、成本与利润。

3. 辩论仲裁机制  
   当方案之间出现“全量空运 vs 成本控制”等冲突时，系统触发辩论过程，再由仲裁器输出最终折中策略。

4. 经验卡片自学习  
   每次应急决策可沉淀为经验卡片，记录触发条件、失败原因、改进策略和推荐模式，后续可用于相似场景检索。

5. 参数配置化与未来校准  
   风险权重、预警阈值和评分权重均在 YAML 中配置。当前为专家经验参数，未来可用企业 ERP/WMS/TMS 历史数据校准。

## 技术架构

```text
Streamlit 页面
  |
  |-- data_loader.py              读取模拟库存、订单、供应商、物流、事件数据
  |-- config_loader.py            读取风险权重和阈值配置
  |-- inventory_monitor.py        计算库存风险指数和预警
  |-- agents.py                   生成采购/物流/财务 Agent 决策提案
  |-- scoring.py                  计算方案总分并排序
  |-- conflict_detector.py        检测评分差异、关键词和目标冲突
  |-- debate.py                   生成 Agent 反驳与折中建议
  |-- arbitrator.py               输出最终仲裁方案
  |-- learning.py                 生成、保存、读取经验卡片
  |-- vector_store.py             默认关键词检索，预留 Chroma
  |-- llm_client.py               默认 Mock LLM，预留 Qwen
  |-- parameter_calibration.py    预留企业历史数据拟合接口
```

## 项目目录结构

```text
ChainGuard/
  app.py
  requirements.txt
  requirements-dev.txt
  README.md
  config/
    risk_weights.yaml
    thresholds.yaml
  data/
    inventory.json
    orders.json
    suppliers.json
    transport_options.json
    events.json
    sample_enterprise_data_schema.md
  docs/
    demo_script.md
  src/
    agents.py
    arbitrator.py
    config_loader.py
    conflict_detector.py
    data_loader.py
    debate.py
    inventory_monitor.py
    learning.py
    llm_client.py
    parameter_calibration.py
    scoring.py
    vector_store.py
  tests/
    test_*.py
```

## 安装方式

建议在项目目录下执行：

```powershell
cd /d D:\github_projects\Chainguard\ChainGuard
pip install -r requirements.txt
```

如需运行测试：

```powershell
pip install -r requirements-dev.txt
```

## 运行方式

```powershell
cd /d D:\github_projects\Chainguard\ChainGuard
streamlit run app.py
```

如果 `streamlit` 命令不可用，可以使用：

```powershell
python -m streamlit run app.py
```

如果默认端口 `8501` 被占用，可以换端口：

```powershell
python -m streamlit run app.py --server.port 8502
```

## 演示案例说明

固定场景：

- 台风导致宁波港暂停作业。
- A供应商发货延误72小时。
- 核心控制芯片 `M-AX100` 当前库存为3600，小时消耗为100，因此库存只能支撑36小时。
- 安全库存为6200，存在明显缺口。
- A类关键客户订单48小时后交付，需求量为5000。
- 系统最终仲裁方案为：关键订单空运 + 备用供应商补货 + 非关键订单延期沟通。

页面按 Step 1 到 Step 7 展示完整流程：

1. 库存监控与风险预警
2. 态势事件卡片
3. 多 Agent 决策提案
4. 方案评分与冲突检测
5. 辩论过程
6. 仲裁决策
7. 自学习经验卡片

## 当前版本限制

- 使用模拟数据，不代表真实企业库存、订单、供应商或物流状态。
- 使用专家经验参数，不是真实历史数据拟合结果。
- 未接入真实 ERP/WMS/TMS。
- 未接入真实 LLM API。
- 当前 Qwen、Chroma、企业数据校准均为预留接口或可选增强项。
- 当前是 Streamlit 单机 MVP，不包含生产级权限、审计、部署和多用户能力。

## 未来扩展

1. 接入企业数据  
   导入 ERP/WMS/TMS 历史库存、订单、供应商、在途物流和应急结果数据。

2. 参数拟合  
   基于历史缺料、延误、停工、投诉和成本结果，校准库存风险权重、预警阈值和方案评分模型。

3. Qwen API  
   通过 `llm_client.py` 接入 Qwen，用于生成更自然的 Agent 推理、辩论反驳和仲裁解释。

4. Chroma  
   通过 `vector_store.py` 将经验卡片接入 Chroma，实现语义检索和案例复用。

5. FastAPI/Vue  
   当前初赛 MVP 不使用 FastAPI/Vue。未来正式产品化时，可将核心算法封装为 FastAPI 服务，并使用 Vue 构建企业级前端。

## 测试

```powershell
python -m pytest tests
```

当前测试覆盖配置读取、库存监控、方案评分、冲突检测、辩论、仲裁、经验卡片、LLM 抽象和向量检索接口。
