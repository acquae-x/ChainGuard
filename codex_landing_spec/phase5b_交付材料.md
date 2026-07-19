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

## Phase 5B/C2 前端最终收口（2026-07-18）

本节补记提交 `48bb5b6 fix(web): close ERP sync and mobile header acceptance` 的最终验收事实；
未修改 orchestrator 决策流水线或已验收的 Phase 5B/C2 后端，也未弱化既有测试。

### ERP 同步确认与长请求

- ERP 连接预览成功后，确认步骤继续使用已预览的 `baseUrl` / `apiKey`，不再因连接表单卸载而
  丢失 `baseUrl`。
- ERP 同步请求单独允许 5 分钟超时，以覆盖十万级数据分页读取与落库；其它 API 请求仍保持
  10 秒默认超时，未扩大长超时范围。
- 在 GUID 隔离 SQLite 与仓库 `scripts/mock_erp_server.py` 提供的真实本地 HTTP ERP 上，
  从 UI 发起全量同步并轮询完成：`sourceRows=111460`、`successRows=111460`、
  `rejectedRows=0`，耗时约 16.8 秒。导入历史与物料资料页均正常回显。

### 375px 移动端顶栏

在 `375×812` 视口实测“更多 / 通知 / 用户菜单”三个入口均固定在可见区域，横向坐标范围为
`x=221–346`，没有被右侧裁切。

验收截图（本机 Codex 可视化留档，不纳入 Git 运行证据）：

- `phase5bc2-fix-acceptance/01-mobile-header-fixed.png`
- `phase5bc2-fix-acceptance/02-erp-ui-111460-succeeded.png`

### 前端定向回归与构建

新增或更新的测试覆盖 ERP 连接信息跨步骤保留、ERP 长请求超时和移动端顶栏定位。最终验证：

```text
Vitest：11 个文件、21 个测试通过
tsc --noEmit：零错误
DATA_MODE=api 生产构建：通过
```

### 最终外部依赖边界

- 真实 PNG/JPG 扫描件 OCR 成功验收仍需可用 OCR 引擎或
  `CHAINGUARD_VISION_API_KEY` / `CHAINGUARD_VISION_API_URL`；当前环境已验证缺少能力时进入
  `manual_required`，确认返回 HTTP 409，不会静默落库。
- 第三方生产 ERP 仍需客户测试租户、地址、凭据与证书，后续应补验真实鉴权、分页、限流、
  失败重试和错误脱敏。本轮的 111,460 行验收使用真实本地 HTTP 与 `RestErpConnector`，
  不冒充第三方生产 ERP 验收。
- 验收所用隔离服务、数据库和临时目录均已清理；默认数据库未使用、未污染。

## Phase 5B 本地真实图片 OCR 闭环（2026-07-19）

本节覆盖此前“真实 PNG/JPG 扫描件 OCR 尚未完成”的唯一欠项，并取代本文前面关于
“当前环境无 OCR 引擎”的旧状态描述。既有 PDF 文本层、Word、CSV、ERP 路径和不可识别时
`manual_required` 的安全闸门均保留。

### 引擎选择与部署

- 采用 `rapidocr==3.9.1` + `onnxruntime==1.27.0`（仓库约束为
  `rapidocr>=3.4,<4`、`onnxruntime>=1.20,<2`）。RapidOCR 使用 Apache-2.0 许可，默认
  PP-OCRv6 检测/识别模型支持中文和英文，ONNX Runtime 在当前 Windows x86-64 / Python
  3.13.5 有预编译 wheel；不需要管理员安装 Tesseract，也不需要 API 密钥或本机绝对模型路径。
- 未采用旧包 `rapidocr-onnxruntime`：该包声明 Python `<3.13`，不适合当前 Python 3.13.5。
- 安装方式仍为 `python -m pip install -r requirements.txt`。RapidOCR wheel 内已核对包含
  `PP-OCRv6_det_small.onnx`、`PP-OCRv6_rec_small.onnx`、
  `ch_ppocr_mobile_v2.0_cls_mobile.onnx` 三个模型；正常安装不需要运行时另配模型目录。
- `.env.example` 新增以下非敏感配置：
  `CHAINGUARD_OCR_ENABLED=true`、`CHAINGUARD_OCR_TIMEOUT_SECONDS=20`、
  `CHAINGUARD_OCR_MIN_CONFIDENCE=0.75`、`CHAINGUARD_OCR_MAX_PIXELS=25000000`。
  仓库未写入密钥、真实环境变量值或本机绝对路径。

### 真实调用链与安全边界

