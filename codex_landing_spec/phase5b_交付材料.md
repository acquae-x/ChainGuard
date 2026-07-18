# ChainGuard Phase 5B 交付材料

## 当前验收结论（Windows 补验，2026-07-18）

第一批文档中“沙箱宕机、未执行”的状态已经在 Windows 本机补齐；第二批实现、验收和风险核查也已纳入本文件。当前结果如下：

| 验证项 | 当前状态 | 留档/结果 |
|---|---|---|
| Windows 全量 `pytest tests/ -q` | ✅ 通过 | **562 passed, 4 skipped, 11 warnings**，110.70s，exit code 0；4 skip 仅为默认不连接外部 PG 的专项用例。JUnit：`phase5b_c2_pytest_20260718.xml` |
| PostgreSQL 专项约束/回填测试 | ✅ 通过 | PostgreSQL 16：`tests/test_phase5b_c2_postgres.py`，**4 passed**；复合 FK、部分唯一索引、租户隔离及冻结 0005 回填均实测 |
| SQLite Alembic 0001→0005 / down 到 0001 / up 到 0005 | ✅ 通过 | 干净 GUID 隔离库，最终 `20260718_0005 (head)` |
| PostgreSQL Alembic 0001→0005 / down 到 0001 / up 到 0005 | ✅ 通过 | 一次性 PostgreSQL 16 隔离容器，最终 `20260718_0005 (head)`；容器已删除 |
| 0005 在线存量回填 | ✅ 通过 | SQLite 与 PostgreSQL 干净环境均成功执行 `migrate_data_records` |
| 0005 离线 `--sql` | ✅ 明确守卫 | 不再生成部分 0005 DDL 后崩溃；现在于任何 0005 DDL 前 fail-fast，提示必须在线执行回填 |
| 第二批验收脚本 | ✅ 通过并归档 | `phase5b_c2_acceptance_20260718.json`：111,460 源行 / 111,460 成功 / 0 拒绝 / 111,460 审计行 |
| Git 提交/干净状态 | ✅ 本批选择性提交 | Phase 5B/C2 文件、测试与证据已纳入本文件所在提交；工作区仍保留未纳入本提交的既有 Phase 5A/前端改动，不把“本批已提交”误写成“整个工作区干净” |

> 全量测试最初在受限沙箱内得到 `518 passed, 1 failed, 40 errors`，失败均为 Windows 临时目录与 `data/` 写权限错误；按错误证据在沙箱外用唯一 basetemp 重跑后取得上表绿证。前一结果不作为产品失败，也不替代最终绿证。

## C2 第一批（实体表 + 迁移 + 共用映射边界，2026-07-15）

范围严格限定为 `11_Phase5B_前置产出.md` v2 §②③ 的 C2 第一批：8 张实体表的模型与单一
Alembic revision、共用映射边界（`config/erp_mapping.yaml` + adapter）、以及租户隔离/唯一
约束/外键/升级回滚/映射测试。**未进入 C1（无 context_builder）、未接线 import router /
scripts/erp_sync、未做 data_records 存量回填与 shipments 到货跨源聚合**（均属后续 C2 落表）。

### 诚实执行状态声明

本轮在 Cowork Linux 沙箱内实现。**实现过程中沙箱 VM 中途宕机（"VM service not running"），
因此下列"待执行"项在本会话未能运行**，绝不写成通过：

| 验证项 | 状态 |
|---|---|
| Alembic upgrade→downgrade→upgrade（revision 0004） | ✅ 本会话实际执行（原始输出见下） |
| 模型 `Base.metadata.create_all` + inspector 结构核对（8 表/复合 FK/唯一键/部分 active 索引） | ✅ 本会话实际执行（输出见下） |
| `config/erp_mapping.yaml` 解析 + resources 列表 | ✅ 本会话实际执行 |
| 模型/迁移/adapter/测试文件 Python 语法解析 | ✅ 本会话实际执行 |
| `pytest tests/test_entities_c2.py`（14 个新用例） | ⏳ **已写入，未执行**（沙箱宕机）——须在 Windows/可用环境运行 |
| `pytest tests/ -q` 全量回归 | ⏳ 未执行——须在 Windows 运行确认无既有断言回归 |

