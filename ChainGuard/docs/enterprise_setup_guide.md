# ChainGuard Enterprise Setup Guide

## §1 Environment Configuration

ChainGuard currently runs as a Python application with Streamlit UI, FastAPI REST API, and optional Docker deployment. The dependency list must be read from `requirements.txt` rather than inferred.

Current required dependencies in `requirements.txt`:

```text
streamlit
scikit-learn>=1.0
fastapi>=0.110
uvicorn>=0.27
httpx>=0.27
```

Dependency meaning:

| Dependency | Status | Used for |
|---|---|---|
| `streamlit` | Required | Main web UI in `app.py` |
| `scikit-learn>=1.0` | Required | TF-IDF retrieval, vector math, model comparison, classifier baseline |
| `fastapi>=0.110` | Required | REST service in `src/api.py` |
| `uvicorn>=0.27` | Required | ASGI runtime for `uvicorn src.api:app` |
| `httpx>=0.27` | Required | FastAPI `TestClient` dependency |

The file also documents an optional semantic retrieval dependency:

```text
# Optional for EmbeddingStore; TfidfStore remains the offline fallback.
# sentence-transformers>=2.2
```

`sentence-transformers>=2.2` is optional. When it is absent, retrieval can fall back to the scikit-learn based TF-IDF path. Do not treat `scikit-learn` as optional; it is installed by the normal requirements file and is part of the core runtime.

Basic local setup:

```bash
pip install -r requirements.txt
streamlit run app.py
```

FastAPI is implemented in `src/api.py` and can be started directly:

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Docker is implemented through `Dockerfile` and `docker-compose.yml`. The compose stack exposes:

```text
Streamlit UI: 8501
FastAPI REST: 8000
```

Start both application services with:

```bash
docker compose up --build
```

## §2 Enterprise Data Requirements

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

The Streamlit UI in `app.py` renders the decision flow through 11 actual `render_step_*` functions. The function names below must stay aligned with the code.

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

After Step 11, `app.py` also renders sensitivity analysis through `render_sensitivity(...)`, using `run_sensitivity("current_stock", [720, 1440, 2160, 3600, 5400, 7200], baseline_context=result.context)`. This is not one of the 11 `render_step_*` functions, but it is part of the current page.

The UI has two scenario modes:

```text
演示场景
企业真实场景
```

In demo mode, `DecisionOrchestrator().run_demo()` is used. In enterprise mode, `DecisionOrchestrator().run_scenario(enterprise_event_id, ScenarioLoader())` is used.

## §4 Enterprise Operation Flow

For local UI operation:

```bash
pip install -r requirements.txt
streamlit run app.py
```

For REST operation:

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Implemented FastAPI routes in `src/api.py` include:

```text
GET  /health
GET  /scenarios
POST /decisions/demo
POST /decisions/scenario/{event_id}
GET  /notifications/pending
GET  /auth/status
```

Authentication is implemented in `src/api.py` with `X-API-Key`. If `CHAINGUARD_API_KEYS` is absent or empty, the API runs in open mode and returns role `admin`. If `CHAINGUARD_API_KEYS` is set with values such as `key1:admin,key2:readonly`, requests must include a valid `X-API-Key` header.

For Docker operation:

```bash
docker compose up --build
```

Current compose services:

| Service | Port | Command |
|---|---|---|
| `streamlit` | `8501:8501` | `streamlit run app.py --server.port=8501 --server.address=0.0.0.0` |
| `api` | `8000:8000` | `uvicorn src.api:app --host 0.0.0.0 --port 8000` |

Both services mount:

```text
./data:/app/data
```

This preserves runtime files such as `data/experience_cards.json`, `data/model_registry.json`, and `data/audit_log.jsonl` outside the container.

Recommended enterprise run sequence:

1. Prepare a SQLite database with the tables and fields listed in §2.
2. Confirm `ScenarioLoader(db_path=...)` can list scenarios from `disruption_events`.
3. Start the UI on port `8501` or the API on port `8000`.
4. In the UI, choose enterprise scenario mode and select one event from the latest 50 scenarios.
5. Review Steps 1-11 and the sensitivity analysis.
6. Use Step 11 `human_approval_required` and `decision_id` for approval tracking.
7. Export the decision report JSON from the Streamlit download button when an archive is required.

FastAPI and Docker are implemented now. Automatic ERP writeback is not implemented; external ERP systems can call the REST API and consume JSON results, but writeback must be handled by a separate integration layer.

## §5 Fallback Behavior And Limits

ChainGuard is designed to keep the main decision flow available when optional enhancement components are absent.

| Missing or limited component | Current behavior | Impact |
|---|---|---|
| `sentence-transformers` not installed | Semantic embedding retrieval can fall back to the scikit-learn based `TfidfStore` path | Retrieval remains available with lexical TF-IDF matching |
| Ollama or Qwen unavailable | Explanation generation uses template output when LLM explanation fails | Step 10 still shows arbitration, debate, and constraint explanations |
| No historical references | Experience retrieval returns empty references and no risk hints | Step 9 shows no similar cases, while Steps 1-8 still run |
| `data/experience_cards.json` missing | Saved-card count is treated as empty until cards are generated | Step 7 can still display the current generated experience card |
| `data/model_registry.json` missing | `ModelRegistry().get_stable()` returns `None` until a model is registered | Model comparison can create registry records after evaluation |
| `ConstraintSolver` finds no fully feasible combination | Constraint result can mark `feasible=False` and still return analysis data | Step 8 remains visible for manual review |
| API key environment not configured | `src.api` uses open mode and `check_api_key(None)` returns `admin` | Existing demos and tests can run without `X-API-Key` |

Known limits:

```text
PriorClassifier is a frequency-prior baseline, not a learned feature model.
Automatic ERP writeback is not implemented.
PostgreSQL migration is documented separately in docs/production_db_migration.md, but current runtime still reads SQLite in scenario_loader and history_pipeline.
```

The current implemented production-facing capabilities are:

```text
FastAPI REST API in src/api.py
Dockerfile and docker-compose.yml deployment files
API key open/key mode authentication
MockNotifier and WebhookNotifier notification abstraction
Decision report JSON download in app.py
```
