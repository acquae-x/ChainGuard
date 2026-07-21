"""C02/C03 供应链节点健康：租户当前 C2 实体数据下，四类节点各自处于什么状态、为什么。

四条硬约束（codex_landing_spec/phase5b_c02_c03_实现范围.md）：
- **只有物料节点是引擎算出来的**。物料健康严格走 ``calculate_inventory_risk`` →
  ``measure_material``，阈值经 ``TenantContextBuilder`` 解析，与 A03 解释、C1 决策链路同源。
  仓库/供应商/订单**没有评分模型**，本批也不新写——给它们编一套加权分就是新算法，越界。
  它们的健康只由两种东西得出：实体行上的**事实判据**，以及从物料节点的**传播**，
  且每条都在 ``reasons[]`` 里标明是哪一种（传播型带 ``derivedFrom``）。
- **不给健康分数**。四档（异常/预警/健康/数据不足）是分类结论，不是数字。
- **数据不足就说数据不足**。``unknown`` 单独计数，绝不并入 healthy；算不了的物料
  如实带上 ``ContextBuildError`` 的原始 code 与 message。
- **不调用 LLM**。状态标签、原因标签、原因文案模板都是固定中文常量，数字由代码填。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.inventory_monitor import calculate_inventory_risk

from .context_builder import _CLOSED_ORDER_STATUSES, ContextBuildError, TenantContextBuilder
from .decision_detail import mask_for_requester
from .impact_scope import latest_batches
from .models import (
    CustomerEntity,
    InventoryEntity,
    Material,
    Risk,
    SalesOrder,
    SalesOrderLine,
    SupplierEntity,
    SupplierMaterial,
)
from .risk_recompute import measure_material, risk_id_for_material

# 单类节点上限。超出即截断并明示真实总数——11 万条企业数据下不能一次全算。
MAX_NODES_PER_TYPE = 500

# 节点类型固定顺序。没有节点的类型**仍然出现**且 total=0：
# "暂无数据"必须是显式的，不能靠类型消失来暗示。
NODE_TYPE_ORDER = ("material", "warehouse", "supplier", "order")

NODE_TYPE_LABELS = {
    "material": "物料", "warehouse": "仓库", "supplier": "供应商", "order": "订单",
}

# 健康四档固定顺序；unknown 不是第四种健康程度，是"这个节点算不了"。
HEALTH_ORDER = ("critical", "warning", "healthy", "unknown")

HEALTH_LABELS = {
    "critical": "异常", "warning": "预警", "healthy": "健康", "unknown": "数据不足",
}

# 引擎自身的三档预警 → 节点健康。此处不引入新阈值：warning_level 完全由
# config/thresholds.yaml 的 red/yellow_support_hours（或租户获批配置）决定。
_HEALTH_BY_WARNING = {"红色预警": "critical", "黄色预警": "warning", "正常": "healthy"}

# 供应商中断状态词表：固定常量，与 context_builder._CLOSED_ORDER_STATUSES 同类，
# 是**状态词表**不是评分。词表外的自定义状态词会被判为 healthy（已知限制 6）。
DISRUPTED_SUPPLIER_STATUSES = {
    "停产", "停供", "中断", "暂停", "受事件影响", "已终止",
    "suspended", "stopped", "disrupted", "terminated",
}

REASON_LABELS = {
    "support_hours_below_red": "库存支撑低于红线",
    "support_hours_below_yellow": "库存支撑低于黄线",
    "risk_index_above_trigger": "库存风险指数超过触发阈值",
    "safety_stock_gap": "安全库存存在缺口",
    "transit_delay": "在途到货延误",
    "critical_order_uncovered": "关键订单未被完全覆盖",
    "material_not_computable": "该物料数据不足，无法计算库存风险",
    "inventory_below_safety_stock": "库存可用量低于安全库存",
    "hosts_critical_material": "存放的物料处于异常",
    "hosts_warning_material": "存放的物料处于预警",
    "insufficient_inventory_fields": "库存行缺少可用量与安全库存，无法判定",
    "supplier_status_disrupted": "供应商状态为中断类",
    "no_qualified_material": "该供应商没有任何合格供货物料",
    "supplies_critical_material": "供货的物料处于异常",
    "supplies_warning_material": "供货的物料处于预警",
    "insufficient_supplier_fields": "供应商缺少状态与供货记录，无法判定",
    "delivery_overdue": "承诺交期已过",
    "requires_critical_material": "所需物料处于异常",
    "requires_warning_material": "所需物料处于预警",
    "insufficient_order_fields": "订单缺少行项目与承诺交期，无法判定",
}

ENTITY_LINKS = {
    "material": "/data/material", "supplier": "/data/supplier", "order": "/data/order",
}

# 承载每类节点的真实表名，写进 source.table 供核对。
NODE_TABLES = {
    "material": "materials", "warehouse": "inventory",
    "supplier": "suppliers", "order": "sales_orders",
}

_RESOURCE_FOR_NODE = {
    "material": "material", "warehouse": "inventory",
    "supplier": "supplier", "order": "order",
}

EMPTY_REASONS = {
    "material": "当前租户还没有物料主数据",
    "warehouse": "当前租户还没有库存记录，因而无法聚合出仓库",
    "supplier": "当前租户还没有供应商主数据",
    "order": "当前租户还没有未关闭的销售订单",
}

LIMITATION_MESSAGES = {
    "CG-C021": "当前租户还没有任何业务实体数据（物料/库存/供应商/订单全空），"
               "节点健康无法计算；请先完成数据导入。",
    "CG-C022": "部分物料因日消耗量或库存记录缺失而无法计算库存风险，已计入「数据不足」。",
    "CG-C023": "系统没有独立的仓库主数据，仓库节点由库存行的仓库字段聚合得出，因此没有资料页可跳转。",
    "CG-C024": "只有物料节点的健康由库存风险引擎计算；仓库/供应商/订单的健康来自实体行上的"
               "事实判据与物料节点的传播，不是独立评分模型——系统没有它们的阈值配置，本批不发明。",
    "CG-C025": "单类节点数超过上限，明细已截断。",
    "CG-C026": "已关闭的销售订单不计入节点健康。",
    "CG-C027": "部分库存行没有仓库标识，未能归入任何仓库节点。",
    "CG-C031": "当前角色没有直接负责的节点类型；请在工作台的「供应链节点健康」概览查看全局。",
    "CG-C032": "当前角色负责的节点类型下暂无数据。",
}

# ── 角色数据范围：全部复用既有权限码，本模块不新增任何权限码 ──────────────────
# 与 auth.security.can_view_data 同族口径：全域权限看全部，专责权限看对口类型。
_GLOBAL_SCOPE_PERMISSIONS = {"*", "data:view", "data:manage", "settings:manage"}
_SCOPE_BY_PERMISSION = {
    "data:inventory:manage": "warehouse",
    "risk:manage:warehouse": "warehouse",
    "data:supplier:manage": "supplier",
    "data:material:manage": "material",
    "risk:manage:material": "material",
    "data:order:manage": "order",
    "data:customer:manage": "order",
    "risk:manage:order": "order",
}


def scope_for(permissions: tuple[str, ...]) -> tuple[list[str], bool]:
    """按既有权限码派生「我的节点」范围。返回 (节点类型列表, 是否全域)。"""
    perms = set(permissions)
    if perms & _GLOBAL_SCOPE_PERMISSIONS:
        return list(NODE_TYPE_ORDER), True
    matched = {_SCOPE_BY_PERMISSION[code] for code in perms if code in _SCOPE_BY_PERMISSION}
    return [name for name in NODE_TYPE_ORDER if name in matched], False


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _worst(*states: str) -> str:
    """健康只降不升：critical > warning > healthy > unknown（unknown 最弱，不掩盖已知结论）。"""
    for level in ("critical", "warning", "healthy"):
        if level in states:
            return level
    return "unknown"


def _round(value: Any, digits: int = 2) -> Any:
    return round(float(value), digits) if isinstance(value, (int, float)) else value


def _reason(
    code: str,
    *,
    detail: str,
    observed: dict[str, Any] | None = None,
    threshold: dict[str, Any] | None = None,
    via: str,
    derived_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """一条异常原因。文案是固定模板 + 真实数字，不经 LLM。"""
    return {
        "code": code,
        "label": REASON_LABELS.get(code, code),
        "detail": detail,
        "observed": observed,
        "threshold": threshold,
        "via": via,
        "derivedFrom": derived_from,
    }


@dataclass
class _Node:
    node_type: str
    id: str
    name: str
    health: str
    reasons: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    updated_at: str | None = None
    link: str | None = None
    related_links: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, batch: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "nodeType": self.node_type,
            "id": self.id,
            "name": self.name,
            "health": self.health,
            "healthLabel": HEALTH_LABELS[self.health],
            "reasons": self.reasons,
            "metrics": self.metrics,
            "source": {"table": NODE_TABLES[self.node_type], "batch": batch},
            "updatedAt": self.updated_at,
            "link": self.link,
            "relatedLinks": self.related_links,
        }


class NodeHealthBuilder:
    """Compute one tenant's supply-chain node health from that tenant's C2 entities only."""

    def __init__(self, db: Session, tenant_id: str, *, now: datetime | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.now = now or datetime.now(timezone.utc)
        self.builder = TenantContextBuilder(db, tenant_id, now=self.now)
        self._limitations: dict[str, dict[str, Any]] = {}

    # ── 入口 ────────────────────────────────────────────────────────────────

    def build(
        self,
        *,
        node_types: list[str] | None = None,
        health: str | None = None,
        keyword: str | None = None,
        current: int = 1,
        page_size: int = 20,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 空列表与 None 语义不同：None 是"没指定，给全部"，[] 是"这个角色一类都不负责"。
        requested = set(NODE_TYPE_ORDER if node_types is None else node_types)
        wanted = [name for name in NODE_TYPE_ORDER if name in requested]
        if not wanted:
            return self._unavailable("CG-C031", scope=scope)

        materials = self._material_nodes()
        buckets: dict[str, list[_Node]] = {
            "material": materials,
            "warehouse": self._warehouse_nodes(materials),
            "supplier": self._supplier_nodes(materials),
            "order": self._order_nodes(materials),
        }
        counted = {name: buckets[name] for name in wanted}

        if not any(counted.values()) and not self._tenant_has_entities():
            return self._unavailable("CG-C021", scope=scope)
        if not any(counted.values()):
            self._limit("CG-C032")

        if any(name != "material" and rows for name, rows in counted.items()):
            self._limit("CG-C024")

        batches = latest_batches(
            self.db, self.tenant_id, {_RESOURCE_FOR_NODE[name] for name in wanted}
        )
        rendered: list[dict[str, Any]] = []
        by_type: list[dict[str, Any]] = []
        summary = {level: 0 for level in HEALTH_ORDER}
        for name in wanted:
            rows = counted[name]
            entry = {
                "nodeType": name,
                "label": NODE_TYPE_LABELS[name],
                "total": len(rows),
                **{level: sum(1 for row in rows if row.health == level) for level in HEALTH_ORDER},
            }
            if not rows:
                entry["emptyReason"] = EMPTY_REASONS[name]
            by_type.append(entry)
            for level in HEALTH_ORDER:
                summary[level] += entry[level]
            batch = batches.get(_RESOURCE_FOR_NODE[name])
            rendered.extend(row.to_dict(batch) for row in rows)

        filtered = self._filter(rendered, health, keyword)
        start = max(int(current) - 1, 0) * int(page_size)
        return {
            "available": True,
            "code": None,
            "scope": scope,
            "summary": {**summary, "total": sum(summary.values())},
            "byType": by_type,
            "nodes": filtered[start:start + int(page_size)],
            "filtered": {
                "total": len(filtered), "current": int(current), "pageSize": int(page_size),
                "nodeTypes": wanted, "health": health, "keyword": keyword or None,
            },
            "filters": {
                "nodeTypes": [
                    {"value": name, "label": NODE_TYPE_LABELS[name]} for name in wanted
                ],
                "healthStates": [
                    {"value": level, "label": HEALTH_LABELS[level]} for level in HEALTH_ORDER
                ],
            },
            "dataFreshness": {
                "scope": "resource_type",
                "note": "最近一次导入批次（非本行血缘）",
                "batches": [batches[key] for key in sorted(batches)],
                "latestNodeUpdatedAt": max(
                    [row["updatedAt"] for row in rendered if row["updatedAt"]] or [None],
                    default=None,
                ),
            },
            "limitations": [self._limitations[key] for key in sorted(self._limitations)],
            "generatedAt": _iso(self.now),
        }

    def _unavailable(self, code: str, *, scope: dict[str, Any] | None) -> dict[str, Any]:
        """可渲染的限制说明，绝不附带任何编造的计数或节点。"""
        self._limit(code)
        return {
            "available": False,
            "code": code,
            "message": LIMITATION_MESSAGES[code],
            "scope": scope,
            "summary": None,
            "byType": [],
            "nodes": [],
            "filtered": None,
            "filters": None,
            "dataFreshness": None,
            "limitations": [self._limitations[key] for key in sorted(self._limitations)],
            "generatedAt": _iso(self.now),
        }

    def _limit(self, code: str, **extra: Any) -> None:
        self._limitations[code] = {
            "code": code, "message": LIMITATION_MESSAGES[code], **extra
        }

    @staticmethod
    def _filter(
        rows: list[dict[str, Any]], health: str | None, keyword: str | None
    ) -> list[dict[str, Any]]:
        text = (keyword or "").strip().lower()
        return [
            row for row in rows
            if (not health or row["health"] == health)
            and (not text or text in str(row["id"]).lower() or text in str(row["name"]).lower())
        ]

    def _tenant_has_entities(self) -> bool:
        for model in (Material, InventoryEntity, SupplierEntity, SalesOrder):
            if self.db.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == self.tenant_id)
            ):
                return True
        return False

    def _truncate(self, node_type: str, total: int) -> None:
        if total > MAX_NODES_PER_TYPE:
            existing = self._limitations.get("CG-C025", {}).get("truncated", {})
            self._limit("CG-C025", truncated={**existing, node_type: {
                "shown": MAX_NODES_PER_TYPE, "actualTotal": total,
            }})

    # ── 物料节点：唯一由引擎算出的一类 ──────────────────────────────────────

    def _material_nodes(self) -> list[_Node]:
        total = int(self.db.scalar(
            select(func.count()).select_from(Material).where(Material.tenant_id == self.tenant_id)
        ) or 0)
        self._truncate("material", total)
        materials = list(self.db.scalars(
            select(Material)
            .where(Material.tenant_id == self.tenant_id)
            .order_by(Material.material_id)
            .limit(MAX_NODES_PER_TYPE)
        ).all())

        nodes: list[_Node] = []
        skipped = 0
        for material in materials:
            try:
                snapshot = self.builder.build_material_snapshot(material)
            except ContextBuildError as error:
                skipped += 1
                nodes.append(_Node(
                    node_type="material",
                    id=material.material_id,
                    name=material.material_name or material.material_id,
                    health="unknown",
                    reasons=[_reason(
                        "material_not_computable",
                        detail=f"{error.message}（{error.code}）",
                        via="materials",
                    )],
                    metrics={
                        "dailyConsumption": material.daily_consumption,
                        "unit": material.unit,
                        "isCritical": material.is_critical,
                    },
                    updated_at=_iso(material.updated_at),
                    link=f"{ENTITY_LINKS['material']}?id={material.material_id}",
                    related_links=self._material_related_links(material.material_id),
                ))
                continue

            result = calculate_inventory_risk(
                snapshot.inventory, snapshot.risk_weights, snapshot.thresholds
            )
            measurement = measure_material(result, snapshot)
            nodes.append(_Node(
                node_type="material",
                id=material.material_id,
                name=material.material_name or material.material_id,
                health=_HEALTH_BY_WARNING.get(str(measurement["warningLevel"]), "unknown"),
                reasons=self._material_reasons(measurement, snapshot.configuration["source"]),
                metrics={
                    "warningLevel": measurement["warningLevel"],
                    "riskIndex": measurement["riskIndex"],
                    "supportHours": _round(measurement["supportHours"]),
                    "currentStock": measurement["inputs"]["currentStock"],
                    "safetyStock": measurement["inputs"]["safetyStock"],
                    "inTransitQty": measurement["inputs"]["inTransitQty"],
                    "dailyConsumption": material.daily_consumption,
                    "unit": material.unit,
                    "isCritical": material.is_critical,
                    "dataQuality": measurement["dataQuality"],
                },
                updated_at=_iso(material.updated_at),
                link=f"{ENTITY_LINKS['material']}?id={material.material_id}",
                related_links=self._material_related_links(material.material_id),
            ))
        if skipped:
            self._limit("CG-C022", affectedCount=skipped)
        return nodes

    @staticmethod
    def _material_reasons(measurement: dict[str, Any], threshold_source: str) -> list[dict[str, Any]]:
        """全部是 measurement 里已有数字与已有阈值的直接对照，不引入任何新阈值。"""
        thresholds = measurement["thresholds"]
        support = float(measurement["supportHours"])
        reasons: list[dict[str, Any]] = []

        def source(value: Any, unit: str) -> dict[str, Any]:
            return {"value": value, "unit": unit, "source": threshold_source}

        if support < float(thresholds["redSupportHours"]):
            reasons.append(_reason(
                "support_hours_below_red",
                detail=f"库存支撑 {support:.1f} 小时，低于红线 {thresholds['redSupportHours']} 小时",
                observed={"field": "库存支撑小时数", "value": _round(support), "unit": "hour"},
                threshold=source(thresholds["redSupportHours"], "hour"),
                via="inventory",
            ))
        elif support < float(thresholds["yellowSupportHours"]):
            reasons.append(_reason(
                "support_hours_below_yellow",
                detail=f"库存支撑 {support:.1f} 小时，低于黄线 {thresholds['yellowSupportHours']} 小时",
                observed={"field": "库存支撑小时数", "value": _round(support), "unit": "hour"},
                threshold=source(thresholds["yellowSupportHours"], "hour"),
                via="inventory",
            ))
        if float(measurement["riskIndex"]) >= float(measurement["triggerThreshold"]):
            reasons.append(_reason(
                "risk_index_above_trigger",
                detail=f"库存风险指数 {measurement['riskIndex']}，不低于触发阈值 "
                       f"{measurement['triggerThreshold']}",
                observed={"field": "库存风险指数", "value": measurement["riskIndex"], "unit": "score"},
                threshold=source(measurement["triggerThreshold"], "score"),
                via="inventory",
            ))
        if float(measurement["safetyStockGap"] or 0) > 0:
            reasons.append(_reason(
                "safety_stock_gap",
                detail=f"安全库存缺口 {_round(measurement['safetyStockGap'])}",
                observed={"field": "安全库存缺口", "value": _round(measurement["safetyStockGap"]),
                          "unit": "quantity"},
                threshold=None,
                via="inventory",
            ))
        if float(measurement["transitDelayHours"] or 0) > 0:
            reasons.append(_reason(
                "transit_delay",
                detail=f"在途到货较计划延误 {_round(measurement['transitDelayHours'])} 小时",
                observed={"field": "在途延误小时", "value": _round(measurement["transitDelayHours"]),
                          "unit": "hour"},
                threshold=None,
                via="inventory",
            ))
        coverage = float(measurement["criticalOrderCoverageRate"] or 0)
        if coverage < 1:
            reasons.append(_reason(
                "critical_order_uncovered",
                detail=f"关键订单覆盖率 {coverage:.0%}，未被现有库存完全覆盖",
                observed={"field": "关键订单覆盖率", "value": _round(coverage, 4), "unit": "ratio"},
                threshold=None,
                via="sales_order_lines",
            ))
        return reasons

    def _material_related_links(self, material_id: str) -> list[dict[str, Any]]:
        """只在真实存在对应业务对象时给链接，绝不给假链接。"""
        risk = self.db.get(Risk, risk_id_for_material(self.tenant_id, material_id))
        if risk is None or risk.tenant_id != self.tenant_id or risk.status == "resolved":
            return []
        if risk.incident_id:
            return [{"label": "查看关联事件", "link": f"/incident/{risk.incident_id}"}]
        return [{"label": "查看风险列表", "link": "/risk/list"}]

    # ── 仓库节点：库存行聚合 + 事实判据 + 物料传播 ──────────────────────────

    def _warehouse_nodes(self, materials: list[_Node]) -> list[_Node]:
        health_by_material = {node.id: node for node in materials}
        rows = list(self.db.scalars(
            select(InventoryEntity)
            .where(InventoryEntity.tenant_id == self.tenant_id)
            .order_by(InventoryEntity.warehouse_id, InventoryEntity.inventory_id)
        ).all())
        if rows:
            self._limit("CG-C023")

        grouped: dict[str, list[InventoryEntity]] = {}
        unassigned = 0
        for row in rows:
            key = str(row.warehouse_id or "").strip()
            if not key:
                unassigned += 1
                continue
            grouped.setdefault(key, []).append(row)
        if unassigned:
            self._limit("CG-C027", affectedRows=unassigned)
        self._truncate("warehouse", len(grouped))

        nodes: list[_Node] = []
        for warehouse_id in sorted(grouped)[:MAX_NODES_PER_TYPE]:
            entries = grouped[warehouse_id]
            reasons: list[dict[str, Any]] = []
            states: list[str] = []

            below = [
                row for row in entries
                if row.available_qty is not None and row.safety_stock_qty is not None
                and float(row.available_qty) < float(row.safety_stock_qty)
            ]
            for row in below:
                reasons.append(_reason(
                    "inventory_below_safety_stock",
                    detail=f"库存行 {row.inventory_id}（{row.material_id}）可用量 "
                           f"{_round(row.available_qty)} 低于安全库存 {_round(row.safety_stock_qty)}",
                    observed={"field": "可用量", "value": _round(row.available_qty), "unit": "quantity"},
                    threshold={"value": _round(row.safety_stock_qty), "unit": "quantity",
                               "source": "inventory.safety_stock_qty"},
                    via="inventory",
                ))
            if below:
                states.append("critical")

            hosted = sorted({str(row.material_id) for row in entries})
            reasons.extend(self._propagated(
                hosted, health_by_material, "hosts_critical_material", "hosts_warning_material",
                via="inventory", verb="存放",
            ))
            states.extend(
                health_by_material[mid].health for mid in hosted
                if mid in health_by_material and health_by_material[mid].health in {"critical", "warning"}
            )

            measurable = any(
                row.available_qty is not None or row.safety_stock_qty is not None for row in entries
            )
            known_materials = [
                mid for mid in hosted
                if mid in health_by_material and health_by_material[mid].health != "unknown"
            ]
            if not measurable and not known_materials:
                health = "unknown"
                reasons.append(_reason(
                    "insufficient_inventory_fields",
                    detail="该仓库的库存行均缺少可用量与安全库存，且其物料均无法计算，无法判定健康状态",
                    via="inventory",
                ))
            else:
                health = _worst(*states) if states else "healthy"

            nodes.append(_Node(
                node_type="warehouse",
                id=warehouse_id,
                name=next((row.warehouse_name for row in entries if row.warehouse_name), warehouse_id),
                health=health,
                reasons=reasons,
                metrics={
                    "inventoryRowCount": len(entries),
                    "materialCount": len(hosted),
                    "onHandQty": sum(float(row.on_hand_qty or 0) for row in entries),
                    "availableQty": sum(float(row.available_qty or 0) for row in entries),
                    "safetyStockQty": sum(float(row.safety_stock_qty or 0) for row in entries),
                    "inTransitQty": sum(float(row.in_transit_qty or 0) for row in entries),
                },
                # 仓库没有主数据，因而没有资料页；给 null 而不是一个点不开的假链接。
                updated_at=max([_iso(row.updated_at) or "" for row in entries] or [""]) or None,
                link=None,
                related_links=[{"label": "查看库存明细", "link": "/data/inventory"}],
            ))
        return nodes

    # ── 供应商节点：状态词表 + 合格供货 + 物料传播 ──────────────────────────

    def _supplier_nodes(self, materials: list[_Node]) -> list[_Node]:
        health_by_material = {node.id: node for node in materials}
        total = int(self.db.scalar(
            select(func.count()).select_from(SupplierEntity)
            .where(SupplierEntity.tenant_id == self.tenant_id)
        ) or 0)
        self._truncate("supplier", total)
        suppliers = list(self.db.scalars(
            select(SupplierEntity)
            .where(SupplierEntity.tenant_id == self.tenant_id)
            .order_by(SupplierEntity.supplier_id)
            .limit(MAX_NODES_PER_TYPE)
        ).all())

        relations: dict[str, list[SupplierMaterial]] = {}
        for row in self.db.scalars(
            select(SupplierMaterial).where(SupplierMaterial.tenant_id == self.tenant_id)
        ).all():
            relations.setdefault(str(row.supplier_id), []).append(row)

        nodes: list[_Node] = []
        for supplier in suppliers:
            supplied = relations.get(supplier.supplier_id, [])
            reasons: list[dict[str, Any]] = []
            states: list[str] = []
            status = str(supplier.status or "").strip()

            if status and status.lower() in {item.lower() for item in DISRUPTED_SUPPLIER_STATUSES}:
                states.append("critical")
                reasons.append(_reason(
                    "supplier_status_disrupted",
                    detail=f"供应商当前状态为「{status}」，属中断类状态",
                    observed={"field": "供应商状态", "value": status, "unit": None},
                    threshold={"value": sorted(DISRUPTED_SUPPLIER_STATUSES), "unit": None,
                               "source": "中断状态词表（固定常量）"},
                    via="suppliers",
                ))
            if supplied and not any(row.qualified for row in supplied):
                states.append("critical")
                reasons.append(_reason(
                    "no_qualified_material",
                    detail=f"该供应商的 {len(supplied)} 条供货记录全部为不合格",
                    observed={"field": "合格供货记录数", "value": 0, "unit": "count"},
                    threshold=None,
                    via="supplier_materials",
                ))

            qualified_materials = sorted({
                str(row.material_id) for row in supplied if row.qualified
            })
            reasons.extend(self._propagated(
                qualified_materials, health_by_material,
                "supplies_critical_material", "supplies_warning_material",
                via="supplier_materials", verb="供货",
            ))
            # 传播最多把供应商拉到 warning——"我供的料缺货"不等于"这家供应商自己出事了"，
            # 把它判成 critical 就是在替用户下一个数据支持不了的结论。
            if any(
                health_by_material.get(mid) is not None
                and health_by_material[mid].health in {"critical", "warning"}
                for mid in qualified_materials
            ):
                states.append("warning")

            if not status and not supplied:
                health = "unknown"
                reasons.append(_reason(
                    "insufficient_supplier_fields",
                    detail="该供应商既没有状态字段，也没有任何供货记录，无法判定健康状态",
                    via="suppliers",
                ))
            else:
                health = _worst(*states) if states else "healthy"

            nodes.append(_Node(
                node_type="supplier",
                id=supplier.supplier_id,
                name=supplier.supplier_name or supplier.supplier_id,
                health=health,
                reasons=reasons,
                metrics={
                    "status": supplier.status,
                    "region": supplier.region,
                    # 无阈值配置，仅作原值展示，不参与健康判定（已知限制 3）。
                    "reliabilityScore": supplier.reliability_score,
                    "materialCount": len(supplied),
                    "qualifiedMaterialCount": len(qualified_materials),
                    "supplierPrice": min(
                        [float(row.supplier_price) for row in supplied if row.supplier_price is not None]
                        or [0.0]
                    ) if any(row.supplier_price is not None for row in supplied) else None,
                },
                updated_at=_iso(supplier.updated_at),
                link=f"{ENTITY_LINKS['supplier']}?id={supplier.supplier_id}",
                related_links=[],
            ))
        return nodes

    # ── 订单节点：未关闭订单 + 逾期事实 + 物料传播 ──────────────────────────

    def _order_nodes(self, materials: list[_Node]) -> list[_Node]:
        health_by_material = {node.id: node for node in materials}
        open_filter = (
            SalesOrder.tenant_id == self.tenant_id,
            func.lower(func.coalesce(SalesOrder.order_status, "")).not_in(_CLOSED_ORDER_STATUSES),
        )
        total_all = int(self.db.scalar(
            select(func.count()).select_from(SalesOrder).where(SalesOrder.tenant_id == self.tenant_id)
        ) or 0)
        total_open = int(self.db.scalar(
            select(func.count()).select_from(SalesOrder).where(*open_filter)
        ) or 0)
        if total_all > total_open:
            self._limit("CG-C026", excludedCount=total_all - total_open)
        self._truncate("order", total_open)

        orders = list(self.db.scalars(
            select(SalesOrder).where(*open_filter)
            .order_by(SalesOrder.sales_order_id).limit(MAX_NODES_PER_TYPE)
        ).all())
        if not orders:
            return []

        order_ids = [order.sales_order_id for order in orders]
        lines: dict[str, list[SalesOrderLine]] = {}
        for row in self.db.scalars(
            select(SalesOrderLine).where(
                SalesOrderLine.tenant_id == self.tenant_id,
                SalesOrderLine.sales_order_id.in_(order_ids),
            )
        ).all():
            lines.setdefault(str(row.sales_order_id), []).append(row)
        customers = {
            row.customer_id: row
            for row in self.db.scalars(
                select(CustomerEntity).where(
                    CustomerEntity.tenant_id == self.tenant_id,
                    CustomerEntity.customer_id.in_([order.customer_id for order in orders] or [""]),
                )
            ).all()
        }

        nodes: list[_Node] = []
        for order in orders:
            entries = lines.get(order.sales_order_id, [])
            customer = customers.get(order.customer_id)
            reasons: list[dict[str, Any]] = []
            states: list[str] = []

            promised = order.promised_delivery_at
            promised = promised if promised is None or promised.tzinfo else promised.replace(tzinfo=timezone.utc)
            if promised is not None and promised < self.now:
                states.append("critical")
                reasons.append(_reason(
                    "delivery_overdue",
                    detail=f"承诺交期 {_iso(promised)} 已过（当前 {_iso(self.now)}）",
                    observed={"field": "承诺交期", "value": _iso(promised), "unit": None},
                    # 纯事实比较，不引入"提前多少小时算临近"这类阈值。
                    threshold={"value": _iso(self.now), "unit": None, "source": "当前时间（事实比较）"},
                    via="sales_orders",
                ))

            required = sorted({str(row.material_id) for row in entries})
            reasons.extend(self._propagated(
                required, health_by_material,
                "requires_critical_material", "requires_warning_material",
                via="sales_order_lines", verb="需要",
            ))
            states.extend(
                health_by_material[mid].health for mid in required
                if mid in health_by_material and health_by_material[mid].health in {"critical", "warning"}
            )

            if not entries and promised is None:
                health = "unknown"
                reasons.append(_reason(
                    "insufficient_order_fields",
                    detail="该订单既没有行项目也没有承诺交期，无法判定健康状态",
                    via="sales_orders",
                ))
            else:
                health = _worst(*states) if states else "healthy"

            nodes.append(_Node(
                node_type="order",
                id=order.sales_order_id,
                name=f"{order.sales_order_id}"
                     + (f"（{customer.customer_name}）" if customer and customer.customer_name else ""),
                health=health,
                reasons=reasons,
                metrics={
                    "orderStatus": order.order_status,
                    "promisedDeliveryAt": _iso(promised),
                    "lineCount": len(entries),
                    "materialCount": len(required),
                    "orderedQty": sum(float(row.ordered_qty or 0) for row in entries),
                    "customerName": customer.customer_name if customer else None,
                    "customerLevel": customer.customer_level if customer else None,
                    "orderAmount": order.order_amount,
                    "grossProfit": order.gross_profit,
                    "penaltyCost": order.penalty_cost,
                },
                updated_at=_iso(order.updated_at),
                link=f"{ENTITY_LINKS['order']}?id={order.sales_order_id}",
                related_links=(
                    [{"label": "查看客户", "link": f"/data/customer?id={order.customer_id}"}]
                    if customer else []
                ),
            ))
        return nodes

    # ── 传播：非物料节点的健康有多少来自物料，必须逐条写明 ──────────────────

    @staticmethod
    def _propagated(
        material_ids: list[str],
        health_by_material: dict[str, _Node],
        critical_code: str,
        warning_code: str,
        *,
        via: str,
        verb: str,
    ) -> list[dict[str, Any]]:
        reasons: list[dict[str, Any]] = []
        for code, level in ((critical_code, "critical"), (warning_code, "warning")):
            for material_id in material_ids:
                node = health_by_material.get(material_id)
                if node is None or node.health != level:
                    continue
                reasons.append(_reason(
                    code,
                    detail=f"{verb}的物料「{node.name}」当前为{HEALTH_LABELS[level]}",
                    observed={"field": "关联物料健康", "value": HEALTH_LABELS[level], "unit": None},
                    threshold=None,
                    via=via,
                    derived_from={
                        "nodeType": "material", "id": node.id, "name": node.name,
                        "health": node.health,
                        "link": f"{ENTITY_LINKS['material']}?id={node.id}",
                    },
                ))
        return reasons


def node_health_overview(
    db: Session,
    tenant_id: str,
    permissions: tuple[str, ...],
    **kwargs: Any,
) -> dict[str, Any]:
    """管理者概览：全部四类节点，出口过既有字段脱敏路径。"""
    payload = NodeHealthBuilder(db, tenant_id).build(**kwargs)
    return mask_for_requester(payload, permissions)


def my_nodes(
    db: Session,
    tenant_id: str,
    permissions: tuple[str, ...],
    **kwargs: Any,
) -> dict[str, Any]:
    """一线「我的节点」：范围由既有权限码派生，不新增权限码。"""
    types, is_global = scope_for(permissions)
    scope = {
        "nodeTypes": types,
        "isGlobal": is_global,
        "matched": bool(types),
        "basis": "既有权限码（data:*:manage / risk:manage:*），未新增权限码",
    }
    payload = NodeHealthBuilder(db, tenant_id).build(node_types=types, scope=scope, **kwargs)
    return mask_for_requester(payload, permissions)
