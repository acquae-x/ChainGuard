"""Single catalog of real enterprise import source types and supported channels."""

from __future__ import annotations

from typing import Any


IMPORT_TYPE_CATALOG: dict[str, dict[str, Any]] = {
    "material": {"label": "物料主数据", "group": "主数据", "source_table": "materials", "erp_resource": "materials", "entity": True},
    "supplier": {"label": "供应商主数据", "group": "主数据", "source_table": "suppliers", "erp_resource": "suppliers", "entity": True},
    "supplier_material": {"label": "供应商物料关系", "group": "主数据", "source_table": "supplier_materials", "erp_resource": "supplier-materials", "entity": True},
    "customer": {"label": "客户主数据", "group": "主数据", "source_table": "customers", "erp_resource": "customers", "entity": True},
    "warehouse": {"label": "仓库主数据", "group": "主数据", "source_table": "warehouses", "erp_resource": "warehouses", "entity": False},
    "inventory": {"label": "实时库存", "group": "库存与物流", "source_table": "inventory", "erp_resource": "inventory", "entity": True},
    "inventory_snapshot": {"label": "库存快照", "group": "库存与物流", "source_table": "inventory_snapshots", "erp_resource": "inventory-snapshots", "entity": False},
    "inventory_movement": {"label": "库存流水", "group": "库存与物流", "source_table": "inventory_movements", "erp_resource": "inventory-movements", "entity": False},
    "shipment": {"label": "运输与在途", "group": "库存与物流", "source_table": "shipments", "erp_resource": "shipments", "entity": False},
    "order": {"label": "销售订单", "group": "销售与采购", "source_table": "sales_orders", "erp_resource": "sales-orders", "entity": True},
    "order_line": {"label": "销售订单行", "group": "销售与采购", "source_table": "sales_order_lines", "erp_resource": "sales-order-lines", "entity": True},
    "purchase_order": {"label": "采购订单", "group": "销售与采购", "source_table": "purchase_orders", "erp_resource": "purchase-orders", "entity": False},
    "purchase_order_line": {"label": "采购订单行", "group": "销售与采购", "source_table": "purchase_order_lines", "erp_resource": "purchase-order-lines", "entity": False},
    "production_plan": {"label": "生产计划", "group": "生产与质量", "source_table": "production_plans", "erp_resource": "production-plans", "entity": False},
    "quality_inspection": {"label": "质量检验", "group": "生产与质量", "source_table": "quality_inspections", "erp_resource": "quality-inspections", "entity": False},
    "supplier_performance": {"label": "供应商绩效", "group": "生产与质量", "source_table": "supplier_performance", "erp_resource": "supplier-performance", "entity": False},
    "disruption_event": {"label": "供应链中断事件", "group": "风险与决策", "source_table": "disruption_events", "erp_resource": "disruption-events", "entity": False},
    "historical_decision": {"label": "历史决策记录", "group": "风险与决策", "source_table": "historical_decisions", "erp_resource": "historical-decisions", "entity": False},
}

IMPORT_MODES = (
    {"value": "structured", "label": "CSV / Excel", "description": "字段映射、校验、批量落库"},
    {"value": "ocr", "label": "PDF / Word / 图片", "description": "OCR/文本提取后人工确认"},
    {"value": "erp", "label": "ERP 接口", "description": "连接测试、目录预览、选择同步"},
)


def catalog_payload() -> dict[str, Any]:
    return {
        "modes": list(IMPORT_MODES),
        "types": [
            {"value": value, "modes": ["structured", "ocr", "erp"], **definition}
            for value, definition in IMPORT_TYPE_CATALOG.items()
        ],
    }


# Compatibility re-export. The maintained UTF-8 catalog lives in
# enterprise_import_catalog.py; keep older imports on the same single source.
from .enterprise_import_catalog import (  # noqa: E402,F401
    IMPORT_MODES as IMPORT_MODES,
    IMPORT_TYPE_CATALOG as IMPORT_TYPE_CATALOG,
    catalog_payload as catalog_payload,
)