1. `/api/v1/imports/upload?mode=ocr` 将原图保存到租户和 job 双重隔离的工作目录；响应不暴露
   服务端路径。
2. `/imports/{id}/preflight` 调用 `src.ingestion_agent.ingest_files`。PDF/DOCX 先走已有文本层；
   PNG/JPG 再按需探测本地 RapidOCR，最后才考虑可选远程视觉后端。
3. OCR 引擎只在图片预检时于独立子进程导入并初始化；超时会终止子进程。实测仅导入 FastAPI
   用时约 `0.765s`，主 API 进程中 `rapidocr_loaded=False`、`onnxruntime_loaded=False`。
4. 成功结果按行形成 `normalized.csv`，回传引擎名、最低文本置信度、行数和耗时，进入已有
   类型识别、预检和人工复核；必须提交 `manualConfirmed=true`，可同时提交 `fieldMapping`。
5. `/execute` 先做租户内签名占用，再由后台 job 将归一化 CSV 送入 C2 共享 YAML adapter，
   写实体表、源行审计和拒绝记录；job 成功后可由 `/data/material` 等资料页查询。
6. 缺引擎、显式禁用、图片损坏、空白、超过像素限制、引擎异常、超时和最低文本置信度低于
   阈值分别给出稳定错误码，全部停在 `manual_required`，不生成可执行 CSV，也不能强制确认
   或静默落库。

### 隔离数据库真实 API 端到端验收

验收使用 pytest 进程启动前生成的 GUID SQLite `DATABASE_URL` 和测试模块自有 GUID 临时目录；
没有使用默认 `chainguard.db`，也没有读取/覆盖既有 `data/`、`ChainGuard/output/` 或根 `output/`
生成物。图片由 Pillow 真实渲染，RapidOCR/ONNX Runtime 真实推理；未 mock OCR 输出、预检、
字段映射、后台 job 或资料查询。

闭环如下：

```text
PNG 上传（中文字段：物料编码/物料名称/成本）
→ RapidOCR 本地推理
→ manual_review 预检（canProceed=true，预览行可见）
→ 人工确认 + 中文字段映射
→ execute 202
→ job 轮询 succeeded（sourceRows=1, successRows=1, rejectedRows=0）
→ 物料资料页可见“中英文OCR芯片”且成本为 12.50
→ 新注册第二租户资料页不可见该物料
```

一次留痕运行中，图片预检 OCR 耗时 `4.666s`，完整单用例（含应用/种子、上传、OCR、预检、
确认、异步执行、轮询、资料页及数据库隔离断言）耗时 `6.73s`。此前直接引擎探针的模型推理
耗时约 `2.063s`；API 路径较长是因为每次使用可强制终止的独立子进程冷启动，属于安全超时与
吞吐之间的明确取舍。

### 测试与实际执行结果

- 新增 `tests/test_phase5b_ocr.py`：真实 PNG/JPG 中英文识别；OCR→预检→中文字段映射；
  人工确认→执行→job 轮询→实体/资料页；第二租户不可见；缺引擎、空白、损坏、低置信度、
  超时安全降级；CSV 直读和 PDF 文本层不调用 OCR。
- OCR/C2/预检定向回归：`38 passed, 2 warnings in 34.04s`，退出码 0。
- 后端全量回归：`567 passed, 4 skipped, 11 warnings in 147.61s`，退出码 0。4 个 skip 仍为
  未显式提供外部 PostgreSQL URL 的专项用例；warning 为既有 FastAPI `on_event` 弃用、
  sklearn SVC 参数弃用及缺少可选 cryptography 的降级提示。
- `python -m ruff check src\ingestion_agent.py tests\test_phase5b_ocr.py`：通过。整个既有
  `imports_settings.py` 单独做 Ruff 扫描仍有 57 个历史单行语句格式告警，本轮没有借 OCR
  改动大规模重排无关路由。
- 首次在受限沙箱运行仍出现 `test_tmp/pytest` / GUID basetemp 的 Windows ACL setup error，
  与本文此前记录一致；改用全新隔离 basetemp 并在正常本机权限运行后取得上述结果。
  第一轮真实 API 用例曾因成功预检响应未回传 extraction 元数据而 `17 passed, 1 failed`；
  已补齐响应中的引擎/置信度/耗时元数据，随后单用例、定向和全量回归均通过。

### 已知限制与验收结论

- 本轮完成的是 PNG/JPG（同时兼容代码中已有 BMP/TIF 后缀）的本地真实 OCR。扫描型 PDF
  尚未实现逐页栅格化；PDF 有文本层时继续真实提取，无文本层且无可用远程视觉服务时仍安全
  进入 `manual_required`。
