# ChainGuard API SLA

## Measurement Method

The production decision path is tenant-aware and asynchronous:

```text
POST /api/v1/incidents/{incident_id}/proposals:generate
GET  /api/v1/jobs/{job_id}
```

Measure request acceptance latency, queue wait, persisted job execution time,
end-to-end terminal time, and error rate separately. A 202 response means the
job was accepted; it is not decision completion.

The former root decision endpoints and `benchmarks/test_api_perf.py` were
removed together. That benchmark measured an unsupported cross-tenant
file-state path, so its historical P50/P95 values are not an SLA for the
current workflow. `pytest benchmarks/` now retains the history-pipeline scale
benchmark only.

## Environment

Record the actual machine profile with each benchmark run:

| Item | Value |
|---|---|
| CPU | TBD by deployment or CI runner |
| Memory | TBD by deployment or CI runner |
| Python | TBD by deployment or CI runner |
| OS | TBD by deployment or CI runner |
| Storage | Local workspace or CI ephemeral disk |

Record the same profile for tenant workflow load tests; the remaining
in-repository scale benchmark is not a replacement for production load testing.

## SLA Targets

Establish numeric targets from representative tenant datasets and deployed
worker capacity before publishing an external SLA. Do not carry over the
deleted synchronous endpoint thresholds.

## Resource Notes

Decision execution performs rule evaluation, experience retrieval, constraint
solving, explanation generation, and persisted audit/workflow updates. The
dominant resources are CPU, database I/O, and configured model-provider latency.

Operational dashboards should track:

- `/metrics` decision counters and latency observations
- API HTTP 5xx rate
- process CPU and memory
- audit log write failures
- database and JWT readiness from `/readyz`

## Degradation Guidance

If end-to-end job latency rises:

1. Check `chainguard_jobs_pending` and worker availability.
2. Separate queue wait from execution time using persisted job timestamps.
3. Inspect structured logs for ERP, model-provider, persistence, and recovery
   failures.
4. Reduce admission concurrency before increasing workers.
5. Increase workers only after confirming shared persistence and rate-limit
   storage remain safe at the new concurrency.

If Prometheus scrapes return 401/403, verify the metrics JWT signature, scope,
expiry, mounted credential file, and reload state. Never restore unauthenticated
scraping as a recovery shortcut.
