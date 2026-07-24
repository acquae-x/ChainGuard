# ChainGuard Production Database Migration: SQLite To PostgreSQL

## Runnable I37 Migration Path

ChainGuard still defaults to SQLite when `DATABASE_URL` is not set. PostgreSQL
is optional and uses the new `src.db.get_connection()` URL convention:

```text
sqlite:///path/to/database.db
postgresql://user:password@host:5432/database
```

Start the optional local PostgreSQL service:

```powershell
docker compose --profile postgres up -d postgres
```

Install the optional PostgreSQL driver. SQLite-only development and tests do not
need this package.

```powershell
python -m pip install "psycopg[binary]>=3"
```

Set the target URL:

```powershell
$env:DATABASE_URL = "postgresql://chainguard:chainguard_secret@localhost:5432/chainguard_prod"
```

Run the migration from the enterprise SQLite database:

```powershell
python scripts/migrate_to_postgres.py `
  --sqlite demo_assets/enterprise/database/chainguard_enterprise_demo.db `
  --postgres-url $env:DATABASE_URL `
  --truncate
```

The migration script creates every SQLite table with
`CREATE TABLE IF NOT EXISTS`, inserts rows in batches, and prints one migrated
row count per table.

Verify PostgreSQL tables:

```powershell
docker compose --profile postgres exec postgres `
  psql -U chainguard -d chainguard_prod `
  -c "SELECT schemaname, relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"
```

Run a timestamped backup into `backups/postgres`:

```powershell
docker compose --profile postgres --profile postgres-backup run --rm postgres-backup
```

Manual backup and restore:

```powershell
docker compose --profile postgres exec postgres `
  pg_dump -U chainguard -d chainguard_prod `
  > backups/postgres/chainguard_prod.sql

docker compose --profile postgres exec -T postgres `
  psql -U chainguard -d chainguard_prod `
  < backups/postgres/chainguard_prod.sql
```

For app processes that should use PostgreSQL-aware code paths, pass
`DATABASE_URL` in the process environment. Existing `ScenarioLoader` and
`HistoryPipeline` calls intentionally keep explicit SQLite URLs so their current
SQLite SQL dialect and test behavior remain unchanged.

## §1 Current SQLite Data Architecture

ChainGuard currently uses a single SQLite demo database for enterprise scenario data:

```text
demo_assets/enterprise/database/chainguard_enterprise_demo.db
```

The demo database contains 18 business tables confirmed by the enterprise dataset.

Core business tables:

```text
historical_decisions
disruption_events
materials
suppliers
inventory
warehouses
customers
```

Supply-chain operations tables:

```text
sales_orders
sales_order_lines
purchase_orders
purchase_order_lines
shipments
inventory_movements
inventory_snapshots
production_plans
supplier_materials
supplier_performance
quality_inspections
```

Runtime files outside SQLite:

```text
data/audit_log.jsonl
data/experience_cards.json
data/model_registry.json
data/pipeline_state.json
```

These JSON and JSONL files are not part of the SQLite database. They should be handled as separate production persistence concerns.

The two current source files that directly use `sqlite3` are:

| File | Current responsibility | Main tables |
|---|---|---|
| `src/history_pipeline.py` | Opens `sqlite3.connect(self.db_path)` to ingest and load historical training records | `historical_decisions` |
| `src/scenario_loader.py` | Opens `sqlite3.connect(...)` to load disruption scenario context | `disruption_events`, `materials`, `inventory`, `supplier_materials`, `suppliers`, `sales_orders`, `sales_order_lines` |

In the current implementation, `history_pipeline` and `scenario_loader` resolve the default database path to `demo_assets/enterprise/database/chainguard_enterprise_demo.db`.

## §2 Migration Prerequisites

Install the PostgreSQL driver and optional migration helper:

```bash
pip install "psycopg2-binary>=2.9"
pip install pgloader
```

`psycopg2-binary` provides the `psycopg2` driver without requiring local compilation. `pgloader` is optional but recommended for one-pass SQLite to PostgreSQL data migration.

Target PostgreSQL environment:

```text
PostgreSQL version: 14 or newer
database name: chainguard_prod
schema name: chainguard
connection URL format: postgresql://user:password@host:5432/chainguard_prod
```

Production code should read the database connection string from:

```text
CHAINGUARD_DATABASE_URL
```

Example:

```bash
export CHAINGUARD_DATABASE_URL="postgresql://chainguard:chainguard_secret@localhost:5432/chainguard_prod"
```

Before migration, take a copy of the current SQLite file:

```bash
cp demo_assets/enterprise/database/chainguard_enterprise_demo.db \
  demo_assets/enterprise/database/chainguard_enterprise_demo.backup.db
```

## §3 Schema Migration Steps

Step 1: export the current SQLite DDL.

```bash
sqlite3 demo_assets/enterprise/database/chainguard_enterprise_demo.db .schema > schema.sql
```

Step 2: convert SQLite DDL to PostgreSQL-compatible DDL.

Common type and syntax adjustments:

| SQLite | PostgreSQL equivalent |
|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` or `BIGSERIAL PRIMARY KEY` |
| `TEXT` | `TEXT`, or `VARCHAR(N)` when a length constraint is needed |
| `REAL` | `DOUBLE PRECISION`, or `NUMERIC(12,4)` for financial values |
| SQLite file-level database | PostgreSQL database plus optional `chainguard` schema |
| `DATETIME` stored as text | `TIMESTAMP` or `TIMESTAMPTZ`, depending on production timezone policy |

Recommended schema prefix:

```sql
CREATE SCHEMA IF NOT EXISTS chainguard;
SET search_path TO chainguard;
```