- 归一化按 OCR 文本行及逗号/制表符重建字段；复杂表格、跨行合并单元格、手写体、严重倾斜、
  低分辨率或强噪声扫描件仍需要人工校对字段映射。置信度是识别文本框最低分，默认阈值
  `0.75`，生产方应结合自有单据样本校准，不能通过降低阈值绕过人工确认。
- 当前为 CPU 冷启动、单图片独立子进程方案，单张规范表格约 4–5 秒；高并发或多页批量场景
  应增加受控 OCR worker 队列/并发上限，而不是取消超时。默认 20 秒和 2,500 万像素是资源
  安全边界。
- 结论：**达到本轮 Phase 5B PNG/JPG 真实 OCR 验收标准**。真实识别、预检、人工确认/字段
  映射、异步落实体、job 轮询、资料页可见、租户隔离和全套安全降级均已实测；扫描 PDF
  栅格 OCR 和生产高并发优化属于已明确记录的后续增强，不冒充已完成。

## Phase 5B OCR 产品界面闭环（2026-07-19）

本轮只补齐数据导入向导的产品闭环，不重写 RapidOCR、本地图片提取、预检、confirm
`fieldMapping` 或“OCR 必须人工确认”的安全策略。

### 人工确认与字段映射

- OCR/Word/PDF 预检完成后，人工确认页从现有 `normalized.previewRows` 展示识别到的源字段和
  样例值，并提供目标字段选择；同一目标字段不能被重复选择。
- 默认建议复用表格导入已有的字段别名和相似度匹配逻辑，再转换为 confirm API 使用的规范键，
  不是只对三条中文文案写死判断。物料类型已实测支持：`物料编码 → material_id`、
  `物料名称 → material_name`、`成本 → standard_cost`；英文标准字段保持同名映射。
- 必填目标字段未完成映射时会在文件级显示错误，并阻止执行。用户确认后的映射随
  `fieldMapping` 发送给现有 confirm API；未选择的源字段不提交。
- OCR/文档仍必须勾选“已核对原文、类型和关键字段”才能执行；没有增加 force 或自动确认旁路。

### 行级拒绝结果

- 共享实体导入结果最小化补充 `rejections` 明细透传（源行号、后端原始拒绝原因、源数据），
  不改 OCR/映射/落库规则；向导结果页在批次展开区显示逐行拒绝明细。
- 前端根据后端原因展示可读修复建议，覆盖缺业务键/必填字段、类型格式、非法外键、敏感或
  禁止字段、未声明列，并为未知原因提供通用核对建议。

### 实际验收

使用 GUID 隔离 SQLite、`DATA_MODE=api`、真实本地 API、真实 Chromium 和真实 RapidOCR；
测试图片由 Chromium 以清晰中英文文本渲染为 PNG，未 mock OCR、预检、confirm、execute、
job 轮询或资料页查询。

```text
中文 PNG：物料编码,物料名称,成本
→ UI 选择物料主数据
→ RapidOCR 成功（2 行，最低置信度约 0.9989）
→ UI 核对三字段规范映射
→ 勾选人工确认
→ confirm/execute/job 轮询 succeeded
→ 结果成功 1、拒绝 0
→ 物料页可见编号、中文名称、成本 12.50

英文 PNG：material_id,material_name,standard_cost
→ 同一 UI 流程 succeeded
→ 结果成功 1、拒绝 0
→ 物料页可见编号、英文名称、成本 23.75
```

另用两行真实 CSV（1 行有效、1 行缺业务主键）复验结果页：批次成功 1、拒绝 1，展开后可见
拒绝源行、`缺业务主键/必填字段` 原因、源数据和“补齐必填字段/修正字段映射”的修复建议；
既有重复签名和租户隔离断言继续通过。

本轮实际执行结果：

```text
TypeScript：npx tsc --noEmit，exit code 0
Vitest 全量：11 个文件、24 个测试通过
DATA_MODE=api 生产构建：Webpack 编译与 route access map 生成通过
后端定向：tests/test_phase5b_c2_batch2.py，15 passed
Playwright API 模式 OCR UI：1 passed（中文别名闭环 + 英文标准字段回归）
Playwright API 模式部分拒绝：1 passed（含逐行原因/建议、重复签名、租户隔离）
```

隔离验收数据库位于 `.workspace`，不使用或污染默认数据库；提交与推送状态以 Git 历史为准。

## Phase 5B/C1 真实租户上下文决策链（2026-07-19）