### 实际修改/新增文件

- `src/webapi/models.py`：新增 `EntityRecord` 混入 + 8 个实体模型（Material / SupplierEntity /
  SupplierMaterial / CustomerEntity / SalesOrder / SalesOrderLine / InventoryEntity / TenantConfig）；
  顶部 import 增加 `ForeignKeyConstraint, Index, text`。
- `alembic/versions/20260717_0004_phase5b_c2_entities.py`：新迁移（down_revision=20260713_0003），
  显式 `op.create_table` 建 8 表，tenant_id/业务键索引，tenant-aware 复合外键，
  tenant_configs 部分唯一索引（SQLite/PostgreSQL）；downgrade 仅删 8 表，不触碰 data_records。
- `config/erp_mapping.yaml`：唯一映射源（CSV 导入与 ERP 同步共用），逐 resource 声明
  source→target 字段、重命名、bool/bool_level 转换、必填/业务键、未知列→extra、敏感列拒绝、
  订单头/行聚合边界；inventory 到货字段标注为后续 shipments 跨源聚合、本批不接线。
- `src/webapi/entity_mapping.py`：共用映射边界 adapter——`load_mapping`/`validate_mapping`/
  `map_row`/`upsert_entities`（租户内业务键幂等 upsert，缺主键入拒绝清单不猜值）/
  `activate_tenant_config`（事务级先停用旧 active 再插新，单 active 双保险）/
  `normalize_transport_mode`（road/公路→canonical truck，引擎内不加 road 分支）。
- `requirements.txt`：追加 `PyYAML>=6,<7`（erp_mapping.yaml 解析）。
- `tests/test_entities_c2.py`：14 个用例（约束/FK/隔离/单 active/映射/迁移守卫）。

### Alembic upgrade/downgrade/upgrade（实际执行原始输出）

隔离库 `sqlite:////tmp/cg_mig4.db`，绝对 script_location + 项目 alembic.ini：

```text
INFO  [alembic.runtime.migration] Running upgrade  -> 20260711_0001, 初始业务表迁移
INFO  [alembic.runtime.migration] Running upgrade 20260711_0001 -> 20260712_0002, Phase 5A trace/notification/token-revocation
INFO  [alembic.runtime.migration] Running upgrade 20260712_0002 -> 20260713_0003, P0-2/P1-10 方案指标可空+归档
INFO  [alembic.runtime.migration] Running upgrade 20260713_0003 -> 20260717_0004, Phase 5B / C2 第一批：8 张结构化业务实体表
INFO  [alembic.runtime.migration] Running downgrade 20260717_0004 -> 20260713_0003, Phase 5B / C2 第一批：8 张结构化业务实体表
INFO  [alembic.runtime.migration] Running upgrade 20260713_0003 -> 20260717_0004, Phase 5B / C2 第一批：8 张结构化业务实体表
```

三步无异常。

### 模型结构核对（实际执行 inspector 输出摘要）

`Base.metadata.create_all` + `PRAGMA foreign_keys=ON` 后：

```text
materials: uq=[tenant_id, material_id]
suppliers: uq=[tenant_id, supplier_id]
supplier_materials: fks=[(tenant_id,supplier_id)->suppliers, (tenant_id,material_id)->materials] uq=[tenant_id,supplier_id,material_id]
customers: uq=[tenant_id, customer_id]
sales_orders: fks=[(tenant_id,customer_id)->customers] uq=[tenant_id, sales_order_id]
sales_order_lines: fks=[(tenant_id,sales_order_id)->sales_orders, (tenant_id,material_id)->materials] uq=[tenant_id,sales_order_id,line_no]
inventory: fks=[(tenant_id,material_id)->materials] uq=[tenant_id, inventory_id]
tenant_configs: uq=[tenant_id,config_type,version]
partial active index present: True
```

### 待执行命令（Windows / 可用环境补跑）

```text
python -m pytest tests/test_entities_c2.py -q
python -m pytest tests/ -q          # 确认无既有断言回归（基线 515 passed）
# Alembic 隔离库 up/down/up（本会话已在沙箱执行，Windows 复跑留档）
```

