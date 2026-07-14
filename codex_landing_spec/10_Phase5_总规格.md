# Phase 5 总规格（2026-07-12 定稿，唯一权威来源）

整合 05 清单（5A/5B 拆分与风险红线）、08 对照（函数级批次归属）、09 融入设计（页面形态）。冲突时以本文为准；页面形态细节以 09 为准。

## 总原则

- 5A 是确定性工程，立即可发；5B 有研发性风险，**先完成规格前置产出再动工**。
- 红线（继承 05 复审）：不改 orchestrator 决策流水线内部；run_demo 保留为演示/测试路径；引擎 460+ 测试断言不许改弱；所有新表带 tenant_id 且仓储层强制过滤。

---

## Phase 5A 管道批

### 5A-1 完整推演（E-1，核心，工作量最大）

后端：决策作业持久化完整 DecisionResult 关键段（conflict/rebuttal/arbitration/debate_result/constraint_analysis/explanation/manual_confirmation_points/audit_entry/sensitivity/game_analysis → 新表 decision_details，随 job 写入，tenant 隔离）；新增 `GET /api/v1/incidents/{id}/decision-detail`。敏感性与 Pareto 数据引擎已有能力（sensitivity.py/game_analysis.py），作业执行时一并计算存入。
前端（形态见 09 §1–2）：方案生成页与审批页共用"完整推演"抽屉，**五段式**：评分与冲突 → 辩论过程 → 仲裁结论与推导 → 约束分析与推荐调整 → **敏感性分析（库存水平 vs 风险指数曲线，Streamlit Step 敏感性迁入，ECharts 折线）**；约束段内加 **Pareto 前沿散点图**（27 策略组合，Streamlit Step 8 附属迁入，可折叠默认收起）；方案卡冲突横幅；AI 解释三层化；审批页"执行确认点"核对清单（批准弹窗附"已核对"勾选，不阻塞）；"查看决策审计记录"抽屉；"导出决策报告"（**JSON + PDF 双格式**，PDF 用 reportlab——已在依赖中，模板参照演示数据生成器的单据风格：摘要+方案对比+推演要点+确认点+审批链）。
Alembic 迁移一份。

### 5A-2 通知规则（D3）

`notification_rules` 表（event_type → 接收方解析策略，规则即数据），按 05 清单 D 组矩阵内置固定规则（含会签请求/完成/拒签/超时放行、任务分派/催办、导入完成/失败、高风险预警）；同对象同事件 5 分钟聚合；铃铛前端扩展（09 §7）。任务逾期通知依赖逾期扫描：在 A5 已有调度器上加一个逾期扫描作业。渠道：站内信 + 既有 webhook。

### 5A-3 引擎审计入库（F5 长期）

