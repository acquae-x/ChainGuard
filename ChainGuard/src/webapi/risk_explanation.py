"""A03 实时风险解释：为一条真实风险回答"为什么现在是这个等级、由哪些数据触发"。

三条硬约束：
- **不调用 LLM**。叙述直接取 ``calculate_inventory_risk`` 返回的 explanation[]，
  其余全是结构化字段，数值一律由代码算出。
- **不新写评分公式**。阈值/权重经 ``TenantContextBuilder`` 解析，与 C1 决策链路同源。
- **数据不足时如实降级**。宁可返回可渲染的限制说明，也不编造一个说得通的解释。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.inventory_monitor import calculate_inventory_risk

from .context_builder import ContextBuildError, MaterialSnapshot, TenantContextBuilder
from .decision_detail import mask_for_requester
from .impact_scope import latest_batches
from .models import Material, Risk, SalesOrder, SupplierEntity
from .risk_recompute import EXTERNAL_ORIGIN, measure_material

# 风险已消除/已忽略：展示消除当时的快照，并明确标注为快照。
CLOSED_STATUSES = {"resolved": "风险已消除", "ignored": "风险已忽略"}

DRIVER_META = {
    "shortage_urgency": {"label": "缺货紧迫度", "metric": "库存支撑小时数", "unit": "hour"},
    "order_importance": {"label": "关键订单覆盖", "metric": "关键订单覆盖率", "unit": "ratio"},
    "transit_delay": {"label": "在途延误", "metric": "在途预计延误小时", "unit": "hour"},
    "external_event": {"label": "外部事件", "metric": "外部事件风险分", "unit": "score"},
}

# 解释里用到的实体 → 前端资料页路由，供证据卡片跳转。
ENTITY_LINKS = {
    "material": "/data/material",
    "inventory": "/data/inventory",
    "supplier": "/data/supplier",
    "order": "/data/order",
    "customer": "/data/customer",
}

def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _unavailable(code: str, message: str, **extra: Any) -> dict[str, Any]:
    """A renderable limitation, never a fabricated explanation."""
    return {
        "available": False,
        "code": code,
        "message": message,
        "verdict": None,
        "drivers": [],
        "deltas": None,
        "evidence": [],
        "provenance": {"scope": "resource_type", "batches": []},
        "decisionLink": None,
        "limitations": [{"code": code, "message": message}],
        **extra,
    }


class RiskExplainer:
    """Explain one tenant-owned risk from that tenant's current entities only."""

    def __init__(self, db: Session, tenant_id: str, *, now: datetime | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.now = now or datetime.now(timezone.utc)
        self.builder = TenantContextBuilder(db, tenant_id, now=self.now)

    # ── 入口 ────────────────────────────────────────────────────────────────

    def explain(self, risk: Risk) -> dict[str, Any]:
        details = risk.details if isinstance(risk.details, dict) else {}
        origin = str(details.get("origin") or "manual")

        if risk.status in CLOSED_STATUSES:
            return self._closed(risk, details)
        if origin == EXTERNAL_ORIGIN:
            return self._declared(risk, details)
        return self._computed(risk, details)

    # ── 已消除 / 已忽略：展示快照，不拿当前数据现编 ──────────────────────────

    def _closed(self, risk: Risk, details: dict[str, Any]) -> dict[str, Any]:
        snapshot = details.get("lastExplanationSnapshot") or details.get("measurement")
        label = CLOSED_STATUSES[risk.status]
        payload = _unavailable(
            "CG-A031",
            f"{label}，以下为{'消除' if risk.status == 'resolved' else '忽略'}当时的最后一次解释快照；"
            "当前数据下该解释可能已不成立。",
            snapshot=snapshot,
            snapshotAt=details.get("resolvedAt") or details.get("computedAt"),
            isSnapshot=True,
        )
        if snapshot is None:
            payload["message"] = f"{label}，且没有留存解释快照，无法还原当时的判定依据。"
            payload["limitations"].append(
                {"code": "CG-A033", "message": "该风险没有留存解释快照"}
            )
        return payload

    # ── 外部录入型风险：标注来源，不伪造指标推导 ────────────────────────────

    def _declared(self, risk: Risk, details: dict[str, Any]) -> dict[str, Any]:
        limitations = [{
            "code": "CG-A034",
            "message": "该风险来自外部事件录入，其等级为申报值而非系统计算值——"
                       "没有任何内部数据能推导出该事件是否发生。",
        }]
        verdict = {
            "mode": "declared",
            "level": risk.level,
            "score": risk.score,
            "scoreSource": details.get("scoreSource") or "declared_by_reporter",
            "rule": risk.rule,
            "reportedChannel": details.get("reportedChannel"),
            "reportedBy": details.get("reportedBy"),
            "reportedAt": details.get("reportedAt") or risk.found_at,
            "narrative": [
                f"来源：{details.get('reportedChannel') or '外部录入'}，"
                f"录入人 {details.get('reportedBy') or '未记录'}，"
                f"录入时间 {details.get('reportedAt') or risk.found_at}。",
                "该等级由录入方申报，系统未对其重新计算。",
            ],
        }
        material = self._material_of(details)
        driven: dict[str, Any] | None = None
        drivers: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        resources: set[str] = set()

        if material is None:
            limitations.append(
                {"code": "CG-2511", "message": "该风险未关联租户内有效物料，无法计算其库存影响"}
            )
        else:
            try:
                snapshot = self.builder.build_material_snapshot(material)
            except ContextBuildError as error:
                limitations.append({"code": error.code, "message": error.message})
            else:
                result = calculate_inventory_risk(
                    snapshot.inventory, snapshot.risk_weights, snapshot.thresholds
                )
                measurement = measure_material(result, snapshot)
                # 它自身的等级不是算出来的，但"它驱动了什么"是实打实算出来的。
                driven = {
                    "materialId": material.material_id,
                    "materialName": material.material_name or material.material_id,
                    "riskIndex": measurement["riskIndex"],
                    "warningLevel": measurement["warningLevel"],
                    "supportHours": measurement["supportHours"],
                    "triggerThreshold": measurement["triggerThreshold"],
                    "shouldTriggerResponse": measurement["shouldTriggerResponse"],
                }
                drivers = self._drivers(measurement)
                evidence, resources = self._evidence(material, snapshot)
                limitations.extend(self._quality_limitations(snapshot))

        return {
            "available": True,
            "code": None,
            "message": None,
            "risk": self._risk_head(risk),
            "verdict": verdict,
            "drivenImpact": driven,
            "drivers": drivers,
            "deltas": None,
            "evidence": evidence,
            "provenance": self._provenance(resources),
            "decisionLink": self._decision_link(risk, material, ready=driven is not None),
            "limitations": limitations,
        }

    # ── 计算型风险：主路径 ──────────────────────────────────────────────────

    def _computed(self, risk: Risk, details: dict[str, Any]) -> dict[str, Any]:
        material = self._material_of(details)
        if material is None:
            return _unavailable(
                "CG-2511", "该风险没有关联到租户内的有效物料，无法生成数据解释。",
                risk=self._risk_head(risk),
            )
        try:
            snapshot = self.builder.build_material_snapshot(material)
        except ContextBuildError as error:
            return _unavailable(error.code, error.message, risk=self._risk_head(risk))

        result = calculate_inventory_risk(
            snapshot.inventory, snapshot.risk_weights, snapshot.thresholds
        )
        measurement = measure_material(result, snapshot)
        evidence, resources = self._evidence(material, snapshot)
        return {
            "available": True,
            "code": None,
            "message": None,
            "risk": self._risk_head(risk),
            "verdict": {
                "mode": "computed",
                "warningLevel": measurement["warningLevel"],
                "riskIndex": measurement["riskIndex"],
                "triggerThreshold": measurement["triggerThreshold"],
                "thresholdSource": snapshot.configuration["source"],
                "configurationItems": snapshot.configuration["items"],
                "shouldTriggerResponse": measurement["shouldTriggerResponse"],
                "level": risk.level,
                "rule": risk.rule,
                # 叙述直接来自引擎，不经 LLM、不套模板话术。
                "narrative": measurement["narrative"],
            },
            "drivers": self._drivers(measurement),
            "deltas": self._deltas(details, measurement),
            "evidence": evidence,
            "provenance": self._provenance(resources),
            "decisionLink": self._decision_link(risk, material, ready=True, snapshot=snapshot),
            "limitations": self._quality_limitations(snapshot),
        }

    # ── 组件 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _risk_head(risk: Risk) -> dict[str, Any]:
        return {
            "id": risk.id, "code": risk.code, "level": risk.level, "score": risk.score,
            "rule": risk.rule, "status": risk.status, "foundAt": risk.found_at,
            "objectName": risk.object_name, "type": risk.type,
        }

    def _material_of(self, details: dict[str, Any]) -> Material | None:
        material_id = str(details.get("material_id") or details.get("material") or "").strip()
        if not material_id:
            return None
        return self.db.scalar(
            select(Material).where(
                Material.tenant_id == self.tenant_id, Material.material_id == material_id
            )
        )

    @staticmethod
    def _drivers(measurement: dict[str, Any]) -> list[dict[str, Any]]:
        """四维分项：权重 × 分项 = 贡献，并给出当前值与阈值的对照。"""
        weights = measurement["weights"]
        thresholds = measurement["thresholds"]
        current = {
            "shortage_urgency": measurement["supportHours"],
            "order_importance": measurement["criticalOrderCoverageRate"],
            "transit_delay": measurement["transitDelayHours"],
            "external_event": measurement["drivers"]["external_event"],
        }
        comparisons = {
            "shortage_urgency": (
                "below_red" if measurement["supportHours"] < thresholds["redSupportHours"]
                else "below_yellow" if measurement["supportHours"] < thresholds["yellowSupportHours"]
                else "normal"
            ),
        }
        output: list[dict[str, Any]] = []
        for key, score in measurement["drivers"].items():
            meta = DRIVER_META[key]
            weight = float(weights.get(key, 0))
            output.append({
                "key": key,
                "label": meta["label"],
                "metric": meta["metric"],
                "unit": meta["unit"],
                "score": score,
                "weight": weight,
                "contribution": round(weight * float(score), 2),
                "currentValue": current[key],
                "threshold": (
                    {"yellow": thresholds["yellowSupportHours"], "red": thresholds["redSupportHours"]}
                    if key == "shortage_urgency" else None
                ),
                "comparison": comparisons.get(key),
            })
        output.sort(key=lambda item: item["contribution"], reverse=True)
        return output

    def _deltas(self, details: dict[str, Any], measurement: dict[str, Any]) -> dict[str, Any] | None:
        """变化原因：与上一次重算快照对比。没有基线就明说没有，不编造变化。"""
        history = list(details.get("snapshotHistory") or [])
        stored = details.get("measurement") or {}
        previous = history[-2] if len(history) >= 2 else None
        if previous is None:
            return None
        changed: list[dict[str, Any]] = []
        for key, score in measurement["drivers"].items():
            before = (stored.get("drivers") or {}).get(key)
            if before is not None and before != score:
                changed.append({
                    "key": key, "label": DRIVER_META[key]["label"],
                    "from": before, "to": score,
                })
        return {
            "previousScore": previous.get("riskIndex"),
            "previousAt": previous.get("at"),
            "previousWarningLevel": previous.get("warningLevel"),
            "change": round(float(measurement["riskIndex"]) - float(previous.get("riskIndex") or 0), 2),
            "changedDrivers": changed,
        }

    def _evidence(
        self, material: Material, snapshot: MaterialSnapshot
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """可追溯来源：每条都是本租户的真实实体行，带业务键与真实更新时间。"""
        evidence: list[dict[str, Any]] = [{
            "entity": "material",
            "id": material.material_id,
            "name": material.material_name or material.material_id,
            "fields": {
                "dailyConsumption": material.daily_consumption,
                "unit": material.unit,
                "isCritical": material.is_critical,
            },
            "updatedAt": _iso(material.updated_at),
            "link": f"{ENTITY_LINKS['material']}?id={material.material_id}",
        }]
        resources = {"material"}

        for row in snapshot.inventory_rows:
            evidence.append({
                "entity": "inventory",
                "id": row.inventory_id,
                "name": row.warehouse_name or row.warehouse_id or row.inventory_id,
                "fields": {
                    "onHandQty": row.on_hand_qty, "availableQty": row.available_qty,
                    "safetyStockQty": row.safety_stock_qty, "inTransitQty": row.in_transit_qty,
                    "plannedArrivalAt": _iso(row.planned_arrival_at),
                    "estimatedArrivalAt": _iso(row.estimated_arrival_at),
                },
                "updatedAt": _iso(row.updated_at),
                "link": f"{ENTITY_LINKS['inventory']}?id={row.inventory_id}",
            })
            resources.add("inventory")

        supplier_rows = {
            row.supplier_id: row
            for row in self.db.scalars(
                select(SupplierEntity).where(
                    SupplierEntity.tenant_id == self.tenant_id,
                    SupplierEntity.supplier_id.in_([item["supplier_id"] for item in snapshot.suppliers] or [""]),
                )
            ).all()
        }
        for item in snapshot.suppliers:
            row = supplier_rows.get(item["supplier_id"])
            evidence.append({
                "entity": "supplier",
                "id": item["supplier_id"],
                "name": item["supplier_name"],
                "fields": {
                    "status": item["status"], "region": item["region"],
                    "reliabilityScore": item["reliability_score"],
                    "leadTimeHours": item["lead_time_hours"],
                    "availableEmergencyQty": item["available_qty"],
                    "supplierPrice": item["supplier_price"],
                },
                "updatedAt": _iso(row.updated_at) if row is not None else None,
                "link": f"{ENTITY_LINKS['supplier']}?id={item['supplier_id']}",
            })
            resources.add("supplier")

        order_rows = {
            row.sales_order_id: row
            for row in self.db.scalars(
                select(SalesOrder).where(
                    SalesOrder.tenant_id == self.tenant_id,
                    SalesOrder.sales_order_id.in_([item["order_id"] for item in snapshot.orders] or [""]),
                )
            ).all()
        }
        for item in snapshot.orders:
            row = order_rows.get(item["order_id"])
            evidence.append({
                "entity": "order",
                "id": item["order_id"],
                "name": item["customer_name"],
                "fields": {
                    "customerLevel": item["priority"], "demandQty": item["demand_qty"],
                    "dueHours": round(float(item["due_hours"]), 2),
                    "orderAmount": item["order_amount"], "grossProfit": item["gross_profit"],
                    "penaltyCost": item["penalty_cost"],
                },
                "updatedAt": _iso(row.updated_at) if row is not None else None,
                "link": f"{ENTITY_LINKS['order']}?id={item['order_id']}",
            })
            resources.add("order")
        return evidence, resources

    def _provenance(self, resources: set[str]) -> dict[str, Any]:
        """导入批次来源。

        实体表没有 source_import_job_id 列（本批不加列、不做迁移），因此这里的语义严格是
        "该租户该资源类型最近一次导入/同步批次"，而**不是本行血缘**——scope 字段显式声明这一点，
        前端据此写"非本行血缘"。行级血缘需要加列 + 迁移 + C2 回归，属另一批。
        """
        if not resources:
            return {"scope": "resource_type", "batches": []}
        # A04 的影响范围「数据来源」共用这同一个函数——两处口径必须一字不差。
        latest = latest_batches(self.db, self.tenant_id, resources)
        missing = sorted(resources - set(latest))
        return {
            "scope": "resource_type",
            "note": "最近一次导入批次（非本行血缘）",
            "batches": [latest[key] for key in sorted(latest)],
            "unknownResources": missing,
        }

    def _decision_link(
        self,
        risk: Risk,
        material: Material | None,
        *,
        ready: bool,
        snapshot: MaterialSnapshot | None = None,
    ) -> dict[str, Any]:
        """明确这条解释与后续方案生成共用哪些上下文键。"""
        readiness: dict[str, Any] | None = None
        if risk.incident_id:
            readiness = self.builder.readiness(risk.incident_id)
        elif snapshot is not None:
            readiness = {
                "ready": ready,
                "level": snapshot.data_quality.level,
                "blocking": [],
                "degraded": snapshot.data_quality.degraded,
            }
        return {
            "contextKeys": [
                "inventory.current_stock", "inventory.safety_stock",
                "inventory.hourly_consumption", "derived_metrics.critical_order_exposure",
                "derived_metrics.supplier_alternatives", "suppliers[]", "orders[]",
            ],
            "materialId": material.material_id if material is not None else None,
            "incidentId": risk.incident_id,
            "readiness": readiness,
            "canCreateIncident": risk.incident_id is None and risk.status not in CLOSED_STATUSES,
        }

    @staticmethod
    def _quality_limitations(snapshot: MaterialSnapshot) -> list[dict[str, Any]]:
        messages = {
            "missing_safety_stock": "安全库存缺失，已用「日消耗×24 小时」替代，该值为估算而非实测。",
            "missing_arrival_information": "缺少计划/预计到货时间，在途延误按 0 计。",
            "estimated_arrival_from_event_delay": "预计到货时间由事件延误推算，非实测。",
            "estimated_order_financials": "订单罚金/毛利缺失，已按估算系数推算。",
            "missing_supplier_reliability": "部分供应商缺少可靠性评分，已按 0 计。",
            "no_orders": "该物料当前没有未关闭订单，关键订单覆盖率按 100% 计。",
            "no_suppliers": "该物料没有合格供应商记录，供应商备选为空。",
            "default_event_delay": "事件未提供预计延误，已按默认值计算。",
        }
        return [
            {"code": reason, "message": messages.get(reason, reason)}
            for reason in snapshot.data_quality.degraded
        ]


def explain_risk(
    db: Session, tenant_id: str, risk: Risk, permissions: tuple[str, ...]
) -> dict[str, Any]:
    """Explain one risk, then run the payload through the existing field-masking path."""
    payload = RiskExplainer(db, tenant_id).explain(risk)
    return mask_for_requester(payload, permissions)
