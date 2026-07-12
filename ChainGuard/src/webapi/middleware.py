from __future__ import annotations

import time
import uuid

from fastapi import Request

from src.observability import Metrics, log_event


async def request_context(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
    request.state.trace_id = trace_id
    started = time.perf_counter()
    response = await call_next(request)
    latency = (time.perf_counter() - started) * 1000
    response.headers["X-Trace-Id"] = trace_id
    Metrics.observe_http(request.method, request.url.path, response.status_code, latency)
    log_event("http_request", trace_id=trace_id, method=request.method, path=request.url.path, status=response.status_code, latency_ms=round(latency, 3))
    return response