orchestrator 产出的 audit_entry 经作业写入 `decision_audits` 表（tenant 隔离），与 5A-1 的 decision_details 同迁移；data/*.jsonl 写入保留（演示路径兼容），文档标注 DB 为权威源。备份天然覆盖（pg_dump）。

### 5A-4 refresh token 吊销（D2）

`revoked_tokens` 表存 jti + 过期时间；登出、改密时写入；decode 时校验；调度器定期清理过期条目。JWT 载荷补 jti。**先于 5A-5 实现（改密依赖它）。**

### 5A-5 账户小项（08 F01–F03）

个人设置页落地：修改密码（校验旧密码，成功后吊销该用户全部 refresh jti 强制重登）；系统设置→用户管理加"重置密码"（一次性临时密码 + 首登强制改密，users 表加 must_change_password 列）；登录页"忘记密码"死链改"请联系企业管理员重置"提示。

### 5A-6 导入体验小项（08 D02/D03）

预检报告结构化渲染：结论徽标三态（通过/建议评估 PostgreSQL/空间不足已阻止）+ 磁盘余量与预计增量 + 消息列表，⛔ 时"仍要导入"禁用；第 4 步预览表格改为服务端归一化结果（表名+行数+前 N 行）。纯前端 + 预检响应字段整理，无迁移。

### 5A-7 告警最小闭环（F6）

compose 可选 profile：prometheus + grafana + 预置面板；三条告警规则：决策作业失败率 >10%（15 分钟窗）、作业积压 >10、磁盘使用 >80%。若工作量超预期可降级为"文档给抓取配置 + 告警规则文件"，但必须交付可导入的规则文件。

### 5A 可选并行项

价值仪表盘（C04/E-4）：报表看板高管页**四块**——本次事件净收益/累计避免损失时间线/决策提速对比/**自动化率卡**（C06 缩编为一张卡，引擎 automation_stats 现成，不做独立面板）。数据暂可基于 decision_details 与审批时间戳计算，不依赖 5B。

### 5A 依赖顺序与验收

顺序：5A-4 → 5A-5；5A-1 → 5A-2（通知里的"方案生成完成"链接到详情）；其余并行。
技术验收：新迁移 up/down 实测；`pytest tests/ -q` 全绿（新功能全部带测试）；`DATA_MODE=api npm run build` 零 error；CI 绿。
用户验收（09 汇总节的 6 项可感知变化）：①方案页看懂"为什么推荐"；②审批页确认点+导出；③预检红绿灯；④预览即所得；⑤改密/重置密码可用；⑥铃铛通知覆盖任务/会签/导入。

---

## Phase 5B 真实化批

### 前置产出（规格阶段，动工前必须完成，由评审方主笔）

1. **引擎 context schema 正式化**：从 data/*.json 反推 inventory/supplier/logistics/finance/orders 各段字段、类型、单位、必填性，成文档 + pydantic 模型。
2. **实体表设计**：materials/suppliers/inventory/orders/customers 五张结构化表 + 与 data_records 的迁移方案（存量 JSON 数据迁移脚本）；**复用 erp_sync.py 的表→实体映射，禁止重写**。
3. **租户隔离设计**：租户级阈值/权重存放（建议 DB 表 tenant_configs）；经验卡入库带 tenant_id；TF-IDF 检索索引按租户构建。
4. **基准压测**：用 benchmarks/ 工具以 1 万/5 万行库存量级压决策链路，据此定作业超时与容量口径。

### 实施顺序

C2（实体表 + 导入落表 + 签名重复闸门 D04）→ C1（context builder + 新增 run_tenant_scenario 入口 + 阈值/评分按真实数据校准，run_demo 不动）→ **校准治理面板（Streamlit Step 9 后半 + 漂移体检迁入）**：管理端展示"数据驱动 vs 专家默认"阈值/权重对比、样本量与置信说明、人工确认放行（复用 parameter_calibration/model_registry/drift_monitor/run_recalibration 现成引擎能力），漂移超限时经 D3 通知 admin——校准不能是黑箱，这是租户敢用数据驱动阈值的前提 → E-3（经验闭环：作业写经验卡入库、方案卡历史经验角标、检索租户隔离）→ C3（空租户引导：向导接真实导入，可选注入演示数据集）→ **ERP 最小集成（E01/E02 提前）**：系统设置→集成页点亮最小集——连接配置（base URL/凭证）+ 连通测试（/health、catalog 预览）+ 手动同步按钮（复用 erp_sync.py 落实体表）+ 同步历史列表；表→实体**映射先以 yaml/json 配置文件交付**（实施方提供标准模板与说明）→ 收尾批（顺序不限）：A03 实时风险解释、A04 影响范围完整版、C02/C03 节点健康视图、**ERP 字段映射编辑 UI**（读写上述配置文件，工期紧张可裁，裁掉不影响主线）、**账户完善**——忘记密码自助（依赖邮件/短信通道，通道未接则维持"管理员重置"兜底并明示）、企业邀请码（生成/失效/角色预设，替换 mock 加入页）、SSO（复用 rbac.py 既有 OIDC 骨架）、账号级锁定（连续失败锁定 15 分钟，补足 IP 限流之外的账号维度防爆破）。

### 5B 验收（端到端场景）

**第 0 步（2026-07-12 确认）**：既有 11 万条企业演示数据（demo_assets/enterprise）经 erp_sync 或 CSV 导入管线完整灌入演示租户，前端各资料页、风险、决策链路可见可用——该数据集同时作为压测基线（详见 11 号文档④节）。然后：新注册企业 → 向导导入自己的 csv（或演示集，或经 ERP 集成页连 Mock ERP 同步）→ 库存风险由真实数据算出并可解释 → 管理端可见"数据驱动 vs 专家默认"校准对比并人工放行 → 创建事件 → 生成方案（引擎吃真实上下文，成本/交期来自真实数据）→ 完整推演五段可读（含敏感性曲线）→ 审批会签 → 任务 → 复盘经验卡入库 → 第二次类似事件时方案卡出现"引用历史经验"角标。全程另一租户看不到任何本租户数据。

---

## Phase 6：已撤销（2026-07-12 产品决策）

原 Phase 6 桶全部归并或裁决：敏感性/Pareto→5A-1；PDF 报告→5A-1 导出；自动化面板→缩编为价值仪表盘一张卡（5A 可选）；参数校准对比/漂移体检→5B 校准治理面板；ERP 最小集成→5B 主线；ERP 字段映射 UI + 登录完善四项→5B 收尾批（映射 UI 可裁）；**6 模型对比评测（B02）砍掉**——保留在 Streamlit 演示版供答辩，不迁移 Web。Phase 5 交付完成即为本轮落地改造终点。

## 与现有前端的结合审计（2026-07-12，逐项对位 config/routes.ts 与组件库）

### 完美对位（现成路由/页面/组件直接承接，共 17 项）

| 并入项 | 前端落点（已存在） |
|---|---|
| 完整推演五段抽屉 + 冲突横幅 + AI 解释三层 | Decision/Generate + Decision/Approval（"查看完整推演"链接已在页面上）；新增 DecisionTrace 组件，无路由变更 |
| 确认点清单 + 批准勾选 | Approval.tsx 决策摘要区 + ApprovalActionBar 批准弹窗扩展 |
| 决策审计抽屉、导出 JSON/PDF | Approval/推演抽屉内按钮，后端出文件流 |
| 通知规则铃铛扩展 | NotificationBell 组件现成；通知 target 所需路由（/decision/approval/:id、/task/mine 等）全部存在 |
| 容量预检红绿灯 + 归一化预览 + 签名重复警告 | ImportWizard 第 4 步 preflightReport 区域现成，改渲染即可 |
| 价值仪表盘四卡（含自动化率） | /report/executive 经营看板页（P2 骨架）+ KpiCard 组件现成 |
| **校准治理面板** | **/settings/thresholds「风险阈值」页已预留**——对比/放行/漂移体检的天然家 |
| **ERP 最小集成 + 映射 UI** | **/settings/integration「集成」页已预留**（灰色占位点亮） |
| 经验闭环展示 | /case/experience 经验卡片页 + Generate 方案卡角标 |
| C2 实体表前端 | /data 五个资料页现成，换数据源不换结构 |
| C3 引导 | /onboarding + /settings/onboarding 重入路由现成 |
| 忘记密码提示/自助 | **/user/reset 路由已预留** |
| 企业邀请码 | /user/join 页现成（mock 换真实） |
| SSO 入口 | 登录页链接已有 + 后端 rbac.py OIDC 骨架 |
| 账号锁定提示 | 登录页 Phase 4 已有限流提示条，复用形态 |
| 管理员重置密码 | Settings/Users 行操作扩展 |
| A03/A04/C02 风险解释/影响范围/节点卡 | Risk 列表、Incident/Detail 四表、Dashboard 卡片区扩展 |

