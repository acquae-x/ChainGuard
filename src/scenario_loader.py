import sqlite3
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO_DB = (
    PROJECT_ROOT
    / "demo_assets"
    / "enterprise"
    / "database"
    / "chainguard_enterprise_demo.db"
)

TRANSPORT_OPTIONS = [
    {
        "mode": "air",
        "name": "空运",
        "estimated_hours": 18.0,
        "cost_multiplier": 3.0,
        "cost_level": "高",
        "risk_note": "速度最快，但加急成本高",
    },
    {
        "mode": "truck",
        "name": "陆运",
        "estimated_hours": 42.0,
        "cost_multiplier": 1.6,
        "cost_level": "中",
        "risk_note": "成本中等，但受天气和道路管制影响",
    },
    {
        "mode": "rail",
        "name": "铁路",
        "estimated_hours": 60.0,
        "cost_multiplier": 1.3,
        "cost_level": "中低",
        "risk_note": "稳定性较好，但时间较长",
    },
    {
        "mode": "sea",
        "name": "海运",
        "estimated_hours": 96.0,
        "cost_multiplier": 1.0,
        "cost_level": "低",
        "risk_note": "成本低，但容易受到港口和航线事件影响",
    },
]


class ScenarioLoader:
    """Load enterprise disruption scenarios from the synthetic SQLite dataset."""

    def __init__(self, db_path: str | Path = DEFAULT_SCENARIO_DB) -> None:
        path = Path(db_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise FileNotFoundError(f"场景数据库不存在：{path}")
        self.db_path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def list_scenarios(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    event_title,
                    event_type,
                    severity,
                    risk_score,
                    event_status
                FROM disruption_events
                ORDER BY started_at DESC, event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_context(self, event_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            event = connection.execute(
                "SELECT * FROM disruption_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if event is None:
                raise ValueError(f"未找到场景事件：{event_id}")

            material_id = event["affected_material_id"]
            material = connection.execute(
                "SELECT * FROM materials WHERE material_id = ?",
                (material_id,),
            ).fetchone()
            if material is None:
                raise ValueError(f"事件 {event_id} 的物料不存在：{material_id}")

            inventory_totals = connection.execute(
                """
                SELECT
                    COALESCE(SUM(on_hand_qty), 0) AS current_stock,
                    COALESCE(SUM(safety_stock_qty), 0) AS safety_stock,
                    COALESCE(SUM(in_transit_qty), 0) AS in_transit_qty
                FROM inventory
                WHERE material_id = ?
                """,
                (material_id,),
            ).fetchone()

            critical_order_demand = connection.execute(
                """
                SELECT COALESCE(SUM(sol.ordered_qty), 0)
                FROM sales_order_lines AS sol
                JOIN sales_orders AS so
                  ON so.sales_order_id = sol.sales_order_id
                WHERE sol.material_id = ?
                  AND so.customer_level = 'A'
                  AND so.order_status IN ('at_risk', 'pending')
                """,
                (material_id,),
            ).fetchone()[0]

            suppliers = self._load_suppliers(
                connection,
                material_id,
                event["affected_supplier_id"],
                event["estimated_delay_hours"],
            )
            orders = self._load_orders(connection, material_id)

        delay_hours = float(event["estimated_delay_hours"] or 0)
        risk_score = float(event["risk_score"] or 0)
        inventory = {
            "material_id": material["material_id"],
            "material_name": material["material_name"],
            "current_stock": float(inventory_totals["current_stock"]),
            "hourly_consumption": float(material["daily_consumption"]) / 24,
            "safety_stock": float(inventory_totals["safety_stock"]),
            "in_transit_qty": float(inventory_totals["in_transit_qty"]),
            "planned_arrival_hours": 0.0,
            "estimated_arrival_hours": delay_hours,
            "critical_order_demand": float(critical_order_demand),
            "external_risk_score": risk_score,
        }
        event_context = {
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "type": event["event_type"],
            "title": event["event_title"],
            "severity": event["severity"],
            "external_risk_score": risk_score,
            "location": event["location"],
            "affected_supplier": event["affected_supplier_id"],
            "affected_material": material_id,
            "affected_route": event["affected_route"],
            "delay_hours": delay_hours,
            "estimated_delay_hours": delay_hours,
            "event_status": event["event_status"],
            "description": event["description"],
        }

        return {
            "inventory": inventory,
            "orders": orders,
            "suppliers": suppliers,
            "transport_options": self._build_transport_options(
                event["event_type"],
                event["affected_route"],
            ),
            "events": [event_context],
        }

    @staticmethod
    def _load_suppliers(
        connection: sqlite3.Connection,
        material_id: str,
        affected_supplier_id: str | None,
        estimated_delay_hours: float | None,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT
                s.supplier_id,
                s.supplier_name,
                s.status,
                s.reliability_score,
                s.region,
                sm.material_id,
                sm.supplier_rank,
                sm.available_emergency_qty,
                sm.lead_time_hours,
                sm.emergency_cost_multiplier
            FROM supplier_materials AS sm
            JOIN suppliers AS s
              ON s.supplier_id = sm.supplier_id
            WHERE sm.material_id = ?
              AND sm.qualified = 1
            ORDER BY sm.supplier_rank ASC, s.supplier_id ASC
            """,
            (material_id,),
        ).fetchall()

        return [
            {
                "supplier_id": row["supplier_id"],
                "supplier_name": row["supplier_name"],
                "material_id": row["material_id"],
                "status": row["status"],
                "available_qty": float(row["available_emergency_qty"] or 0),
                "lead_time_hours": float(row["lead_time_hours"] or 0),
                "delay_hours": (
                    float(estimated_delay_hours or 0)
                    if row["supplier_id"] == affected_supplier_id
                    else 0.0
                ),
                "cost_multiplier": float(row["emergency_cost_multiplier"] or 1),
                "reliability_score": float(row["reliability_score"] or 0),
                "region": row["region"],
                "supplier_rank": int(row["supplier_rank"]),
            }
            for row in rows
        ]

    @staticmethod
    def _load_orders(
        connection: sqlite3.Connection,
        material_id: str,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT
                so.sales_order_id,
                so.customer_id,
                so.customer_level,
                so.promised_delivery_at,
                so.gross_profit,
                so.penalty_cost,
                sol.ordered_qty,
                ROUND(
                    (JULIANDAY(so.promised_delivery_at) - JULIANDAY('now')) * 24
                ) AS delivery_hours
            FROM sales_orders AS so
            JOIN sales_order_lines AS sol
              ON so.sales_order_id = sol.sales_order_id
            WHERE sol.material_id = ?
              AND so.order_status NOT IN ('delivered', 'cancelled')
            ORDER BY so.promised_delivery_at ASC
            LIMIT 20
            """,
            (material_id,),
        ).fetchall()

        return [
            {
                "order_id": row["sales_order_id"],
                "customer_name": row["customer_id"],
                "priority": row["customer_level"],
                "required_material": material_id,
                "delivery_hours": float(row["delivery_hours"] or 0),
                "due_hours": float(row["delivery_hours"] or 0),
                "demand": float(row["ordered_qty"] or 0),
                "demand_qty": float(row["ordered_qty"] or 0),
                "gross_profit": float(row["gross_profit"] or 0),
                "penalty_cost": float(row["penalty_cost"] or 0),
            }
            for row in rows
        ]

    @staticmethod
    def _build_transport_options(
        event_type: str,
        affected_route: str | None,
    ) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        route_note = affected_route or "未指定路线"
        for template in TRANSPORT_OPTIONS:
            option = dict(template)
            unavailable = (
                event_type == "port_shutdown" and option["mode"] == "sea"
            ) or (
                event_type == "route_blockage"
                and option["mode"] in {"truck", "rail"}
            )
            option["available"] = not unavailable
            if unavailable:
                option["risk_note"] = f"{route_note} 受事件影响，当前不可用"
            options.append(option)
        return options

