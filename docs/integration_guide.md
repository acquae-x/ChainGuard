# ChainGuard Enterprise Integration Guide

## §1 System Integration Architecture

```text
[ERP Mock API : 8765]
        |
        | HTTP GET /api/v1/{table}
        v
[Enterprise demo data: demo_assets/enterprise/database/chainguard_enterprise_demo.db]
        |
        | ScenarioLoader.load_context(event_id)
        v
[ChainGuard Orchestrator: run_scenario(event_id, loader)]
        |
        | DecisionResult.to_dict()
        v
[ChainGuard Decision API : 8000]
        |
        | when audit_entry.human_approval_required == True
        v
[Notifier -> MockNotifier or WebhookNotifier]
        |
        | NotificationPayload JSON
        v
[Enterprise approval system / notification platform]

[Streamlit UI : 8501] -> app.py -> ChainGuard decision workflow
```

The ERP Mock API runs on port `8765` when started with `python scripts/mock_erp_server.py`. It exposes supply-chain tables through `GET /api/v1/{table}`, for example `GET /api/v1/materials`, `GET /api/v1/suppliers`, and `GET /api/v1/inventory`.

The ChainGuard Decision API runs on port `8000` through FastAPI. It exposes `/health`, `/scenarios`, `/decisions/demo`, `/decisions/scenario/{event_id}`, and `/notifications/pending`.

The Streamlit UI runs on port `8501` with `streamlit run app.py --server.port=8501 --server.address=0.0.0.0`.

Current implementation note: `DecisionOrchestrator.run_scenario(event_id, loader)` receives a `ScenarioLoader`. `ScenarioLoader` reads disruption and supply-chain context from `demo_assets/enterprise/database/chainguard_enterprise_demo.db`, not by making live HTTP calls to the ERP Mock API. The ERP Mock API is the integration-facing read model over the same enterprise demo data.

## §2 ERP To ChainGuard Data Flow

The ERP-side mock service is defined by `demo_assets/erp_api/openapi.yaml` and implemented by `scripts/mock_erp_server.py`. Its default base URL is:

```text
http://127.0.0.1:8765
```

Key ERP Mock API endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Health check for the ERP Mock API |
| `/api/v1/catalog` | GET | Lists available resources and record counts |
| `/api/v1/dashboard/summary` | GET | Returns supply-chain dashboard summary counts |
| `/api/v1/materials` | GET | Paged material master data |
| `/api/v1/suppliers` | GET | Paged supplier master data |
| `/api/v1/inventory` | GET | Paged inventory records |
| `/api/v1/disruption-events` | GET | Paged disruption events |
| `/api/v1/historical-decisions` | GET | Paged historical decision records |

Paged table endpoints support `page` and `page_size`, for example:

```bash
curl "http://127.0.0.1:8765/api/v1/materials?page=1&page_size=100"
curl "http://127.0.0.1:8765/api/v1/disruption-events?page=1&page_size=20"
```

To trigger ChainGuard decisions from an external system, call the Decision API on port `8000`:

```bash
# List available enterprise disruption scenarios.
curl http://127.0.0.1:8000/scenarios

# Run decision workflow for a specific enterprise event.
curl -X POST http://127.0.0.1:8000/decisions/scenario/EVT-000001
```

The decision path is:

1. External caller requests `POST /decisions/scenario/{event_id}` on port `8000`.
2. `src.api.run_scenario_decision` creates `ScenarioLoader()`.
3. `DecisionOrchestrator().run_scenario(event_id, loader)` calls `loader.load_context(event_id)`.
4. `ScenarioLoader` loads records from `demo_assets/enterprise/database/chainguard_enterprise_demo.db`.
5. The orchestrator returns `DecisionResult.to_dict()` as JSON.

This means the ERP Mock API is available for integration demos and data inspection, while the current decision runtime uses the local SQLite scenario dataset directly.

## §3 ChainGuard Decision API Specification

Base URL for the FastAPI service:

```text
http://127.0.0.1:8000
```

| Endpoint | Method | Description | Response |
|---|---|---|---|
| `/health` | GET | API health check | `{"status":"ok","version":"1.0.0"}` |
| `/scenarios` | GET | Lists available disruption scenarios, default `limit=50` | `{"scenarios":[...],"count":N}` |
| `/decisions/demo` | POST | Runs the built-in typhoon demo decision workflow | `DecisionResult.to_dict()` JSON |
| `/decisions/scenario/{event_id}` | POST | Runs the decision workflow for one enterprise scenario | `DecisionResult.to_dict()` JSON, or 404 when `event_id` is not found |
| `/notifications/pending` | GET | Lists accumulated approval notifications when using `MockNotifier` | `{"notifications":[...],"count":N}` |

