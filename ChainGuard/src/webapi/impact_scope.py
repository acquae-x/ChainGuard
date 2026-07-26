"""A04 影响范围完整版：一条风险/一个事件到底波及了哪些**真实**业务对象。

三条硬约束：
- **只走真实外键**。每条影响关系都由 C2 实体表上的外键承载，关系所经的表名写进
  ``relation.via``，可被逐条核对。不做任何字符串模糊匹配——旧的尽力版正是靠子串
  匹配"猜"关系，那既会漏也会误报。
- **不评分、不估损**。本模块只做图遍历 + 去重 + 分组，回答"波及了谁、经由什么关系"。
  影响程度与损失金额属决策链路（C1/orchestrator）职责，在这里给数字就得新写公式。
- **数据不足时如实说明**。零关联就说零关联，仓库是聚合出来的就标明是聚合出来的，
  宁可返回一个空分组加一句限制，也不编造一条影响结论。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .context_builder import _CLOSED_ORDER_STATUSES
from .decision_detail import mask_for_requester
from .models import (
    CustomerEntity,
    ImportJob,
    Incident,
    InventoryEntity,
    Material,
    Risk,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
    Task,
)

# 单类实体命中上限。超出即截断并明示真实总数——宁可截断也不让一次请求拖垮页面。
MAX_ITEMS_PER_TYPE = 500

# 分组固定顺序。没有命中的分组**仍然出现**且 total=0：
# "暂无数据"必须是显式的，不能靠分组消失来暗示。
GROUP_ORDER = ("material", "inventory", "warehouse", "supplier", "order", "customer", "task")

GROUP_LABELS = {
    "material": "物料", "inventory": "库存", "warehouse": "仓库", "supplier": "供应商",
    "order": "订单", "customer": "客户", "task": "任务",
}

# 关系标签是固定中文常量，不是生成文本——A04 全程不调用 LLM。
RELATION_LABELS = {
    "seed_material": "风险/事件直接指向的物料",
    "seed_supplier": "风险/事件直接指向的供应商",
    "material_inventory": "该物料的库存记录",
    "inventory_warehouse": "存放受影响库存的仓库",
    "supplies_material": "为受影响物料供货",
    "order_consumes_material": "订单中包含受影响物料",
    "order_customer": "经由订单关联的客户",
    "shared_supplier": "与受影响物料共用供应商",
    "supplied_by_seed_supplier": "由受影响供应商供货",
    "incident_task": "该事件下的应急任务",
}

ENTITY_LINKS = {
    "material": "/data/material", "inventory": "/data/inventory", "supplier": "/data/supplier",
    "order": "/data/order", "customer": "/data/customer",
}

# 承载每类实体的真实表名，写进 source.table 供核对。
ENTITY_TABLES = {
    "material": "materials", "inventory": "inventory", "warehouse": "inventory",
    "supplier": "suppliers", "order": "sales_orders", "customer": "customers", "task": "tasks",
}

# 实体 → import_jobs 报告里的资源类型，用于批次归属。
_RESOURCE_FOR_ENTITY = {
    "material": "material", "inventory": "inventory", "warehouse": "inventory",
    "supplier": "supplier", "order": "order", "customer": "customer",
}

EMPTY_REASONS = {
    "material": "未发现其他关联物料",
    "inventory": "受影响物料暂无库存记录",
    "warehouse": "无库存记录，因而无法定位仓库",
    "supplier": "受影响物料暂无供应商供货记录",
    "order": "受影响物料暂无未关闭订单",
    "customer": "无未关闭订单，因而无法关联到客户",
    "task": "该风险尚未产生应急事件，或事件下暂无任务",
}

LIMITATION_MESSAGES = {
    "CG-A041": "起点已解析，但在两跳范围内没有找到任何关联业务对象；"
               "影响范围有限，请先补齐库存/供应商/订单等基础资料。",
    "CG-A042": "系统没有独立的仓库主数据，仓库分组由库存行的仓库字段聚合得出。",
    "CG-A044": "单类实体命中数超过上限，明细已截断。",
    "CG-A045": "已关闭的订单不计入影响范围。",
}

# 起点物料的键名集合与 C1 _resolve_material 保持一致，不新发明键名。
_MATERIAL_KEYS = ("material_id", "materialId", "affected_material_id", "affectedMaterialId", "material")
_SUPPLIER_KEYS = ("supplier_id", "supplierId", "affected_supplier_id", "affectedSupplierId", "supplier")


class ImpactScopeError(Exception):
    """起点无法解析——不是异常状况，是"这条风险没有结构化起点"这一事实。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def latest_batches(db: Session, tenant_id: str, resources: Iterable[str]) -> dict[str, dict[str, Any]]:
    """该租户各资源类型最近一次导入/同步批次。

    语义严格是"资源类型级"，**不是行级血缘**——实体表没有 source_import_job_id 列，
    本批不加列不迁移。A03 的 ``_provenance`` 与 A04 的
    ``source.batch`` 共用本函数，保证两处"数据来源"口径一字不差。
    """
    wanted = set(resources)
    if not wanted:
        return {}
    latest: dict[str, dict[str, Any]] = {}
    jobs = db.scalars(
        select(ImportJob).where(ImportJob.tenant_id == tenant_id).order_by(ImportJob.created_at.desc())
    ).all()
    for job in jobs:
        result = job.result if isinstance(job.result, dict) else {}
        reported = {
            _RESOURCE_FOR_ENTITY.get(str(report.get("type")), str(report.get("type")))
            for report in (result.get("reports") or [])
            if isinstance(report, dict)
        }
        if not reported and job.import_type in {"erp", "onboarding_demo"}:
            reported = set(wanted)  # 整批同步/演示集覆盖全部资源类型
        for resource in reported & wanted:
            if resource in latest:
                continue
            latest[resource] = {
                "resourceType": resource,
                "importJobId": job.id,
                "fileName": job.file_name,
                "source": "erp_sync" if job.import_type == "erp" else job.import_type,
                "status": job.status,
                "finishedAt": _iso(job.updated_at),
            }
    return latest


