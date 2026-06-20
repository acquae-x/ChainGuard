"""Serve the generated ChainGuard enterprise SQLite database as a mock ERP API."""

from __future__ import annotations

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


RESOURCE_TABLES = {
    "materials": "materials",
    "warehouses": "warehouses",
    "suppliers": "suppliers",
    "supplier-materials": "supplier_materials",
    "customers": "customers",
    "inventory": "inventory",
    "inventory-snapshots": "inventory_snapshots",
    "inventory-movements": "inventory_movements",
    "sales-orders": "sales_orders",
    "sales-order-lines": "sales_order_lines",
    "purchase-orders": "purchase_orders",
    "purchase-order-lines": "purchase_order_lines",
    "shipments": "shipments",
    "quality-inspections": "quality_inspections",
    "production-plans": "production_plans",
    "supplier-performance": "supplier_performance",
    "disruption-events": "disruption_events",
    "historical-decisions": "historical_decisions",
}
FILTER_FIELDS = {
    "materials": {"material_id", "category", "criticality", "active"},
    "suppliers": {"supplier_id", "region", "supplier_tier", "financial_risk", "status"},
    "supplier-materials": {"supplier_id", "material_id", "qualified"},
    "inventory": {"material_id", "warehouse_id"},
    "sales-orders": {
        "sales_order_id",
        "customer_id",
        "customer_level",
        "order_status",
        "sales_region",
    },
    "sales-order-lines": {"sales_order_id", "material_id", "warehouse_id"},
    "purchase-orders": {"supplier_id", "purchase_status", "buyer"},
    "shipments": {"supplier_id", "transport_mode", "shipment_status"},
    "disruption-events": {"event_id", "event_type", "severity", "event_status", "location"},
    "historical-decisions": {"outcome_status", "model_version"},
}


class ERPHandler(BaseHTTPRequestHandler):
    database_path: Path
    _decisions: list[dict] = []

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json(200, {"status": "ok", "database": str(self.database_path)})
            return
        if parsed.path == "/api/v1/catalog":
            self.send_catalog()
            return
        if parsed.path == "/api/v1/dashboard/summary":
            self.send_dashboard()
            return
        if parsed.path == "/api/v1/decisions":
            self.send_json(
                200,
                {
                    "resource": "decisions",
                    "total": len(self._decisions),
                    "items": self._decisions,
                },
            )
            return
        prefix = "/api/v1/"
        if not parsed.path.startswith(prefix):
            self.send_json(404, {"error": "not_found", "path": parsed.path})
            return
        resource = parsed.path[len(prefix):].strip("/")
        if resource not in RESOURCE_TABLES:
            self.send_json(404, {"error": "unknown_resource", "resource": resource})
            return
        self.send_resource(resource, parse_qs(parsed.query))

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/decisions":
            self.send_json(404, {"error": "not_found", "path": parsed.path})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "invalid_content_length"})
            return
        try:
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json(400, {"error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self.send_json(400, {"error": "decision_payload_must_be_object"})
            return

        self._decisions.append(payload)
        self.send_json(201, {"status": "stored", "decision": payload})

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def send_catalog(self) -> None:
        with self.connect() as connection:
            resources = []
            for resource, table in RESOURCE_TABLES.items():
                count = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                resources.append(
                    {
                        "resource": resource,
                        "endpoint": f"/api/v1/{resource}",
                        "record_count": count,
                    }
                )
        self.send_json(200, {"resources": resources})

    def send_dashboard(self) -> None:
        queries = {
            "materials": "SELECT COUNT(*) FROM materials",
            "inventory_records": "SELECT COUNT(*) FROM inventory",
            "inventory_shortage_records": (
                "SELECT COUNT(*) FROM inventory WHERE available_qty < safety_stock_qty"
            ),
            "at_risk_orders": (
                "SELECT COUNT(*) FROM sales_orders WHERE order_status IN ('at_risk', 'overdue')"
            ),
            "delayed_shipments": "SELECT COUNT(*) FROM shipments WHERE delay_hours > 0",
            "active_events": (
                "SELECT COUNT(*) FROM disruption_events WHERE event_status IN ('active', 'escalated')"
            ),
            "historical_decisions": "SELECT COUNT(*) FROM historical_decisions",
        }
        with self.connect() as connection:
            payload = {key: connection.execute(query).fetchone()[0] for key, query in queries.items()}
        self.send_json(200, payload)

    def send_resource(self, resource: str, query: dict[str, list[str]]) -> None:
        try:
            page = max(1, int(query.get("page", ["1"])[0]))
            page_size = min(1000, max(1, int(query.get("page_size", ["100"])[0])))
        except ValueError:
            self.send_json(400, {"error": "page and page_size must be integers"})
            return

        table = RESOURCE_TABLES[resource]
        allowed_filters = FILTER_FIELDS.get(resource, set())
        where = []
        parameters: list[object] = []
        for field in allowed_filters:
            if field in query:
                where.append(f'"{field}" = ?')
                parameters.append(query[field][0])
        where_sql = f" WHERE {' AND '.join(where)}" if where else ""
        offset = (page - 1) * page_size
        with self.connect() as connection:
            total = connection.execute(
                f'SELECT COUNT(*) FROM "{table}"{where_sql}',
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                f'SELECT * FROM "{table}"{where_sql} LIMIT ? OFFSET ?',
                [*parameters, page_size, offset],
            ).fetchall()
        self.send_json(
            200,
            {
                "resource": resource,
                "page": page,
                "page_size": page_size,
                "total": total,
                "items": [dict(row) for row in rows],
            },
        )

    def log_message(self, message_format: str, *args: object) -> None:
        print(f"[mock-erp] {self.address_string()} - {message_format % args}")


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--database",
        type=Path,
        default=project_root / "demo_assets" / "enterprise" / "database" / "chainguard_enterprise_demo.db",
    )
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.exists():
        raise FileNotFoundError(
            f"Demo database does not exist: {database}. Run generate_enterprise_demo_data.py first."
        )
    ERPHandler.database_path = database
    server = ThreadingHTTPServer((args.host, args.port), ERPHandler)
    print(f"Mock ERP API: http://{args.host}:{args.port}")
    print(f"OpenAPI file: {project_root / 'demo_assets' / 'erp_api' / 'openapi.yaml'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
