from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from threading import Lock
from typing import Any


def log_event(event: str, **fields: Any) -> None:
    """Emit one structured JSON log line to stdout."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False, default=str), file=sys.stdout, flush=True)


class _Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._setup_backend()

    def _setup_backend(self) -> None:
        try:
            from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
        except Exception:
            self._prometheus = False
            self._decisions: dict[str, int] = {}
            self._errors: dict[str, int] = {}
            self._latency_count = 0
            self._latency_sum = 0.0
            self._http: dict[tuple[str, str, str], int] = {}
            return

        self._prometheus = True
        self._generate_latest = generate_latest
        self._registry = CollectorRegistry()
        self._decision_counter = Counter(
            "chainguard_decisions",
            "Total ChainGuard decision requests by status.",
            ["status"],
            registry=self._registry,
        )
        self._error_counter = Counter(
            "chainguard_decision_errors",
            "Total ChainGuard decision errors by status.",
            ["status"],
            registry=self._registry,
        )
        self._latency_histogram = Histogram(
            "chainguard_decision_latency_ms",
            "ChainGuard decision latency in milliseconds.",
            registry=self._registry,
            buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
        )
        self._http_counter = Counter(
            "chainguard_http_requests",
            "Total HTTP requests by method, path and status.",
            ["method", "path", "status"],
            registry=self._registry,
        )
        self._http_latency = Histogram(
            "chainguard_http_latency_ms",
            "HTTP request latency in milliseconds.",
            ["method", "path"],
            registry=self._registry,
        )

    def reset(self) -> None:
        """Reset metrics state for tests and local smoke checks."""
        with self._lock:
            self._setup_backend()

    def inc_decision(self, status: str) -> None:
        normalized = str(status or "unknown")
        with self._lock:
            if self._prometheus:
                self._decision_counter.labels(status=normalized).inc()
                if normalized in {"error", "failed", "exception"}:
                    self._error_counter.labels(status=normalized).inc()
                return
            self._decisions[normalized] = self._decisions.get(normalized, 0) + 1
            if normalized in {"error", "failed", "exception"}:
                self._errors[normalized] = self._errors.get(normalized, 0) + 1

    def observe_latency(self, ms: float) -> None:
        value = max(float(ms), 0.0)
        with self._lock:
            if self._prometheus:
                self._latency_histogram.observe(value)
                return
            self._latency_count += 1
            self._latency_sum += value

    def observe_http(self, method: str, path: str, status: int, ms: float) -> None:
        """记录 HTTP 层请求量与耗时。"""
        with self._lock:
            if self._prometheus:
                self._http_counter.labels(method=method, path=path, status=str(status)).inc()
                self._http_latency.labels(method=method, path=path).observe(max(float(ms), 0.0))
                return
            key = (method, path, str(status))
            self._http[key] = self._http.get(key, 0) + 1

    def render(self) -> str:
        with self._lock:
            if self._prometheus:
                return self._generate_latest(self._registry).decode("utf-8")

            lines = [
                "# HELP chainguard_decisions_total Total ChainGuard decision requests by status.",
                "# TYPE chainguard_decisions_total counter",
            ]
            for status, count in sorted(self._decisions.items()):
                lines.append(
                    f'chainguard_decisions_total{{status="{_escape_label(status)}"}} {count}'
                )
            lines.extend(
                [
                    "# HELP chainguard_decision_errors_total Total ChainGuard decision errors by status.",
                    "# TYPE chainguard_decision_errors_total counter",
                ]
            )
            for status, count in sorted(self._errors.items()):
                lines.append(
                    f'chainguard_decision_errors_total{{status="{_escape_label(status)}"}} {count}'
                )
            lines.extend(
                [
                    "# HELP chainguard_decision_latency_ms ChainGuard decision latency in milliseconds.",
                    "# TYPE chainguard_decision_latency_ms summary",
                    f"chainguard_decision_latency_ms_count {self._latency_count}",
                    f"chainguard_decision_latency_ms_sum {self._latency_sum:.6f}",
                ]
            )
            lines.extend([
                "# HELP chainguard_http_requests_total Total HTTP requests.",
                "# TYPE chainguard_http_requests_total counter",
            ])
            for (method, path, status), count in sorted(self._http.items()):
                lines.append(f'chainguard_http_requests_total{{method="{_escape_label(method)}",path="{_escape_label(path)}",status="{_escape_label(status)}"}} {count}')
            return "\n".join(lines) + "\n"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


Metrics = _Metrics()
