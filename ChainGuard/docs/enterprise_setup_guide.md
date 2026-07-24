# ChainGuard Enterprise Setup Guide

## §1 Environment Configuration

ChainGuard's production product is a tenant-aware web application; the dedicated `web` service is its browser UI and FastAPI provides the internal application API.

Compose starts `postgres`, `redis`, a one-shot `migrate` service, the internal
FastAPI `api`, and the browser-facing `web` service. `web` is published on
`http://localhost:8080` by default (override with `WEB_PORT`); `api` listens on
container port `8000` only and is intentionally not host-published.

The production UI is `chainguard-web` (React), served by the `web` service. The
former Streamlit analysis app (`app.py`) has been removed; its decision-core
computations live in `src/` and are surfaced through `/api/v1` and the React UI.

Create a deployment-specific `.env` alongside `docker-compose.yml`:

```dotenv
POSTGRES_DB=chainguard
POSTGRES_USER=chainguard
POSTGRES_PASSWORD=<strong-database-password>
JWT_SECRET=<long-random-signing-secret>
SEED_DEMO_PASSWORD=<demo-password>
```

Useful optional settings are `WEB_PORT`, `API_WORKERS`, `CORS_ORIGINS`,
`RATE_LIMIT_STORAGE_URI`, and `REFRESH_COOKIE_SECURE`. `JWT_SECRET` is a
signing dependency: `/readyz` is unhealthy when it is absent.

Start the product with:

```bash
docker compose up --build
```

Open `http://localhost:8080` (or `WEB_PORT`) in a browser. If a deployment
intentionally exposes the internal API, place an authenticated gateway in front
of it; do not treat it as the primary product entry point.

For a non-Compose local API process, provide an absolute `DATABASE_URL` plus
`JWT_SECRET`, `SEED_DEMO_PASSWORD`, and `CHAINGUARD_ENCRYPTION_KEY`, then run:

```bash
uvicorn src.api:app --host 127.0.0.1 --port 8000
```

When a built frontend exists at `../chainguard-web/dist`, `src.api` can serve
it for a single-process local demonstration. Compose uses the dedicated `web`
service instead.

## §2 Enterprise Data Requirements

> Legacy local-analysis note: this section documents checked-in SQLite fixtures
> and `ScenarioLoader`, not the production tenant data contract. Production
> data is PostgreSQL-backed and enters through the UI or `/api/v1`.

Enterprise scenario data is loaded by `src/scenario_loader.py`. The default SQLite demo database path is:

```text
demo_assets/enterprise/database/chainguard_enterprise_demo.db
```

Production or customer datasets can use `ScenarioLoader(db_path=...)` as long as the schema provides the fields read by `ScenarioLoader.list_scenarios()` and `ScenarioLoader.load_context()`.

Scenario listing query reads `disruption_events`:

```text
event_id
event_title
event_type
severity
risk_score
event_status
```

Scenario context requirements:

| Table | Required fields used by current code | Purpose |
|---|---|---|
| `disruption_events` | `event_id`, `event_title`, `event_type`, `severity`, `risk_score`, `event_status`, `location`, `description`, `affected_supplier_id`, `affected_material_id`, `affected_route`, `estimated_delay_hours` | Defines the disruption event and chooses the affected material and supplier |
| `materials` | `material_id`, `material_name`, `daily_consumption` | Converts daily consumption to `hourly_consumption` for inventory risk |
| `inventory` | `material_id`, `on_hand_qty`, `safety_stock_qty`, `in_transit_qty` | Computes current stock, safety stock, and in-transit quantity totals |
| `suppliers` | `supplier_id`, `supplier_name`, `status`, `reliability_score`, `region` | Supplies basic supplier profile fields |
| `supplier_materials` | `supplier_id`, `material_id`, `supplier_rank`, `qualified`, `available_emergency_qty`, `lead_time_hours`, `emergency_cost_multiplier` | Provides emergency supply quantity, lead time, cost multiplier, and ranked qualified suppliers |
| `sales_orders` | `sales_order_id`, `customer_id`, `customer_level`, `promised_delivery_at`, `gross_profit`, `penalty_cost`, `order_status` | Provides order priority, promised date, profit, and penalty data |
| `sales_order_lines` | `sales_order_id`, `material_id`, `ordered_qty` | Links sales orders to material demand |