### 是否触碰禁止范围

未修改 orchestrator；未新增权限码；未弱化/删除既有断言（仅新增文件与 models/requirements 追加）；
未进入 C1 或其他 5B 批次；未虚构 scripts/erp_sync.py 的表→实体映射（adapter 为独立新模块）；
transport road→truck 仅在 adapter 边界处理，未改引擎枚举；cost_multiplier 直存不推导；
derived_metrics 未建实体表（明确为 Web builder 加法字段，属 C1）。

### 尚未完成 / 风险

1. `pytest tests/test_entities_c2.py` 与全量回归本会话未执行（沙箱宕机）——**必须补跑**，
   通过前不得视为验收完成。
2. data_records → 实体 存量回填 Alembic data migration、import router / erp_sync 接线、
   shipments→inventory 到货跨源聚合 均属后续 C2 落表，本批未做（按规格顺序）。
3. PostgreSQL 端外键/部分唯一索引仅在 SQLite 侧本会话验证；PG 侧须在 Windows/CI 补验。

## C2 第二批（导入执行 + 存量回填 + 跨源聚合，2026-07-18）

第二批已完成从三种导入通道到实体落表、逐行审计、拒绝留痕、重复导入防护和存量 `data_records` 回填，并接入现有 router/job 执行链。

### 实际修改/新增范围

- `alembic/versions/20260718_0005_phase5b_c2_import_execution.py`：新增 `signature_history`、`import_source_rows`、`import_rejections` 三表及索引/唯一约束；在线 upgrade 执行幂等存量回填；downgrade 仅移除第二批三表，不删除旧 `data_records` 或第一批实体表；新增离线 fail-fast 守卫。
- `src/webapi/models.py`：新增 `ImportSignature`、`ImportSourceRow`、`ImportRejection` ORM 模型。
- `src/webapi/entity_mapping.py`：新增 `migrate_data_records`、拒绝持久化及实体/产品页 adapter；旧数据只读迁移，无法转换的记录进入 `import_rejections`，源记录不删不改。
- `src/webapi/entity_import.py`：统一 CSV/OCR/ERP 的批量实体落表、源行审计、签名去重、全目录核对与 shipments 聚合。
- `src/webapi/routers/imports_settings.py` + `src/webapi/jobs.py`：接线确认、执行、后台 job、ERP 同步和成功/失败状态；本次补验修正 ERP sync 的相对导入路径，并增加路由回归测试。
- `scripts/phase5b_c2_acceptance.py`：隔离库全量核对脚本；补齐 Windows 直接运行时的项目根路径初始化，`python scripts\\phase5b_c2_acceptance.py ...` 已实跑通过。
- `tests/test_phase5b_c2_batch2.py`、`tests/test_phase5b_c2_entities.py`、`tests/test_entities_c2.py`、`tests/test_database_target_guard.py`：第二批与第一批约束/迁移/目标库守卫回归。
- `tests/test_phase5b_c2_postgres.py`：仅在显式提供一次性 `CHAINGUARD_TEST_POSTGRES_URL` 时运行的 PG 专项测试，避免误连开发/生产数据库。

### 验收脚本归档

#### 顶层全量回归证据（2026-07-18 复核）

在 `ChainGuard/` 目录按指定命令实际执行：

```text
python -m pytest tests/ -q
```

受限文件沙箱内的首次执行未被隐藏或记为通过；其结尾摘要原样为：

```text
1 failed, 521 passed, 4 skipped, 53 warnings, 40 errors in 105.73s (0:01:45)
```

唯一 `failed` 和 40 个 `errors` 均为 Windows ACL 拒绝写入或清理
`data/`、`test_tmp/pytest`、`.pytest_cache/` 所致；失败点为
`PermissionError: [WinError 5]` / `PermissionError: [Errno 13]`，不是业务断言失败。
不改测试、不改业务代码，在正常本机文件权限下使用完全相同的命令复跑，退出码为 `0`，结尾摘要原样为：

```text
562 passed, 4 skipped, 11 warnings in 108.11s (0:01:48)
```

4 个 `skipped` 是默认不连接外部 PostgreSQL 的专项用例；已有 PostgreSQL 16
专项验收结果仍为 4 passed，见本文顶部验收表。

