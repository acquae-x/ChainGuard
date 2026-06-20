from __future__ import annotations

import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from fastapi.testclient import TestClient

from src.api import app


SERIAL_SAMPLES = int(os.environ.get("CHAINGUARD_API_PERF_SAMPLES", "20"))
CONCURRENT_REQUESTS = int(os.environ.get("CHAINGUARD_API_PERF_CONCURRENCY_TOTAL", "20"))
CONCURRENT_WORKERS = int(os.environ.get("CHAINGUARD_API_PERF_WORKERS", "4"))
DEMO_P95_THRESHOLD_MS = float(os.environ.get("CHAINGUARD_DEMO_P95_THRESHOLD_MS", "2000"))
SCENARIO_P95_THRESHOLD_MS = float(
    os.environ.get("CHAINGUARD_SCENARIO_P95_THRESHOLD_MS", "2500")
)
SCENARIO_EVENT_ID = os.environ.get("CHAINGUARD_API_PERF_SCENARIO_ID", "EVT-000006")


@dataclass(frozen=True)
class PerfStats:
    endpoint: str
    samples: int
    ok_count: int
    error_count: int
    p50_ms: float
    p95_ms: float
    elapsed_s: float
    qps: float


def test_demo_decision_p95_under_threshold():
    stats = _measure_serial("POST", "/decisions/demo", samples=SERIAL_SAMPLES)

    _print_stats("serial-demo", stats)
    assert stats.error_count == 0
    assert stats.p95_ms < DEMO_P95_THRESHOLD_MS


def test_scenario_decision_perf_smoke():
    stats = _measure_serial(
        "POST",
        f"/decisions/scenario/{SCENARIO_EVENT_ID}",
        samples=SERIAL_SAMPLES,
    )

    _print_stats("serial-scenario", stats)
    assert stats.error_count == 0
    assert stats.p95_ms < SCENARIO_P95_THRESHOLD_MS


def test_concurrent_requests_no_errors():
    stats = _measure_concurrent(
        "POST",
        "/decisions/demo",
        total_requests=CONCURRENT_REQUESTS,
        max_workers=CONCURRENT_WORKERS,
    )

    _print_stats("concurrent-demo", stats)
    assert stats.error_count == 0


def _measure_serial(method: str, endpoint: str, samples: int) -> PerfStats:
    client = TestClient(app)
    _request(client, method, endpoint)

    elapsed_values: list[float] = []
    ok_count = 0
    started = time.perf_counter()
    for _ in range(samples):
        status_code, elapsed_ms = _timed_request(client, method, endpoint)
        elapsed_values.append(elapsed_ms)
        if status_code < 500:
            ok_count += 1
    elapsed_s = time.perf_counter() - started

    return _stats(endpoint, elapsed_values, ok_count, elapsed_s)


def _measure_concurrent(
    method: str,
    endpoint: str,
    *,
    total_requests: int,
    max_workers: int,
) -> PerfStats:
    elapsed_values: list[float] = []
    ok_count = 0
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_one_thread_request, method, endpoint)
            for _ in range(total_requests)
        ]
        for future in as_completed(futures):
            status_code, elapsed_ms = future.result()
            elapsed_values.append(elapsed_ms)
            if status_code < 500:
                ok_count += 1
    elapsed_s = time.perf_counter() - started

    return _stats(endpoint, elapsed_values, ok_count, elapsed_s)


def _one_thread_request(method: str, endpoint: str) -> tuple[int, float]:
    client = TestClient(app)
    return _timed_request(client, method, endpoint)


def _timed_request(
    client: TestClient,
    method: str,
    endpoint: str,
) -> tuple[int, float]:
    started = time.perf_counter()
    response = _request(client, method, endpoint)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return response.status_code, elapsed_ms


def _request(client: TestClient, method: str, endpoint: str):
    if method == "POST":
        return client.post(endpoint)
    if method == "GET":
        return client.get(endpoint)
    raise ValueError(f"unsupported method: {method}")


def _stats(
    endpoint: str,
    elapsed_values: list[float],
    ok_count: int,
    elapsed_s: float,
) -> PerfStats:
    error_count = len(elapsed_values) - ok_count
    return PerfStats(
        endpoint=endpoint,
        samples=len(elapsed_values),
        ok_count=ok_count,
        error_count=error_count,
        p50_ms=statistics.median(elapsed_values),
        p95_ms=_percentile(elapsed_values, 95),
        elapsed_s=elapsed_s,
        qps=len(elapsed_values) / max(elapsed_s, 0.001),
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = int(round((len(ordered) - 1) * percentile / 100))
    return ordered[index]


def _print_stats(label: str, stats: PerfStats) -> None:
    print(
        f"{label}: endpoint={stats.endpoint} samples={stats.samples} "
        f"ok={stats.ok_count} errors={stats.error_count} "
        f"p50={stats.p50_ms:.1f}ms p95={stats.p95_ms:.1f}ms "
        f"elapsed={stats.elapsed_s:.2f}s qps={stats.qps:.2f}"
    )