The critical demand query joins `sales_order_lines` and `sales_orders`, filters `customer_level = 'A'`, and counts orders where `order_status IN ('at_risk', 'pending')`.

The order-loading query excludes completed orders with:

```text
order_status NOT IN ('delivered', 'cancelled')
```

It calculates `delivery_hours` from `promised_delivery_at` using SQLite `JULIANDAY(...)` in the current implementation.

Historical learning and model comparison data is loaded by `src/history_pipeline.py` from the `historical_decisions` table. Important fields include:

```text
case_id
created_at
outcome_status
covered_demand_rate
predicted_delay_hours
actual_delay_hours
predicted_cost
actual_cost
production_downtime_hours
human_rating
lessons_learned
```

Quality checks in `history_pipeline` require:

```text
case_id is not empty
0.0 <= covered_demand_rate <= 1.0
1 <= human_rating <= 5
actual_cost >= 0
```

## §3 UI Steps And Render Functions

> The production UI is `chainguard-web` (React), served by the `web` service.
> The former Streamlit renderers described below have been removed.

The decision chain has 11 stages. They were originally shown by Streamlit
`render_step_*` functions (now removed); the **same content** is today surfaced
by the React `DecisionTrace` component and the `/api/v1` incident
decision-detail payload. The table maps each stage to the payload it draws from.

| Step | Function | What the UI displays | Key data source |
|---|---|---|---|
| Step 1 | `render_step_1` | Inventory risk summary, warning level, trigger flag, and risk explanation lines | `result.context["inventory"]`, `result.inventory_risk` |
| Step 2 | `render_step_2` | Disruption event cards, affected route, location, affected supplier, delay, and monitored material | `result.context["events"]`, `result.context["suppliers"]`, `result.context["inventory"]` |
| Step 3 | `render_step_3` | Ranked agent proposals, total scores, low-score warnings, reasoning, actions, and risks | `result.proposals`, `low_score_threshold` |
| Step 4 | `render_step_4` | Proposal score ranking and conflict detection result | `result.proposals`, `result.conflict` |
| Step 5 | `render_step_5` | Rebuttal points, suggested revision, and accepted tradeoff | `result.rebuttal` |
| Step 6 | `render_step_6` | Arbitration title, final score, final strategy, execution plan, manual confirmation points, expected effects, and arbitration derivation | `result.arbitration`, `result.proposals`, `result.conflict`, `result.rebuttal` |
| Step 7 | `render_step_7` | Generated experience card, trigger conditions, recommended pattern, confidence score, tags, and saved card count | `result.experience_card`, `data/experience_cards.json` |
| Step 8 | `render_step_8_constraint_debate` | Constraint solver feasible count, optimal utility, debate rounds, utility change, optimal combo, recommended changes, and violations | `result.constraint_analysis`, `result.debate_result` |
| Step 9 | `render_step_9_experience_references` | Historical references, confidence adjustment, risk hints, TF-IDF retrieval label, and parameter calibration comparison expander | `result.experience_references`, `demo_assets/enterprise/csv/historical_decisions.csv` |
| Step 10 | `render_step_10_explanation` | Explanation summary for arbitration, debate, and constraints; also shows whether LLM enhancement was used | `result.explanation` |
| Step 11 | `render_step_11_audit` | Audit status, inventory risk index, feasible count, debate convergence, human approval prompt, and full audit JSON | `result.audit_entry` |

Beyond the 11 stages, the decision-detail payload also carries a sensitivity
series (`run_sensitivity("current_stock", ...)`), which the React `DecisionTrace`
renders as a current-stock-vs-risk-index curve.

The UI has two scenario modes:

```text
演示场景
企业真实场景
```

In demo mode, `DecisionOrchestrator().run_demo()` is used. In enterprise mode, `DecisionOrchestrator().run_scenario(enterprise_event_id, ScenarioLoader())` is used.

## §4 Enterprise Operation Flow

For the supported product UI, start Compose and open the published `web`
service:

```bash
docker compose up --build
# open http://localhost:8080 (or WEB_PORT)
```