Example calls:

```bash
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/scenarios?limit=5"
curl -X POST http://127.0.0.1:8000/decisions/demo
curl -X POST http://127.0.0.1:8000/decisions/scenario/EVT-000001
curl http://127.0.0.1:8000/notifications/pending
```

`DecisionResult.to_dict()` includes these top-level fields:

```text
risk_weights
thresholds
context
inventory_risk
proposals
conflict
rebuttal
arbitration
experience_card
constraint_analysis
debate_result
experience_references
explanation
audit_entry
```

The `audit_entry` object includes the operational fields used by integration and approval workflows:

```text
decision_id
timestamp
event_type
event_severity
inventory_risk_index
constraint_feasible_count
debate_converged
human_approval_required
decision_status
error_message
```

External systems should use `decision_id` as the decision correlation key, `inventory_risk_index` as the quantitative risk signal, `decision_status` as the outcome status, and `human_approval_required` to decide whether a manual approval queue should be opened.

## §4 Approval Notification Flow

I16 adds a notification abstraction in `src/notifier.py`.

The trigger condition is:

```python
audit_entry["human_approval_required"] == True
```

When that condition is true after `/decisions/demo` or `/decisions/scenario/{event_id}`, `src.api` calls:

```python
_notifier.send(NotificationPayload.from_audit_entry(result.audit_entry))
```

`NotificationPayload` fields:

```text
decision_id
timestamp
event_type
inventory_risk_index
human_approval_required
decision_status
```

Notifier implementations:

| Type | Intended Use | Behavior |
|---|---|---|
| `MockNotifier` | Demo and tests | Appends each `NotificationPayload` to `.sent`; `/notifications/pending` returns this list |
| `WebhookNotifier(url)` | Production integration | Sends an HTTP POST JSON payload to the configured URL; network failures return `False` and do not block the API response |

The default module-level notifier in `src.api` is:

```python
_notifier: Notifier = MockNotifier()
```

For a production deployment, the integration point is to configure a `WebhookNotifier` target such as:

```python
_notifier = WebhookNotifier("https://your-erp-system/api/v1/approvals")
```

The receiving enterprise approval system can store the `NotificationPayload`, fetch the full decision body by correlation if needed, and route manual review based on `human_approval_required`, `inventory_risk_index`, and `decision_status`.

## §5 Docker Startup And Enterprise Deployment

I15 adds these deployment files:

```text
Dockerfile
docker-compose.yml
.dockerignore
```

Start the Streamlit UI and FastAPI service with Docker Compose:

```bash
git clone <repo-url>
cd ChainGuard
docker compose up --build
```

Service URLs:

```text
Streamlit UI: http://localhost:8501
FastAPI REST: http://localhost:8000
Swagger UI: http://localhost:8000/docs
FastAPI health: http://localhost:8000/health
ERP Mock API: http://localhost:8765
```

The `docker-compose.yml` file defines two services:

| Service | Command | Port |
|---|---|---|
| `streamlit` | `streamlit run app.py --server.port=8501 --server.address=0.0.0.0` | `8501:8501` |
| `api` | `uvicorn src.api:app --host 0.0.0.0 --port 8000` | `8000:8000` |

Both services mount the same persistent data volume:

```yaml
volumes:
  - ./data:/app/data
```

This keeps runtime data outside the container filesystem:

| File | Purpose |
|---|---|
| `data/experience_cards.json` | Persistent experience-card storage across container restarts |
| `data/model_registry.json` | Classifier/model registry metadata |
| `data/audit_log.jsonl` | Decision audit log records |

The ERP Mock API is independent of the compose stack and can be started separately when ERP-style data inspection is needed:

```bash
python scripts/mock_erp_server.py
```

It listens on `http://127.0.0.1:8765` by default and serves the same enterprise demo database used by the scenario loader.

## Section 6 TLS Termination

Production deployments should expose ChainGuard over HTTPS. Two supported
patterns are:

1. Terminate TLS at a reverse proxy or load balancer, then forward private
   network traffic to `uvicorn src.api:app --host 0.0.0.0 --port 8000`.
2. Run Uvicorn with certificate files directly for smaller controlled
   deployments:

```bash
uvicorn src.api:app \
  --host 0.0.0.0 \
  --port 8443 \
  --ssl-keyfile /path/to/tls.key \
  --ssl-certfile /path/to/tls.crt
```

`docker-compose.yml` includes an `https-example` profile that expects
development or externally provisioned certificates under `./certs/dev.key` and
`./certs/dev.crt`:

```bash
docker compose --profile https-example up api-https
```

Use a managed certificate authority, platform secret store, or enterprise KMS
outside this repository for production certificate and key lifecycle
management. Do not commit private keys to source control.