#### Git 工作区复核

实际执行 `git status --short` 后，**整个工作区不干净**，因此不宣称
"工作区干净"或"无任何 C2 相关未提交改动"。当时状态包含：

- `ChainGuard/data/audit_log.jsonl`、`ChainGuard/data/model_registry.json` 和 `ChainGuard/output/`
  等运行生成物；
- `chainguard-web` 下正在进行的 EnterpriseImportWizard、导入历史兼容、数据展示及
  Playwright API 验收等未提交前端改动，这些与 C2 企业导入后续收口有关，不得忽略。

同时，将 `bfe3ce8 feat(phase5b): land C2 entity imports and freeze backfill`
的 33 个已提交文件与 `git status --porcelain=v1` 逐项求交，交集为 `0`：
**本文所述 C2 第二批后端提交范围无未提交残留，但整体工作区与 C2 前端后续工作仍未干净。**

直接入口实际执行：

```text
python scripts\phase5b_c2_acceptance.py --database <GUID隔离库> \
  --data-dir demo_assets\enterprise\csv --tenant-id tenant-phase5b-c2-direct \
  --job-id job-phase5b-c2-direct --account phase5b-c2-direct@example.local \
  --password <acceptance-only> --output ..\codex_landing_spec\phase5b_c2_acceptance_20260718.json
```

归档摘要：

```text
alembicRevision=20260718_0005
sourceRows=111460
successRows=111460
rejectedRows=0
auditedRows=111460
persistedSourceRows=111460
persistedRejections=0
```

### shipments→inventory 范围结论

该项**已经完成，不再是 C2 欠项，也未移出范围**。`entity_import.aggregate_shipments` 将未完成 shipments 与 `purchase_order_lines` 按采购单关联，按物料汇总 `max(ordered_qty - received_qty, 0)`，选择最近未完成到货时间并写入对应租户库存的 `in_transit_qty`、`planned_arrival_at`、`estimated_arrival_at`。本次验收数据中 3,000 条 shipments 聚合了 240 个物料并更新 240 条 inventory，0 拒绝；专项单测同时覆盖完成状态排除、UTC 时间归一和目标仓选择。

### 0005 data migration 风险结论

- 已解决应用层漂移风险：0005 回填已改为 revision 内冻结的 SQLAlchemy Core snapshot，不再导入 `src.webapi`、当前 ORM、业务 adapter 或运行时 `erp_mapping.yaml`，也不再在 Alembic migration 内自行 `Session.commit()`。
- 已证实：在线干净 SQLite/PostgreSQL upgrade、down、up 均可运行；SQLite 测试从 0003 注入 6 条真实 legacy 记录后升级，正确生成物料/客户/订单/库存并对敏感行、非法 FK 行各留一条拒绝记录，且不删除/改写 `data_records`；PostgreSQL 专项也直接执行同一冻结回填并通过。
- 已修复：原先离线 `--sql` 会先输出三表 DDL，再在 ORM `MockConnection` 上崩溃；现于 0005 开始时明确 fail-fast，不会产生看似可用但缺回填的部分 SQL。
- 设计边界：离线 SQL 仍明确不支持该数据回填，因为静态 SQL 无法诚实复现逐行 JSON 兼容映射与拒绝留痕；部署必须走在线 migration。该限制现在是显式、可测试的契约，不再是隐式崩溃。

### Git 核查结论（提交前事实与本次处理）

- `git log` 中没有 Phase 5B 提交；最新提交仍为 `69b8b0d phase5a: ...`。
- 接手时 0004、0005、`entity_import.py`、`entity_mapping.py`、`entity_repository.py`、`erp_mapping.yaml`、验收脚本及 Phase 5B 测试均为未跟踪文件；不是“已提交但状态没留档”。
- 本次按 Phase 5B/C2 清单选择性暂存并提交相关实现、测试与证据；工作区中其它既有 Phase 5A/非本批前端修改继续保留，未混入本批提交。

## Phase 5B/C2 外部集成补验（2026-07-18）

本节只记录本轮验收事实；未修改 orchestrator 决策流水线、既有 Phase 5B/C2 后端或测试。