### 角色合理性审查补充（2026-07-12，按九角色走查后新增 3 项硬要求 + 2 项预期管理）

- **【硬性，安全级】decision-detail 接口按角色字段脱敏**：完整推演含成本/资金全量数据，`GET /incidents/{id}/decision-detail` 必须复用 mask_payload 同款脱敏（buyer 等无 field:cost:view 角色看到 \*\*\*），与导出脱敏同批实现、同批测试。导出权限口径：具备 decision:view（含域视图）即可导出——安全由脱敏保证而非拦导出。
- **【硬性】超时放行的追认动作闭环（并入 5A-1/A5）**：超时自动放行后，finance 打开审批单应有"补充会签意见"入口——追认通过 / 追认异议（必填理由，通知 boss 与提交人，留痕不回滚任务）。没有这个入口，"通知财务追认"无法落地。
- **【硬性】C3 引导必须含"邀请成员/创建业务账号"步骤**：注册人默认为 admin（纯配置角色，无决策权限），引导若不带建号步骤，新租户首屏即"什么都干不了的空系统"。保留 01 规格向导中的邀请成员环节。
- **【预期管理】boss 移动可达性**：真移动端不在本期范围，但 webhook 通知必须携带审批直达链接，且审批页/推演抽屉需通过窄屏（≥375px）响应式自查——应急审批大概率发生在手机浏览器。
- **【预期管理】通知聚合默认开启**：scm_lead 是通知矩阵最大接收者，5 分钟聚合为默认行为而非可选项。

### 缝隙（5 处，实现时按此处理）

1. **个人设置页无路由**（F01）：新增 `/user/profile`（hideInMenu，布局内），承载改密+基本信息，顶栏"个人设置"指向它。
2. **首登强制改密守卫**（F02）：login/me 返回 `mustChangePassword` 时，onPageChange 除 /user/profile 外一律重定向至该页，改密成功后放行。
3. **【安全级】导出物脱敏**：决策报告 JSON/PDF 含成本/利润字段，必须经与 API 同款的字段权限脱敏（无 field:cost:view 的角色导出的 PDF 中成本为 \*\*\*）——否则导出功能变成绕过字段权限的后门。后端生成时按请求者角色走 mask 逻辑，加测试锁定。
4. **铃铛数据源统一**（D3 前置小改）：NotificationBell 当前 api 模式下由 risks/approvals/tasks 三接口前端拼装，D3 落地后统一改为消费 /notifications 单一真实源，避免双源不一致。
5. **Dashboard 角色分卡**（C02/C03）：工作台为全角色共用单页，节点健康卡按角色显示（一线+scm_lead 可见），用现有 access 权限码判断，不新增权限码；校准放行权限复用 `canApprovalConfig`（settings:approval/settings:manage），全程不新增权限码。

## 交付物要求（沿用惯例）

每批完成：实际执行的 pytest/build 原始输出、变更文件清单、逐项验收证据（5A 按 6 项用户可感知变化截图）、已知限制。禁止声称未实际执行的验证。5A 交付材料 → `phase5a_交付材料.md`；5B 动工须待前置产出评审通过。
