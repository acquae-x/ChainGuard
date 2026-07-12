# ChainGuard 企业演示数据资产包

本资产包用于复赛演示、ERP/WMS/TMS 接口联调、数据映射和算法回放。所有企业、
人员、订单、金额和风险事件均为程序生成的合成数据，不对应任何真实主体。

## 生成方式

使用工作区内带有 `openpyxl`、`reportlab` 和 `pypdf` 的 Python：

```powershell
python scripts/generate_enterprise_demo_data.py
```

默认输出到 `demo_assets/`。生成过程使用固定随机种子 `20260615`，因此同版本脚本
每次生成的数据口径和主外键关系一致。

## 资产结构

```text
demo_assets/
  manifest.json
  enterprise/
    csv/                         # 18 张企业业务表
    database/
      chainguard_enterprise_demo.db
    json/
      dashboard_summary.json
  erp_api/
    openapi.yaml
    sample_requests.http
  small_business/
    ChainGuard小企业供应链演示账套.xlsx
  pdf/
    企业供应链风险管理周报.pdf
    库存与安全库存缺口明细.pdf
    业务单据/
      采购订单/                  # 12 份
      送货单/                    # 12 份
    风险事件简报/                # 8 份
```

`manifest.json` 记录每张表的行数、总记录数、文件大小和生成时点，可作为演示时的
统一数据说明。

## 企业数据表

| 表 | 典型系统 | 用途 |
| --- | --- | --- |
| materials | ERP | 物料主数据、成本、关键等级 |
| warehouses | ERP/WMS | 仓库与产能主数据 |
| suppliers | ERP/SRM | 供应商主数据与风险 |
| supplier_materials | SRM | 供应商物料、交期、可供量、价格 |
| customers | ERP/CRM | 客户分级、信用与 SLA |
| inventory | WMS | 当前库存、锁定、在途与安全库存 |
| inventory_snapshots | WMS | 31 天库存日快照 |
| inventory_movements | WMS | 收发存与调整流水 |
| sales_orders / sales_order_lines | ERP | 销售订单头与明细 |
| purchase_orders / purchase_order_lines | ERP | 采购订单头与明细 |
| shipments | TMS | 在途运输、路线、预计到达和延误 |
| quality_inspections | QMS | 来料、过程和终检记录 |
| production_plans | MES/ERP | 生产计划、物料齐套和风险 |
| supplier_performance | SRM | 12 个月供应商绩效 |
| disruption_events | 风险平台 | 台风、停产、召回、需求突增等事件 |
| historical_decisions | 应急台账 | 历史策略、预测值、实际结果与复盘 |

## 启动模拟 ERP API

先生成数据，再执行：

```powershell
python scripts/mock_erp_server.py
```

默认地址为 `http://127.0.0.1:8765`。主要接口：

- `GET /health`
- `GET /api/v1/catalog`
- `GET /api/v1/dashboard/summary`
- `GET /api/v1/inventory?page=1&page_size=100`
- `GET /api/v1/sales-orders?order_status=at_risk`
- `GET /api/v1/disruption-events?event_status=active`

业务列表接口统一返回：

```json
{
  "resource": "inventory",
  "page": 1,
  "page_size": 100,
  "total": 1440,
  "items": []
}
```

API 直接读取生成的 SQLite 数据库，因此接口、CSV 和数据库中的业务记录保持一致。
完整接口目录见 `demo_assets/erp_api/openapi.yaml`。

## 演示建议

1. 用管理周报解释企业面临的库存、订单、供应商和运输风险。
2. 用 Excel 展示小企业无需 ERP 时的可落地数据入口。
3. 用 ERP API 的 `catalog` 和分页接口证明系统具备标准化集成形态。
4. 用 SQLite/CSV 做算法批量回放、参数校准和基准评测。
5. 明确说明当前 API 是本地模拟服务，不应对外表述为已接入真实企业 ERP。