Step 3: create the PostgreSQL schema.

```bash
createdb chainguard_prod
psql chainguard_prod -c "CREATE SCHEMA IF NOT EXISTS chainguard;"
psql chainguard_prod -f schema_pg.sql
```

Step 4: migrate data.

Recommended `pgloader` path:

```bash
pgloader demo_assets/enterprise/database/chainguard_enterprise_demo.db \
  postgresql://user:password@localhost:5432/chainguard_prod
```

Manual CSV fallback path:

```bash
sqlite3 -header -csv demo_assets/enterprise/database/chainguard_enterprise_demo.db \
  "SELECT * FROM historical_decisions" > historical_decisions.csv

sqlite3 -header -csv demo_assets/enterprise/database/chainguard_enterprise_demo.db \
  "SELECT * FROM disruption_events" > disruption_events.csv

psql chainguard_prod -c "\COPY historical_decisions FROM 'historical_decisions.csv' CSV HEADER"
psql chainguard_prod -c "\COPY disruption_events FROM 'disruption_events.csv' CSV HEADER"
```

Repeat the CSV export/import process for all 18 tables.

Step 5: verify row counts.

```sql
SELECT 'historical_decisions' AS table_name, COUNT(*) FROM historical_decisions
UNION ALL
SELECT 'disruption_events', COUNT(*) FROM disruption_events
UNION ALL
SELECT 'materials', COUNT(*) FROM materials
UNION ALL
SELECT 'suppliers', COUNT(*) FROM suppliers
UNION ALL
SELECT 'inventory', COUNT(*) FROM inventory;
```

Compare these counts against the original SQLite database before switching application traffic.

## §4 Application Code Change Plan

This document does not change code. The production migration will require replacing the connection layer in exactly the modules that currently use SQLite:

```text
src/history_pipeline.py
src/scenario_loader.py
```

Current `src/history_pipeline.py` pattern:

```python
import sqlite3

with sqlite3.connect(self.db_path) as connection:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT * FROM historical_decisions WHERE created_at <= ?",
        (cutoff_time,),
    )
```

PostgreSQL replacement pattern with `psycopg2`:

```python
import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ["CHAINGUARD_DATABASE_URL"]

with psycopg2.connect(DATABASE_URL) as connection:
    with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute(
            "SELECT * FROM historical_decisions WHERE created_at <= %s",
            (cutoff_time,),
        )
        rows = cursor.fetchall()
```

Current `src/scenario_loader.py` pattern:

```python
import sqlite3

connection = sqlite3.connect(self.db_path)
connection.row_factory = sqlite3.Row
```

PostgreSQL replacement pattern:

```python
import os
import psycopg2
import psycopg2.extras

connection = psycopg2.connect(os.environ["CHAINGUARD_DATABASE_URL"])
cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
```

SQL query compatibility notes:

| Current location | Migration concern |
|---|---|
| `history_pipeline` queries on `historical_decisions` | Replace SQLite `?` placeholders with PostgreSQL `%s` placeholders |
| `scenario_loader` queries on `disruption_events`, `materials`, `inventory`, `supplier_materials`, `suppliers`, `sales_orders`, `sales_order_lines` | Replace placeholders and row access with dict-style cursor rows |
| `scenario_loader` uses `JULIANDAY(...)` in delivery-hour calculation | Replace with PostgreSQL timestamp arithmetic, for example `EXTRACT(EPOCH FROM (promised_delivery_at::timestamp - NOW())) / 3600` |

Most table joins and filters are standard SQL. The main code changes are connection creation, placeholder style, row conversion, and the SQLite-specific `JULIANDAY` expression.

Recommended transition strategy:

1. Add a small database adapter that chooses SQLite when `CHAINGUARD_DATABASE_URL` is absent.
2. Use PostgreSQL when `CHAINGUARD_DATABASE_URL` starts with `postgresql://`.
3. Keep existing SQLite behavior for local demos and tests.
4. Add integration tests against a disposable PostgreSQL service after the adapter is introduced.

## §5 Docker Compose Integration

The runtime UI service is `web` (nginx serving the built React app and proxying
`/api/` to `api`); there is no Streamlit service. The production `docker-compose`
adds a `postgres` service and passes `CHAINGUARD_DATABASE_URL` to the application services.

Example:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: chainguard_prod
      POSTGRES_USER: chainguard
      POSTGRES_PASSWORD: chainguard_secret
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./schema_pg.sql:/docker-entrypoint-initdb.d/01_schema.sql

  api:
    build: .
    depends_on:
      - postgres
    environment:
      - PYTHONUNBUFFERED=1
      - CHAINGUARD_DATABASE_URL=postgresql://chainguard:chainguard_secret@postgres:5432/chainguard_prod
    ports:
      - "8000:8000"
    command: uvicorn src.api:app --host 0.0.0.0 --port 8000

volumes:
  pgdata:
```

Deployment checklist:

1. Build and start PostgreSQL with `docker-compose up postgres`.
2. Apply `schema_pg.sql` or mount it into `/docker-entrypoint-initdb.d/01_schema.sql`.
3. Load data from SQLite with `pgloader` or CSV imports.
4. Set `CHAINGUARD_DATABASE_URL` for the `api` service.
5. Start the full stack with `docker-compose up --build`.
6. Verify `GET /healthz` and `GET /readyz`, then exercise the tenant-aware
   `/api/v1` incident and asynchronous proposal-generation workflow with a
   valid user JWT.

Until the code adapter is implemented, this PostgreSQL compose configuration is a migration target, not the current runtime behavior.