@dataclass
class _Hit:
    entity_type: str
    id: str
    name: str
    degree: str
    relation: str
    via: str
    path: list[str]
    status: dict[str, Any] | None
    fields: dict[str, Any]
    updated_at: str | None


@dataclass
class _Collector:
    """去重容器：键 (entityType, businessId) 全局唯一，degree 只降不升。"""

    hits: dict[tuple[str, str], _Hit] = field(default_factory=dict)
    truncated: dict[str, int] = field(default_factory=dict)

    def add(self, hit: _Hit) -> None:
        key = (hit.entity_type, hit.id)
        existing = self.hits.get(key)
        if existing is not None:
            # 既直接又间接命中 → direct 胜出；间接不覆盖已有的直接判定。
            if existing.degree == "direct" or hit.degree == "indirect":
                return
        counted = sum(1 for k in self.hits if k[0] == hit.entity_type)
        if existing is None and counted >= MAX_ITEMS_PER_TYPE:
            self.truncated[hit.entity_type] = self.truncated.get(hit.entity_type, 0) + 1
            return
        self.hits[key] = hit

    def ids(self, entity_type: str) -> list[str]:
        return [key[1] for key in self.hits if key[0] == entity_type]


class ImpactScopeBuilder:
    """Traverse one tenant's real C2 foreign keys, at most two hops from the seeds."""

    def __init__(self, db: Session, tenant_id: str, *, now: datetime | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.now = now or datetime.now(timezone.utc)

    # ── 入口 ────────────────────────────────────────────────────────────────

    def for_risk(self, risk: Risk) -> dict[str, Any]:
        head = {
            "kind": "risk", "id": risk.id, "code": risk.code,
            "name": risk.object_name, "status": risk.status,
        }
        try:
            materials, suppliers, seeds = self._seeds_from_risks([risk])
        except ImpactScopeError as error:
            return self._unavailable(error, head)
        incident_ids = [risk.incident_id] if risk.incident_id else []
        return self._traverse(head, materials, suppliers, seeds, incident_ids, task_degree="indirect")

    def for_incident(self, incident: Incident) -> dict[str, Any]:
        head = {
            "kind": "incident", "id": incident.id, "code": incident.code,
            "name": incident.title, "status": incident.status,
        }
        risk_ids = list(incident.source_risk_ids or [])
        risks = list(
            self.db.scalars(
                select(Risk).where(Risk.tenant_id == self.tenant_id, Risk.id.in_(risk_ids or [""]))
            ).all()
        )
        if not risks:
            return self._unavailable(
                ImpactScopeError("CG-A043", "该事件没有有效的来源风险，无法确定影响范围的起点。"), head
            )
        try:
            materials, suppliers, seeds = self._seeds_from_risks(risks)
        except ImpactScopeError as error:
            return self._unavailable(error, head)
        return self._traverse(head, materials, suppliers, seeds, [incident.id], task_degree="direct")

    # ── 起点解析（复用 C1/A03 同一套键名，不新发明） ────────────────────────

    def _seeds_from_risks(
        self, risks: list[Risk]
    ) -> tuple[list[Material], list[SupplierEntity], list[dict[str, Any]]]:
        material_ids: list[str] = []
        supplier_ids: list[str] = []
        origins: dict[str, str] = {}
        for risk in risks:
            details = risk.details if isinstance(risk.details, dict) else {}
            for key in _MATERIAL_KEYS:
                value = str(details.get(key) or "").strip()
                if value and value not in material_ids:
                    material_ids.append(value)
                    origins[f"material:{value}"] = f"risk.details.{key}"
            for key in _SUPPLIER_KEYS:
                value = str(details.get(key) or "").strip()
                if value and value not in supplier_ids:
                    supplier_ids.append(value)
                    origins[f"supplier:{value}"] = f"risk.details.{key}"

        materials = list(
            self.db.scalars(
                select(Material).where(
                    Material.tenant_id == self.tenant_id, Material.material_id.in_(material_ids or [""])
                ).order_by(Material.material_id)
            ).all()
        )
        suppliers = list(
            self.db.scalars(
                select(SupplierEntity).where(
                    SupplierEntity.tenant_id == self.tenant_id,
                    SupplierEntity.supplier_id.in_(supplier_ids or [""]),
                ).order_by(SupplierEntity.supplier_id)
            ).all()
        )
        if not materials and not suppliers:
            raise ImpactScopeError(
                "CG-2511",
                "该风险/事件没有关联到租户内的有效物料或供应商，无法确定影响范围的起点。",
            )
        seeds = [
            {"entityType": "material", "id": row.material_id,
             "name": row.material_name or row.material_id,
             "from": origins.get(f"material:{row.material_id}", "risk.details.material_id")}
            for row in materials
        ] + [
            {"entityType": "supplier", "id": row.supplier_id,
             "name": row.supplier_name or row.supplier_id,
             "from": origins.get(f"supplier:{row.supplier_id}", "risk.details.supplier_id")}
            for row in suppliers
        ]
        return materials, suppliers, seeds

    # ── 遍历主体 ────────────────────────────────────────────────────────────

    def _traverse(
        self,
        head: dict[str, Any],
        materials: list[Material],
        suppliers: list[SupplierEntity],
        seeds: list[dict[str, Any]],
        incident_ids: list[str],
        *,
        task_degree: str,
    ) -> dict[str, Any]:
        collector = _Collector()
        limitations: list[dict[str, Any]] = []
        relations: set[str] = set()
        closed_orders = 0

        seed_material_ids = {row.material_id for row in materials}

        for material in materials:
            self._add_material(collector, material, "direct", "seed_material", "materials", [])
            relations.add("seed_material")

        # 起点供应商 → 其供货物料（这些物料的展开一律记为 indirect）
        seed_supplier_materials: list[Material] = []
        for supplier in suppliers:
            self._add_supplier(collector, supplier, "direct", "seed_supplier", "suppliers", [])
            relations.add("seed_supplier")
            rows = self.db.scalars(
                select(SupplierMaterial).where(
                    SupplierMaterial.tenant_id == self.tenant_id,
                    SupplierMaterial.supplier_id == supplier.supplier_id,
                )
            ).all()
            linked = self._materials_by_id(
                [row.material_id for row in rows if row.material_id not in seed_material_ids]
            )
            for row in linked:
                self._add_material(
                    collector, row, "direct", "supplied_by_seed_supplier", "supplier_materials",
                    [f"supplier:{supplier.supplier_id}"],
                )
                relations.add("supplied_by_seed_supplier")
            seed_supplier_materials.extend(linked)

        # 起点物料展开为 direct；起点供应商带出的物料展开为 indirect。
        expansion: list[tuple[Material, str]] = (
            [(row, "direct") for row in materials] + [(row, "indirect") for row in seed_supplier_materials]
        )

        for material, degree in expansion:
            base = [f"material:{material.material_id}"]

            # 库存（真实外键 inventory.material_id）+ 由库存行聚合出的仓库
            inventory_rows = self.db.scalars(
                select(InventoryEntity).where(
                    InventoryEntity.tenant_id == self.tenant_id,
                    InventoryEntity.material_id == material.material_id,
                ).order_by(InventoryEntity.inventory_id)
            ).all()
            for row in inventory_rows:
                collector.add(_Hit(
                    entity_type="inventory", id=row.inventory_id,
                    name=row.warehouse_name or row.warehouse_id or row.inventory_id,
                    degree=degree, relation="material_inventory", via="inventory",
                    path=[*base, "inventory", f"inventory:{row.inventory_id}"],
                    status=None,
                    fields={
                        "materialId": row.material_id, "warehouseName": row.warehouse_name,
                        "onHandQty": row.on_hand_qty, "availableQty": row.available_qty,
                        "safetyStockQty": row.safety_stock_qty, "inTransitQty": row.in_transit_qty,
                        "plannedArrivalAt": _iso(row.planned_arrival_at),
                        "estimatedArrivalAt": _iso(row.estimated_arrival_at),
                    },
                    updated_at=_iso(row.updated_at),
                ))
                relations.add("material_inventory")
                warehouse_id = str(row.warehouse_id or row.warehouse_name or "").strip()
                if warehouse_id:
                    collector.add(_Hit(
                        entity_type="warehouse", id=warehouse_id,
                        name=row.warehouse_name or warehouse_id,
                        degree=degree, relation="inventory_warehouse", via="inventory",
                        path=[*base, "inventory", f"warehouse:{warehouse_id}"],
                        status=None,
                        # 仓库没有主数据表，能给的只有它在库存行里的标识本身。
                        fields={"warehouseId": row.warehouse_id, "warehouseName": row.warehouse_name},
                        updated_at=_iso(row.updated_at),
                    ))
                    relations.add("inventory_warehouse")

            # 供应商（真实外键 supplier_materials）
            links = self.db.scalars(
                select(SupplierMaterial).where(
                    SupplierMaterial.tenant_id == self.tenant_id,
                    SupplierMaterial.material_id == material.material_id,
                ).order_by(SupplierMaterial.supplier_id)
            ).all()
            supplier_rows = {
                row.supplier_id: row for row in self.db.scalars(
                    select(SupplierEntity).where(
                        SupplierEntity.tenant_id == self.tenant_id,
                        SupplierEntity.supplier_id.in_([link.supplier_id for link in links] or [""]),
                    )
                ).all()
            }
            for link in links:
                row = supplier_rows.get(link.supplier_id)
                if row is None:
                    continue
                self._add_supplier(
                    collector, row, degree, "supplies_material", "supplier_materials", base,
                    extra={
                        "qualified": link.qualified, "supplierRank": link.supplier_rank,
                        "leadTimeHours": link.lead_time_hours, "supplierPrice": link.supplier_price,
                        "availableEmergencyQty": link.available_emergency_qty,
                    },
                )
                relations.add("supplies_material")

                # 第二跳：同供应商供货的其他物料
                sibling_links = self.db.scalars(
                    select(SupplierMaterial).where(
                        SupplierMaterial.tenant_id == self.tenant_id,
                        SupplierMaterial.supplier_id == link.supplier_id,
                        SupplierMaterial.material_id != material.material_id,
                    ).order_by(SupplierMaterial.material_id)
                ).all()
                for sibling in self._materials_by_id([item.material_id for item in sibling_links]):
                    self._add_material(
                        collector, sibling, "indirect", "shared_supplier", "supplier_materials",
                        [*base, f"supplier:{link.supplier_id}"],
                    )
                    relations.add("shared_supplier")

            # 订单（真实外键 sales_order_lines.material_id），只纳入未关闭的
            lines = self.db.scalars(
                select(SalesOrderLine).where(
                    SalesOrderLine.tenant_id == self.tenant_id,
                    SalesOrderLine.material_id == material.material_id,
                ).order_by(SalesOrderLine.sales_order_id)
            ).all()
            order_rows = {
                row.sales_order_id: row for row in self.db.scalars(
                    select(SalesOrder).where(
                        SalesOrder.tenant_id == self.tenant_id,
                        SalesOrder.sales_order_id.in_([line.sales_order_id for line in lines] or [""]),
                    )
                ).all()
            }
            demand: dict[str, float] = {}
            for line in lines:
                demand[line.sales_order_id] = demand.get(line.sales_order_id, 0.0) + float(line.ordered_qty or 0)
            open_order_ids: list[str] = []
            for order_id in sorted({line.sales_order_id for line in lines}):
                row = order_rows.get(order_id)
                if row is None:
                    continue
                if str(row.order_status or "").strip().lower() in _CLOSED_ORDER_STATUSES:
                    closed_orders += 1
                    continue
                open_order_ids.append(order_id)
                collector.add(_Hit(
                    entity_type="order", id=order_id, name=order_id,
                    degree=degree, relation="order_consumes_material", via="sales_order_lines",
                    path=[*base, "sales_order_lines", f"order:{order_id}"],
                    status={"label": row.order_status or "未知", "value": row.order_status},
                    fields={
                        "customerId": row.customer_id, "orderedQty": demand.get(order_id),
                        "promisedDeliveryAt": _iso(row.promised_delivery_at),
                        "orderAmount": row.order_amount, "grossProfit": row.gross_profit,
                        "penaltyCost": row.penalty_cost,
                    },
                    updated_at=_iso(row.updated_at),
                ))
                relations.add("order_consumes_material")

            # 第二跳：订单的客户（真实外键 sales_orders.customer_id）
            customer_ids = sorted({
                order_rows[order_id].customer_id for order_id in open_order_ids
                if order_rows.get(order_id) is not None and order_rows[order_id].customer_id
            })
            customers = self.db.scalars(
                select(CustomerEntity).where(
                    CustomerEntity.tenant_id == self.tenant_id,
                    CustomerEntity.customer_id.in_(customer_ids or [""]),
                ).order_by(CustomerEntity.customer_id)
            ).all()
            by_customer = {
                order_rows[order_id].customer_id: order_id for order_id in open_order_ids
                if order_rows.get(order_id) is not None
            }
            for row in customers:
                collector.add(_Hit(
                    entity_type="customer", id=row.customer_id,
                    name=row.customer_name or row.customer_id,
                    degree="indirect", relation="order_customer", via="sales_orders",
                    path=[*base, f"order:{by_customer.get(row.customer_id, '')}",
                          f"customer:{row.customer_id}"],
                    status={"label": row.contract or "未知", "value": row.contract},
                    fields={
                        "customerLevel": row.customer_level, "region": row.region,
                        "contract": row.contract, "owner": row.owner,
                    },
                    updated_at=_iso(row.updated_at),
                ))
                relations.add("order_customer")

        # 任务（真实外键 tasks.incident_id）
        if incident_ids:
            for row in self.db.scalars(
                select(Task).where(
                    Task.tenant_id == self.tenant_id, Task.incident_id.in_(incident_ids)
                ).order_by(Task.id)
            ).all():
                collector.add(_Hit(
                    entity_type="task", id=row.id, name=row.title,
                    degree=task_degree, relation="incident_task", via="tasks",
                    path=[f"incident:{row.incident_id}", "tasks", f"task:{row.id}"],
                    status={"label": row.status, "value": row.status},
                    fields={
                        "assignee": row.assignee, "roleCode": row.role_code,
                        "priority": row.priority, "dueAt": row.due_at, "source": row.source,
                    },
                    updated_at=_iso(row.updated_at),
                ))
                relations.add("incident_task")

        if any(key[0] == "warehouse" for key in collector.hits):
            limitations.append({"code": "CG-A042", "message": LIMITATION_MESSAGES["CG-A042"]})
        if closed_orders:
            limitations.append({
                "code": "CG-A045",
                "message": f"{LIMITATION_MESSAGES['CG-A045']}本次共排除 {closed_orders} 条已关闭订单。",
                "excludedOrders": closed_orders,
            })
        for entity_type, dropped in sorted(collector.truncated.items()):
            limitations.append({
                "code": "CG-A044",
                "message": f"{GROUP_LABELS.get(entity_type, entity_type)}命中数超过 {MAX_ITEMS_PER_TYPE} 条上限，"
                           f"已截断 {dropped} 条；真实总数为 {MAX_ITEMS_PER_TYPE + dropped} 条。",
                "entityType": entity_type, "truncated": dropped,
                "total": MAX_ITEMS_PER_TYPE + dropped,
            })

        groups = self._groups(collector)
        total = sum(group["total"] for group in groups)
        seed_total = len(seeds)
        if total <= seed_total:
            # 起点解析成功但两跳内零关联：范围有限，而不是"没算出来"。
            limitations.insert(0, {"code": "CG-A041", "message": LIMITATION_MESSAGES["CG-A041"]})

        return {
            "available": True,
            "code": None,
            "message": None,
            "scopeOf": head,
            "seeds": seeds,
            "summary": {
                "total": total,
                "direct": sum(group["direct"] for group in groups),
                "indirect": sum(group["indirect"] for group in groups),
                "byType": {group["entityType"]: group["total"] for group in groups},
            },
            "groups": groups,
            "traversal": {
                "maxHops": 2,
                "relations": sorted(relations),
                "note": "所有关系均沿 C2 实体表真实外键遍历，不做字符串模糊匹配。",
            },
            "limitations": limitations,
            "generatedAt": _iso(self.now),
        }

    # ── 组装 ────────────────────────────────────────────────────────────────

    def _groups(self, collector: _Collector) -> list[dict[str, Any]]:
        resources = {
            _RESOURCE_FOR_ENTITY[key[0]] for key in collector.hits if key[0] in _RESOURCE_FOR_ENTITY
        }
        batches = latest_batches(self.db, self.tenant_id, resources)
        groups: list[dict[str, Any]] = []
        for entity_type in GROUP_ORDER:
            hits = sorted(
                (hit for hit in collector.hits.values() if hit.entity_type == entity_type),
                key=lambda hit: (hit.degree != "direct", hit.id),
            )
            items = [self._item(hit, batches) for hit in hits]
            groups.append({
                "entityType": entity_type,
                "label": GROUP_LABELS[entity_type],
                "total": len(items),
                "direct": sum(1 for hit in hits if hit.degree == "direct"),
                "indirect": sum(1 for hit in hits if hit.degree == "indirect"),
                "emptyReason": None if items else EMPTY_REASONS[entity_type],
                "items": items,
            })
        return groups

    @staticmethod
    def _item(hit: _Hit, batches: dict[str, dict[str, Any]]) -> dict[str, Any]:
        resource = _RESOURCE_FOR_ENTITY.get(hit.entity_type)
        link = ENTITY_LINKS.get(hit.entity_type)
        return {
            "entityType": hit.entity_type,
            "id": hit.id,
            "name": hit.name,
            "degree": hit.degree,
            "relation": {
                "code": hit.relation,
                "label": RELATION_LABELS[hit.relation],
                "via": hit.via,
                "path": hit.path,
            },
            "status": hit.status,
            "fields": hit.fields,
            "source": {
                "table": ENTITY_TABLES[hit.entity_type],
                "resourceType": resource,
                # 批次是资源类型级的，不是本行血缘——与 A03 同一口径、同一函数。
                "scope": "resource_type",
                "batch": batches.get(resource or "") or None,
            },
            "updatedAt": hit.updated_at,
            "link": f"{link}?id={hit.id}" if link else None,
        }

    def _add_material(
        self, collector: _Collector, material: Material, degree: str,
        relation: str, via: str, base: list[str],
    ) -> None:
        collector.add(_Hit(
            entity_type="material", id=material.material_id,
            name=material.material_name or material.material_id,
            degree=degree, relation=relation, via=via,
            path=[*base, via, f"material:{material.material_id}"] if base else [f"material:{material.material_id}"],
            status={"label": "关键物料" if material.is_critical else "普通物料",
                    "value": "critical" if material.is_critical else "normal"},
            fields={
                "category": material.category, "unit": material.unit,
                "dailyConsumption": material.daily_consumption, "unitCost": material.unit_cost,
                "isCritical": material.is_critical,
            },
            updated_at=_iso(material.updated_at),
        ))

    def _add_supplier(
        self, collector: _Collector, supplier: SupplierEntity, degree: str,
        relation: str, via: str, base: list[str], *, extra: dict[str, Any] | None = None,
    ) -> None:
        collector.add(_Hit(
            entity_type="supplier", id=supplier.supplier_id,
            name=supplier.supplier_name or supplier.supplier_id,
            degree=degree, relation=relation, via=via,
            path=[*base, via, f"supplier:{supplier.supplier_id}"] if base else [f"supplier:{supplier.supplier_id}"],
            status={"label": supplier.status or "未知", "value": supplier.status},
            fields={
                "region": supplier.region, "reliabilityScore": supplier.reliability_score,
                **(extra or {}),
            },
            updated_at=_iso(supplier.updated_at),
        ))

    def _materials_by_id(self, material_ids: list[str]) -> list[Material]:
        if not material_ids:
            return []
        return list(
            self.db.scalars(
                select(Material).where(
                    Material.tenant_id == self.tenant_id, Material.material_id.in_(material_ids)
                ).order_by(Material.material_id)
            ).all()
        )

    @staticmethod
    def _unavailable(error: ImpactScopeError, head: dict[str, Any]) -> dict[str, Any]:
        """可渲染的限制说明，绝不是一份编造的影响范围。响应里不含任何实体名与计数。"""
        return {
            "available": False,
            "code": error.code,
            "message": error.message,
            "scopeOf": head,
            "seeds": [],
            "summary": {"total": 0, "direct": 0, "indirect": 0, "byType": {}},
            "groups": [],
            "traversal": {"maxHops": 2, "relations": [], "note": None},
            "limitations": [{"code": error.code, "message": error.message}],
            "generatedAt": None,
        }


def risk_impact_scope(
    db: Session, tenant_id: str, risk: Risk, permissions: tuple[str, ...]
) -> dict[str, Any]:
    """One risk's impact scope, then through the existing field-masking path."""
    payload = ImpactScopeBuilder(db, tenant_id).for_risk(risk)
    return mask_for_requester(payload, permissions)


def incident_impact_scope(
    db: Session, tenant_id: str, incident: Incident, permissions: tuple[str, ...]
) -> dict[str, Any]:
    """One incident's impact scope, then through the existing field-masking path."""
    payload = ImpactScopeBuilder(db, tenant_id).for_incident(incident)
    return mask_for_requester(payload, permissions)
