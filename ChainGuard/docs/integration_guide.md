# ChainGuard Enterprise Integration Guide

## §1 System Integration Architecture

ChainGuard exposes one tenant-aware application API under `/api/v1`.
Business requests use the JWT returned by `/api/v1/auth/login`; tenant identity
comes from the verified token and persisted user, not from a caller-supplied
tenant header.

The former root health, scenario, synchronous decision, pending-notification,
and auth-status APIs have been removed. They bypassed the persisted tenant/user
model and must not be used by integrations.

The remaining root endpoints are operational:

| Endpoint | Authentication | Purpose |
|---|---|---|
| `/healthz` | None | Process liveness |
| `/readyz` | None | Database and JWT signing-key readiness |
| `/metrics` | Prometheus service JWT | Global operational metrics |

The ERP Mock API remains a separate fixture on port `8765`. Its `GET /health`
belongs to the mock service and is unrelated to ChainGuard's removed root
health endpoint.

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

Log in and use the returned tenant access token:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@chainguard.demo","password":"Demo@2026"}'
```

The tenant decision path is:

1. Create or select an incident through `/api/v1/incidents`.
2. Start generation with
   `POST /api/v1/incidents/{incident_id}/proposals:generate`.
3. Poll `GET /api/v1/jobs/{job_id}` until it reaches a terminal state.
4. Read `/api/v1/proposals?incidentId={incident_id}` and
   `/api/v1/incidents/{incident_id}/decision-detail`.
5. Use `/api/v1/notifications` and the approval endpoints for human workflow.

Every request in this flow carries `Authorization: Bearer ${ACCESS_TOKEN}` and
is constrained by the authenticated user's tenant and data scope.

## §3 ChainGuard Tenant API Specification

Base URL for the FastAPI service:

```text
http://127.0.0.1:8000
```

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/auth/login` | POST | Issue tenant access and refresh tokens |
| `/api/v1/incidents` | GET/POST | List or create tenant incidents |
| `/api/v1/incidents/{id}/proposals:generate` | POST | Enqueue decision generation |
| `/api/v1/jobs/{job_id}` | GET | Read persisted job state |
| `/api/v1/proposals` | GET | List tenant proposals |
| `/api/v1/incidents/{id}/decision-detail` | GET | Read the complete masked result |
| `/api/v1/notifications` | GET | List the current user's notifications |

Example calls:

```bash
curl http://127.0.0.1:8000/api/v1/incidents \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

curl -X POST \
  http://127.0.0.1:8000/api/v1/incidents/${INCIDENT_ID}/proposals:generate \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

curl http://127.0.0.1:8000/api/v1/jobs/${JOB_ID} \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

The generation call returns HTTP 202 with `jobId` and `status`. Do not treat
that response latency as decision completion time. Cross-tenant identifiers are
hidden by the same not-found contract as unknown identifiers.

## §4 Prometheus Authentication

`/metrics` is global operational telemetry, not tenant business data. It accepts
only a least-privilege service JWT signed and verified by ChainGuard's existing
JWT implementation. The token must contain `type=metrics` and
`scope=metrics:read`; regular access tokens and `X-API-Key` are rejected.

Generate and mount the credential:

```bash
python scripts/generate_metrics_token.py \
  --days 30 \
  --output secrets/prometheus.jwt

docker compose --profile monitoring up -d prometheus node-exporter grafana
```

`config/prometheus.yml` reads the credential from
`/run/secrets/chainguard_metrics_token`. Compose mounts
`./secrets/prometheus.jwt` by default; set
`CHAINGUARD_METRICS_TOKEN_FILE` to use a secret-manager-provisioned host file.

Rotate before expiry, replace the mounted file atomically, and restart or reload
Prometheus. Missing, expired, wrongly scoped, or wrongly signed credentials
fail closed with HTTP 401/403.

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
FastAPI liveness (when port 8000 is directly exposed): http://localhost:8000/healthz
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
