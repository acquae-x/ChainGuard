# ChainGuard Decision API SLA

## Measurement Method

Run the in-process FastAPI benchmark with:

```bash
python -m pytest benchmarks/test_api_perf.py -v -s
```

The benchmark performs one warmup request, then samples each measured endpoint
multiple times with `fastapi.testclient.TestClient`. It reports P50, P95,
elapsed time, approximate QPS, and error count for:

- `POST /decisions/demo`
- `POST /decisions/scenario/{event_id}`
- light concurrent `POST /decisions/demo` traffic

Concurrency uses `ThreadPoolExecutor`; each worker creates its own independent
`TestClient(app)` instance to avoid cross-thread client sharing.

Default knobs:

| Variable | Default | Purpose |
|---|---:|---|
| `CHAINGUARD_API_PERF_SAMPLES` | `20` | Serial sample count per endpoint |
| `CHAINGUARD_API_PERF_CONCURRENCY_TOTAL` | `20` | Total concurrent demo requests |
| `CHAINGUARD_API_PERF_WORKERS` | `4` | Concurrent worker count |
| `CHAINGUARD_DEMO_P95_THRESHOLD_MS` | `2000` | Demo decision P95 gate |
| `CHAINGUARD_SCENARIO_P95_THRESHOLD_MS` | `2500` | Scenario decision P95 gate |
| `CHAINGUARD_API_PERF_SCENARIO_ID` | `EVT-000006` | Scenario event used by the benchmark |

## Environment

Record the actual machine profile with each benchmark run:

| Item | Value |
|---|---|
| CPU | TBD by deployment or CI runner |
| Memory | TBD by deployment or CI runner |
| Python | TBD by deployment or CI runner |
| OS | TBD by deployment or CI runner |
| Storage | Local workspace or CI ephemeral disk |

The in-repository benchmark is intended as a repeatable smoke baseline, not a
replacement for external production load testing.

## SLA Targets

| Endpoint | Target |
|---|---:|
| `POST /decisions/demo` P95 latency | `< 2000 ms` |
| `POST /decisions/scenario/{event_id}` P95 latency | `< 2500 ms` |
| Light concurrent demo requests | `0` HTTP 5xx responses |

The recommended initial concurrency limit is 4 in-flight decision requests per
single Uvicorn worker. Raise this only after confirming P95 latency and memory
headroom in the target environment.

## Latest Local Benchmark

Latest run on the local development environment:

| Case | Samples | P50 | P95 | Approx QPS | Errors |
|---|---:|---:|---:|---:|---:|
| Serial demo decision | 20 | 1295.2 ms | 1306.4 ms | 0.77 | 0 |
| Serial scenario decision (`EVT-000006`) | 20 | 1309.9 ms | 1326.2 ms | 0.76 | 0 |
| Concurrent demo decision, 4 workers | 20 | 1442.2 ms | 1541.7 ms | 2.78 | 0 |

## Resource Notes

Decision execution performs deterministic rule evaluation, experience retrieval,
constraint solving, explanation generation, audit append, and optional
notification logic. The dominant resources are CPU time for in-process decision
steps and local file/database I/O for experience and audit persistence.

Operational dashboards should track:

- `/metrics` decision counters and latency observations
- API HTTP 5xx rate
- process CPU and memory
- audit log write failures
- scenario database availability from `/health`

## Degradation Guidance

If P95 latency exceeds the SLA target:

1. Reduce concurrent decision requests at the API gateway or worker queue.
2. Prefer cached scenario lists and avoid repeated nonessential decision calls.
3. Disable or defer optional outbound notifications until the API recovers.
4. Run more Uvicorn workers only after confirming shared file/database writes
   remain healthy.
5. Inspect `/metrics` and structured decision logs to separate compute latency
   from error retries or dependency failures.

If the error rate rises under light concurrency, keep traffic at single-request
mode and investigate local persistence, database availability, and recent
configuration changes before raising concurrency.
