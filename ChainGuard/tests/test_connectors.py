import json
import threading
from pathlib import Path
from urllib import request

import pytest

from scripts.mock_erp_server import ERPHandler, ThreadingHTTPServer
from src.connectors import RestErpConnector


DB_PATH = Path("demo_assets/enterprise/database/chainguard_enterprise_demo.db")


@pytest.fixture(scope="module")
def erp_server():
    ERPHandler.database_path = DB_PATH
    ERPHandler._decisions = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ERPHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def test_fetch_events_maps_fields(erp_server):
    events = RestErpConnector(erp_server).fetch_disruption_events()

    assert events
    assert all("event_id" in event for event in events)


def test_fetch_context_shape(erp_server):
    connector = RestErpConnector(erp_server)
    event_id = connector.fetch_disruption_events()[0]["event_id"]

    context = connector.fetch_context(event_id)

    assert {"inventory", "events", "suppliers", "orders"}.issubset(context)
    assert context["events"][0]["event_id"] == event_id


def test_write_back_then_readable(erp_server):
    connector = RestErpConnector(erp_server)

    assert connector.write_back_decision(
        {"decision_id": "TEST-001", "decision_status": "approved"}
    )
    with request.urlopen(f"{erp_server}/api/v1/decisions", timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))

    assert any(item.get("decision_id") == "TEST-001" for item in payload["items"])


def test_unreachable_erp_raises_or_empty():
    connector = RestErpConnector("http://127.0.0.1:1", timeout=0.2, retries=0)

    events = connector.fetch_disruption_events()

    assert events == []
