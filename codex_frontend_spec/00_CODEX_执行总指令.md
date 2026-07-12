# 00 CODEX 执行总指令（先读本文件）

你要为 ChainGuard（供应链中断应急决策系统，后端已有：Python/FastAPI+Streamlit，见仓库 `ChainGuard/`）生成一个**真实企业级 SaaS 前端**，不是比赛 Demo。本目录 7 份文档是完整规格，冲突裁决顺序：00 > 07 > 02/03（权限）> 04（页面）> 01/05/06。

## 技术栈（强制）

- React 18 + TypeScript + Ant Design Pro（@ant-design/pro-components）+ UmiJS（Pro 脚手架默认）
- 图表 ECharts（echarts-for-react）；Excel 解析 SheetJS
- 状态：Pro 自带 useModel/initialState，局部用 zustand；禁止 redux
- **禁止使用 localStorage/sessionStorage 持久化业务数据**（登录 token 可用 cookie；向导进度走 mock 服务端保存）
- 全部文案中文；代码注释中文

## 工程位置与结构

在仓库根目录新建 `chainguard-web/`：

```
chainguard-web/
  config/           # umi 路由、proxy、theme
  mock/             # 全部 mock（user/tenant/risk/incident/decision/approval/task/import/report/audit/fields）
  src/
    access.ts       # 权限唯一出口（02 文档矩阵）
    theme.ts        # 色板唯一出口（05 文档）
    constants/status.ts
    components/     # 07 文档第 5 节的 10 个复用组件，先建
    services/       # 接口层，签名注释真实后端 endpoint（ChainGuard/src/api.py）
    pages/          # 按 03 文档路由
  docs/route-access-map.md  # 构建时生成
```

## 生成顺序（严格执行）

1. 脚手架 + theme.ts + constants + 10 个复用组件
2. services 接口签名 + mock 数据（含演示租户：9 角色账号，密码 Demo@1234；1 条完整 supplier_shutdown 演练数据链：风险→事件→3 方案→审批→任务→复盘）
3. 布局（顶部栏见 03 文档第 1 节）+ 路由 + access
4. P1 精细页（07 清单）：登录/注册/加入/向导/工作台/风险列表/事件详情/**方案生成页（最重要）**/审批/数据导入
5. P1 普通页：风险总览/规则/事件列表/方案列表/数据管理 5 表/用户/角色/审计/结果页
6. P2 骨架页：任务 3 页/案例库/报表 3 页/自定义字段/其余设置页
7. 不做 P3（06 文档）：只留 services 可替换结构 + 设置里"集成"灰色占位

## 硬性验收（完成后逐项自查并输出清单）

1. `npm run build` 零 error；`npm run dev` 可跑
2. 4 条核心流程可点击走通（07 文档第 4 节），全程无死链
3. 9 个演示账号登录后：菜单符合 03 第 4 节矩阵；按钮/字段符合 02 第 2 节矩阵（重点抽查：buyer 看成本=***、auditor 全只读、admin 无审批按钮）
4. 精细页四态齐全（05 文档第 4 节）；筛选/分页/tab 状态写入 URL
5. 无营销风格元素：无渐变大背景、无轮播、无深色大屏
6. 新企业注册→向导→示例演练全程 ≤10 分钟可完成
7. 生成 docs/route-access-map.md（路由×角色可达表）

## 文档索引

- 01 注册登录、租户模型、初始化向导 6 步
- 02 9 角色、能力矩阵、数据/字段/审批权限、审计
- 03 顶部栏、菜单树、角色×菜单矩阵、移动端边界
- 04 12 组核心页面逐页规格（布局/组件/操作/接口/状态）
- 05 色板、组件铁律、四态、效率细节
- 06 P1/P2/P3 范围与完成度
- 07 页面清单 30 页、复用组件、流程、MVP 首屏、自检