本节仅覆盖 C1：实体表到决策引擎的真实上下文适配、租户配置解析、新编排入口和 Web
后台作业闭环。未提前实现校准治理 UI、E-3 经验闭环、C3 初始化向导或账户完善。
`DecisionOrchestrator.run_demo()` 的入口和固定演示行为保留；既有演示断言未降低。

### 实际实现范围

- `src/webapi/context_builder.py`：新增正式 Pydantic 契约 `EngineContext` 及 inventory、orders、
  suppliers、transport_options、events、data_quality 子模型；新增 `TenantContextBuilder`、
  `build_incident_context` 和结构化 `ContextBuildError`。所有实体、风险、事件、配置查询和 join
  均显式带 `tenant_id`。
- builder 从 materials、inventory、supplier_materials/suppliers、sales_order_lines/sales_orders/
  customers 构建引擎五段 context；订单需求在 SQL 按订单头聚合，订单头财务值只计一次；
  时间统一为 UTC、引擎时长统一为小时、数量为件、金额为 CNY。
- `derived_metrics` 新增库存支撑时长、可用库存、库存缺口、在途量、最近计划/预计到货 UTC、
  到货延误、关键订单金额/罚金/毛利暴露、供应商可替代数量/可供量/最优交期及单位说明。
- 阻断规则落地：CG-2510 事件/作业不存在或跨租户、CG-2511 无有效物料、CG-2512 消耗量
  缺失或不大于 0、CG-2513 无库存记录、CG-2514 高风险事件无预计延误。无订单、无供应商、
  无到货信息、中低风险无延误、财务字段估算、可靠性缺失及安全库存缺失均返回结构化
  `data_quality` 降级，不读取 demo 数据。
- `tenant_configs` 只采用当前租户 `is_active=true` 且 `approved_by/approved_at` 完整的版本；
  thresholds、risk_weights、transport_options、estimation_coefficients 分别返回 source、version、
  ignored_version/fallback_reason。无有效配置回退专家 YAML 默认值，并在
  `context.configuration.fallback_reasons` 留痕。未批准或未激活版本不生效。
- `DecisionOrchestrator.run_tenant_scenario(...)` 新增租户入口，复用既有 `_run_context` 流水线；
  Web 租户路径显式禁用文件态演示经验检索、经验卡写入和 JSONL 审计追加，只由现有 DB 表
  持久化租户决策明细和审计。`run_demo()` 仍使用原默认文件态行为。
- tenant adapter 将真实 supplier_price、应急数量/倍率、供应商交期、运输倍率及订单罚金暴露
  物化为方案 `total_cost`、`lead_time_impact` 和 `economic_basis`；因此实体报价、交期、订单金额
  与库存变化会实际改变风险、成本、交期或供应商选择，不是“先查表后返回 demo”。
- `src/webapi/jobs.py` 已从 `run_demo()` 切换到 `_execute_tenant_decision` →
  `run_tenant_scenario()`。decision executor worker 内部自行创建和关闭 `SessionLocal`；请求 Session
  与外层 job worker Session 均不跨线程传递。job/incident/proposal/detail/audit 的读取和写入再次按
  job tenant 校验。异常日志只记录 job id 和异常类型，不输出 DB URL、驱动异常正文或业务字段。
- Web sensitivity 改为当前租户 context、风险权重与阈值，并以当前库存的 0.5x/1x/1.5x 计算，
  不再在 Web 决策明细中混入固定 demo sensitivity。新增
  `GET /api/v1/incidents/{id}/decision-readiness`，与 builder 共用同一套阻断/降级事实源。

### 本轮 C1 变更文件

- 新增：`ChainGuard/src/webapi/context_builder.py`
- 修改：`ChainGuard/src/orchestrator.py`
- 修改：`ChainGuard/src/sensitivity.py`
- 修改：`ChainGuard/src/webapi/jobs.py`
- 修改：`ChainGuard/src/webapi/proposal_mapper.py`
- 修改：`ChainGuard/src/webapi/routers/business.py`
- 新增：`ChainGuard/tests/test_phase5b_c1_tenant_decision.py`
- 修改：`ChainGuard/tests/test_webapi.py`（仅将两个作业单元测试的 patch 点从已移除的
  `run_demo` 调用改到新的 worker 边界；原并发/归档断言保留）
- 修改：`codex_landing_spec/phase5b_交付材料.md`（本节）

接手时已经存在的 OCR/C2 修改、`.env.example`、requirements、ingestion/import router、
`test_phase5b_ocr.py`、data JSON/JSONL、output 目录及后续出现的 git 属性/忽略文件变动均未清理、
覆盖或纳入上述 C1 实现清单。