### 真实 OCR 能力与降级边界

- 运行时探针结果：`llm_vision=False`、`ocr_engine=False`、`text_layer=True`、`word_text=True`。
  本机未安装 `paddleocr`、`pytesseract` 或 tesseract 可执行文件；环境也没有
  `CHAINGUARD_VISION_API_KEY` / `CHAINGUARD_VISION_API_URL`。因此本轮不能宣称真实扫描件
  OCR 成功识别。
- 实际上传一张带文本的 PNG 后，预检状态为 `manual_required`、提取方式为
  `manual_required`；继续确认返回 HTTP 409，证明缺少 OCR 后端时不会静默落库或绕过人工闸门。
- 实际 PDF 通过 `pypdf` 文本层提取成功，状态进入 `manual_review`；未人工确认时返回
  HTTP 409，确认字段映射后成功落库 1 行。该结果属于真实 PDF 文本提取，不冒充 OCR。

### 真实 HTTP ERP 连接器同步

使用仓库 `scripts/mock_erp_server.py` 启动真实本地 HTTP 服务，API 路由通过
`RestErpConnector` 实际分页读取并写入 GUID 隔离 SQLite；未 mock connector 或同步函数。

```text
连接探测：ok=true，样例 1 行，materials 总数 240
目录预览/同步总行数：16953
materials=240, suppliers=60, customers=120, supplier_materials=1066,
sales_orders=3500, sales_order_lines=10527, inventory=1440
同步结果：sourceRows=16953, successRows=16953, rejectedRows=0
```

逐表报告、导入历史和五个资料页总数均与源数据一致；第二租户五个资料页均为 0，读取第一租户
ERP job 返回 404。隔离数据库在进程退出后已删除。

### CSV + 文档/图片 + ERP 混合闭环

同一租户、同一批量分类入口实际上传 `materials.csv`、`materials_scan.pdf`、
`materials_scan.png`，系统分别识别为 `structured`、`ocr`、`ocr`：

- CSV 成功落库 1 行；
- PDF 经真实文本层提取、人工确认和字段映射后成功落库 1 行；
- PNG 因无真实 OCR 后端停在 `manual_required`，确认被 HTTP 409 阻止；
- 随后同租户从 ERP 同步 materials 240 行，资料页最终为 242 行，CSV/PDF 两条可见，
  PNG 未被静默导入；历史状态依次为 `succeeded`、`succeeded`、`manual_required`、
  `succeeded`。

因此混合渠道的真实闭环在当前环境下达到“可处理来源落库、不可处理来源明确人工挂起、ERP 继续同步并在
同一资料页汇合”；唯一未完成项是外部 OCR 引擎本身的成功识别。

### 隔离 PostgreSQL 16 补验

Docker Desktop 29.6.1 启动后创建一次性 `postgres:16-alpine` 容器，使用独立数据库名、
测试凭证和随机本机端口；未使用默认数据库或现有 compose volume。Alembic 从 0001 在线升级至
`20260718_0005` 后：

```text
python -m pytest tests/test_phase5b_c2_postgres.py -q
4 passed in 0.79s
```

另经真实 API 完成 CSV 上传→预检→确认→异步执行→job 轮询→资料页：
`sourceRows=1, successRows=1, rejectedRows=0`；第二租户资料页为 0，读取该 job 返回 404。
容器、隔离数据库和临时上传目录均已删除，Docker Desktop 已恢复为未运行状态。

### 定向回归与运行证据边界

OCR、连接器、企业导入和 C2 映射相关 7 个测试文件在正常本机权限下复跑：

```text
69 passed in 15.69s
```

受限文件沙箱首次运行出现的 13 个 setup error 及 pytest 收尾异常均为 GUID basetemp 的
Windows ACL 拒绝访问；不改测试、不改业务代码后重跑全绿。

`ChainGuard/data/audit_log.jsonl`（新增 671 条运行事件）、
`ChainGuard/data/model_registry.json`（新增 168 条逐行记录）、`ChainGuard/output/` 和根目录
`output/` 均为既有运行证据/噪声。本轮只检查、不删除、不提交，也不与本交付文档混入同一提交。