The FastAPI service is internal to this stack at `api:8000`. For a local
single-process demonstration, use the isolated-environment command from
section 1 and keep the API bound to `127.0.0.1` unless a gateway is configured.

Operational FastAPI routes in `src/api.py` include:

```text
GET /healthz
GET /readyz
GET /metrics
```

Tenant business routes live under `/api/v1` and use the JWT tenant/user
authentication in `src/webapi/auth/security.py`. The former root scenario,
synchronous decision, pending-notification, and auth-status routes were removed;
`CHAINGUARD_API_KEYS` and open mode no longer exist.

Prometheus uses a separate token type within the same JWT implementation. Create
the least-privilege credential with the deployment signing configuration:

```bash
python scripts/generate_metrics_token.py \
  --days 30 \
  --output secrets/prometheus.jwt
```

`config/prometheus.yml` sends this credential from
`/run/secrets/chainguard_metrics_token`; compose mounts
`./secrets/prometheus.jwt` by default. Set
`CHAINGUARD_METRICS_TOKEN_FILE` when a secret manager provisions a different
host path. Rotate the file before expiry and restart or reload Prometheus.

For Docker operation:

```bash
docker compose up --build
```

Current Compose application services:

| Service | Host exposure | Role |
|---|---|---|
| `web` | `${WEB_PORT:-8080}:8080` | Browser UI and reverse proxy to `api` |
| `api` | Internal `api:8000` only | Tenant-aware FastAPI API |
| `migrate` | None | Database migration and demo seed before API startup |

`api` persists runtime application data through the named `appdata` volume and
tenant calibration/import state through the named `workspace` volume. Do not
rely on mutable JSON files as the production source of tenant state.

Recommended enterprise run sequence:

1. Set the required deployment `.env` values and provision PostgreSQL and Redis.
2. Generate `secrets/prometheus.jwt` before enabling the monitoring profile.
3. Start `docker compose up --build` and open the `web` service on port 8080.
4. Log in to the tenant product, import or inspect tenant data, then create or
   select an incident.
5. Enqueue proposal generation through the persisted workflow and monitor its
   job, proposals, approvals, tasks, and audit trail in the UI or `/api/v1`.
6. Use an integration layer for any approved ERP writeback; automatic writeback
   is not implemented.

## §5 Fallback Behavior And Limits

ChainGuard is designed to keep the main decision flow available when optional enhancement components are absent.

| Missing or limited component | Current behavior | Impact |
|---|---|---|
| `sentence-transformers` not installed | Semantic embedding retrieval can fall back to the scikit-learn based `TfidfStore` path | Retrieval remains available with lexical TF-IDF matching |
| Ollama or Qwen unavailable | Explanation generation uses template output when LLM explanation fails | Persisted workflow remains available with degraded explanations |
| No historical references | Experience retrieval returns empty references and no risk hints | The persisted workflow remains available without similar-case hints |
| `data/experience_cards.json` missing | Saved-card count is treated as empty until cards are generated | Step 7 can still display the current generated experience card |
| `data/model_registry.json` missing | `ModelRegistry().get_stable()` returns `None` until a model is registered | Model comparison can create registry records after evaluation |
| `ConstraintSolver` finds no fully feasible combination | Constraint result can mark `feasible=False` and still return analysis data | Step 8 remains visible for manual review |
| Prometheus metrics JWT missing, expired, or invalid | `/metrics` returns 401/403 without falling back to an application role | Business APIs remain available; monitoring scrapes fail until the token is provisioned or rotated |

Known limits:

```text
PriorClassifier is a frequency-prior baseline, not a learned feature model.
Automatic ERP writeback is not implemented.
PostgreSQL migration is documented separately in docs/production_db_migration.md, but current runtime still reads SQLite in scenario_loader and history_pipeline.
```

The current implemented production-facing capabilities are:

```text
Tenant-aware browser UI through the Compose `web` service
FastAPI REST API in src/api.py (internal to Compose unless deliberately gated)
Dockerfile and docker-compose.yml deployment files
JWT tenant/user authentication for `/api/v1`
Least-privilege JWT authentication for `/metrics`
MockNotifier and WebhookNotifier notification abstraction
Persisted incident, proposal, approval, task, and audit workflows
```