### GUID 隔离库真实闭环与前后变化证据

验收使用 `tests/conftest.py` 在进程导入前生成的 GUID SQLite `DATABASE_URL` 和独立 GUID
pytest basetemp；没有使用默认 `chainguard.db`，也没有读取/覆盖现有 data/output 作为租户输入。
最小企业数据通过 C2 共享 `erp_mapping.yaml` adapter 真实导入：1 物料、1 合格供应商及报价、
1 库存（含在途和到货时间）、1 A 级客户、1 订单头和 1 订单行。随后通过真实 API 发起决策、
轮询 job、读取方案和 decision-detail；未 mock builder、orchestrator 或持久化结果。

第一次作业后，将同租户库存从 25 件改为 260 件、供应商报价改为 29 元/件、交期从 30 小时
改为 72 小时，再次通过 API 生成。原始机器可读摘要：

```text
{"c1Acceptance":{"firstRiskIndex":76.51,"changedRiskIndex":54.52,
"firstProcurementCostCny":5712.0,"changedProcurementCostCny":9744.0,
"firstLeadDays":1.25,"changedLeadDays":3.0,"supplierPriceCny":29.0,
"elapsedMs":4277.49}}
```

风险随库存增加下降；成本使用修改后的真实报价上升；采购交期随供应商交期从 30h 增至 72h
而上升。另一租户读取第一租户 job 和 incident 均为 HTTP 404；同业务键双租户夹具还断言库存、
报价、订单金额和 context 完全分离。Session 追踪回归观察到外层 job 与 decision worker 至少两个
不同线程各自获取 Session。

### 测试原始摘要

C1 真实定向验收（含 `-s --durations=10`）：

```text
9 passed, 2 warnings in 10.93s（生成机器可读前后对比的留痕运行）
slowest: Web 导入→两次决策→隔离/Session 闭环 4.28s
```

补入 Web 阻断 job 结构化失败回归及去除租户入口 `demo_source()` 表面依赖后的最终定向结果：

```text
23 passed, 2 warnings in 28.49s
（C1 10 项 + test_orchestrator/test_orchestrator_data_source 13 项）
Ruff: All checks passed!
```

C1 + 固定 run_demo + 既有 Web API 组合回归：

```text
61 passed, 2 warnings in 36.48s
```

后端全量（`python -m pytest tests/ -q`，使用独立 GUID basetemp）：

```text
577 passed, 4 skipped, 11 warnings in 153.69s (0:02:33)
```

4 个 skip 是显式要求 `CHAINGUARD_TEST_POSTGRES_URL` 的 PostgreSQL 专项；warning 仍为既有
FastAPI `on_event` 弃用、sklearn SVC 参数弃用和缺可选 cryptography 的安全降级提示。
新增/独立 C1 文件及触及的非遗留风格文件 Ruff 检查通过。`jobs.py`、`business.py`、
`test_webapi.py` 整文件仍有既有单行语句 Ruff 告警，本轮未借 C1 大规模格式化无关代码。

### PostgreSQL/迁移与已知限制

- SQLite migration、upgrade/down/up、复合外键和实体/配置专项均已包含在上述全量回归并通过。
- 本机 Docker CLI 为 29.6.1，但本轮检查时 Docker Desktop Linux daemon 未运行，且
  `CHAINGUARD_TEST_POSTGRES_URL` 未设置，因此未启动外部服务、未连接默认/既有数据库，也不把
  本轮记录为 C1 PostgreSQL 通过。C2 已有一次性 PostgreSQL 16 的 4 passed 证据；C1 的 SQL
  使用标准 SQLAlchemy 聚合及 tenant-aware join，仍应在提供一次性 URL 时补跑同一 C1 套件。
- 本次 4.28s 是最小真实 API 双决策闭环耗时，不替代前置规格规定的 1 万/5 万库存、4 并发、
  p50/p95/峰值 RSS 正式容量基准；该 benchmark 仍是 C1 后的独立压测批次，未虚构为已完成。
- 安全库存全为 0 时，既有库存 scorer 需要正分母；builder 使用“1 天日耗量”专家估计并明确写入
  `missing_safety_stock` 与 `estimated_fields=inventory.safety_stock`。这不是 demo 数值，后续校准
  治理面板可让租户审核替换。
- C1 只关闭真实上下文与决策链。租户 DB 经验卡检索/写入属于后续 E-3；在其实现前 Web 租户
  决策的 experience reference 固定为空，绝不会回退全局演示经验文件。
