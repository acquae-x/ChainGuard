from __future__ import annotations

import dataclasses as _dataclasses
import os
import sqlite3
import time
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.notifier import MockNotifier, NotificationPayload, Notifier, WebhookNotifier
from src.observability import Metrics, log_event
from src.orchestrator import DecisionOrchestrator
from src.scenario_loader import ScenarioLoader
from src.security.masking import mask_payload
from src.security.rbac import authenticate_role, require
from src.webapi.config import settings
from src.webapi.database import engine
from src.webapi.errors import install_error_handlers
from src.webapi.limits import limiter
from src.webapi.middleware import request_context
from src.webapi.routers import api_router


app = FastAPI(
    title="ChainGuard Decision API",
    version="1.0.0",
    description="Supply chain disruption decision engine REST interface.",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(request_context)
install_error_handlers(app)
app.include_router(api_router)


def _countersign_scheduler() -> None:
    """Run workflow timeout and overdue-task scans every five minutes."""
    from src.webapi.routers.business import release_expired_countersigns, release_overdue_tasks
    while True:
        try:
            release_expired_countersigns()
            release_overdue_tasks()
        except Exception as error:
            log_event("countersign_scheduler_failed", exception=type(error).__name__)
        time.sleep(300)


@app.on_event("startup")
def start_countersign_scheduler() -> None:
    if settings.scheduler_disabled:
        log_event("countersign_scheduler_disabled")
        return
    threading.Thread(target=_countersign_scheduler, name="chainguard-countersign-scheduler", daemon=True).start()

def _load_api_keys() -> dict[str, str]:
    """
    Parse CHAINGUARD_API_KEYS env var into a key-to-role mapping.

    Format: "key1:role1,key2:role2". Empty or absent env var enables open mode.
    """
    raw = os.environ.get("CHAINGUARD_API_KEYS", "").strip()
    if not raw:
        return {}
    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            key, role = entry.split(":", 1)
            result[key.strip()] = role.strip()
    return result


_API_KEYS: dict[str, str] = _load_api_keys()
def _build_notifier() -> Notifier:
    """仅在 URL 与显式开关同时配置时启用外部 webhook。"""
    webhook_url = os.getenv("WEBHOOK_URL", "").strip()
    enabled = os.getenv("WEBHOOK_REMOTE_ENABLED", "false").strip().lower() == "true"
    return WebhookNotifier(webhook_url) if enabled and webhook_url else MockNotifier()


_notifier: Notifier = _build_notifier()
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENTERPRISE_DB_PATH = (
    _PROJECT_ROOT
    / "demo_assets"
    / "enterprise"
    / "database"
    / "chainguard_enterprise_demo.db"
)


check_api_key = authenticate_role


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """免鉴权的纯存活探针。"""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    """就绪探针：数据库 + 令牌签名密钥。

    签名密钥必须在这里检查，不能只靠 `auth/security.py::_token` 的运行期守卫。
    少配 JWT_SECRET 的部署，数据库是通的、/healthz 是绿的、/readyz 原本也是绿的，
    于是滚动发布判定成功——直到第一个用户登录才 500，且此时旧副本已经下线。
    就绪探针的职责就是让这种配置错误在**接流量之前**暴露。
    """
    from sqlalchemy import text
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        log_event("readiness_failed", exception=type(error).__name__, message=str(error))
        raise HTTPException(status_code=503, detail="数据库未就绪") from error

    # 与 _token() 的取键逻辑保持一致：RS256 用私钥签名，其余算法用对称密钥。
    signing_key = (
        settings.jwt_rs256_private_key
        if settings.jwt_algorithm == "RS256"
        else settings.jwt_secret
    )
    if not signing_key:
        log_event("readiness_failed", reason="jwt_signing_key_missing", algorithm=settings.jwt_algorithm)
        raise HTTPException(status_code=503, detail="令牌签名密钥未配置")
    return {"status": "ready"}


@app.get("/health", deprecated=True)
def health(role: str = Depends(require("admin"))) -> dict[str, object]:
    return {
        "status": "ok",
        "version": "1.0.0",
        "dependencies": {
            "enterprise_db": _check_sqlite_database(_ENTERPRISE_DB_PATH),
            "llm": True,
            "vector_store": (_PROJECT_ROOT / "data" / "experience_cards.json").exists(),
        },
    }


# 不是弃用端点：config/prometheus.yml 按 metrics_path=/metrics 实际抓取，
# config/alerts.yml 的告警规则全部挂在这里导出的指标上。此前误标 deprecated，
# 等于在 OpenAPI 里告诉运维"这个要没了"——而它是唯一的监控接入点。
@app.get("/metrics")
def metrics(role: str = Depends(require("admin"))) -> PlainTextResponse:
    # Refresh the gauge at scrape time too, so restarts do not report a stale zero.
    from src.webapi.database import SessionLocal
    from src.webapi.jobs import sync_jobs_pending_metric
    with SessionLocal() as db:
        sync_jobs_pending_metric(db)
    return PlainTextResponse(Metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/scenarios", deprecated=True)
def list_scenarios(
    request: Request,
    limit: int = 50,
    role: str = Depends(require("view_decision")),
) -> dict[str, object]:
    """List available enterprise disruption scenarios."""
    tenant_id = _tenant_id_from_request(request)
    try:
        scenarios = ScenarioLoader(tenant_id=tenant_id).list_scenarios(limit=limit)
        return {"scenarios": scenarios, "count": len(scenarios), "tenant_id": tenant_id}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"{type(error).__name__}: {error}",
        ) from error


@app.post("/decisions/demo", deprecated=True)
def run_demo_decision(
    request: Request,
    role: str = Depends(require("run_decision")),
) -> JSONResponse:
    """Run the built-in typhoon demo decision workflow."""
    tenant_id = _tenant_id_from_request(request)
    start = time.perf_counter()
    log_event(
        "decision_started",
        endpoint="/decisions/demo",
        scenario_type="demo",
        tenant_id=tenant_id,
    )
    try:
        result = DecisionOrchestrator().run_demo()
        if result.audit_entry.get("human_approval_required"):
            _notifier.send(NotificationPayload.from_audit_entry(result.audit_entry))
        _record_decision_success(
            endpoint="/decisions/demo",
            scenario_type="demo",
            result=result.to_dict(),
            start=start,
            tenant_id=tenant_id,
        )
        payload = mask_payload(result.to_dict(), role)
        payload["tenant_id"] = tenant_id
        return JSONResponse(content=payload)
    except Exception as error:
        _record_decision_error(
            endpoint="/decisions/demo",
            scenario_type="demo",
            start=start,
            error=error,
            tenant_id=tenant_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"{type(error).__name__}: {error}",
        ) from error


@app.post("/decisions/scenario/{event_id}", deprecated=True)
def run_scenario_decision(
    event_id: str,
    request: Request,
    role: str = Depends(require("run_decision")),
) -> JSONResponse:
    """Run decision workflow for an enterprise scenario event."""
    tenant_id = _tenant_id_from_request(request)
    start = time.perf_counter()
    log_event(
        "decision_started",
        endpoint="/decisions/scenario/{event_id}",
        scenario_type="enterprise",
        event_id=event_id,
        tenant_id=tenant_id,
    )
    try:
        loader = ScenarioLoader(tenant_id=tenant_id)
        result = DecisionOrchestrator().run_scenario(event_id, loader)
        if result.audit_entry.get("human_approval_required"):
            _notifier.send(NotificationPayload.from_audit_entry(result.audit_entry))
        _record_decision_success(
            endpoint="/decisions/scenario/{event_id}",
            scenario_type="enterprise",
            result=result.to_dict(),
            start=start,
            event_id=event_id,
            tenant_id=tenant_id,
        )
        payload = mask_payload(result.to_dict(), role)
        payload["tenant_id"] = tenant_id
        return JSONResponse(content=payload)
    except ValueError as error:
        _record_decision_error(
            endpoint="/decisions/scenario/{event_id}",
            scenario_type="enterprise",
            start=start,
            error=error,
            event_id=event_id,
            tenant_id=tenant_id,
        )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        _record_decision_error(
            endpoint="/decisions/scenario/{event_id}",
            scenario_type="enterprise",
            start=start,
            error=error,
            event_id=event_id,
            tenant_id=tenant_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"{type(error).__name__}: {error}",
        ) from error


@app.get("/notifications/pending", deprecated=True)
def list_pending_notifications(
    role: str = Depends(require("approve")),
) -> dict[str, object]:
    """Return notifications accumulated by MockNotifier (demo only)."""
    if isinstance(_notifier, MockNotifier):
        return {
            "notifications": [_dataclasses.asdict(payload) for payload in _notifier.sent],
            "count": len(_notifier.sent),
        }
    return {
        "notifications": [],
        "count": 0,
        "note": "only available with MockNotifier",
    }


@app.get("/auth/status", deprecated=True)
def auth_status(role: str = Depends(check_api_key)) -> dict[str, str]:
    """Return current auth mode and caller's role."""
    mode = "open" if not _API_KEYS else "key-required"
    return {"mode": mode, "role": role}


def _check_sqlite_database(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            uri=True,
            timeout=0.2,
        ) as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        return False
    return True


def _record_decision_success(
    *,
    endpoint: str,
    scenario_type: str,
    result: dict[str, object],
    start: float,
    event_id: str | None = None,
    tenant_id: str = "default",
) -> None:
    latency_ms = _elapsed_ms(start)
    audit_entry = _as_mapping(result.get("audit_entry"))
    inventory_risk = _as_mapping(result.get("inventory_risk"))
    status = str(audit_entry.get("decision_status") or "ok")
    Metrics.inc_decision(status)
    Metrics.observe_latency(latency_ms)
    log_event(
        "decision_finished",
        endpoint=endpoint,
        scenario_type=audit_entry.get("event_type") or scenario_type,
        event_id=event_id,
        tenant_id=tenant_id,
        status=status,
        latency_ms=round(latency_ms, 3),
        risk_index=_risk_index(audit_entry, inventory_risk),
        human_approval_required=bool(audit_entry.get("human_approval_required", False)),
    )


def _record_decision_error(
    *,
    endpoint: str,
    scenario_type: str,
    start: float,
    error: Exception,
    event_id: str | None = None,
    tenant_id: str = "default",
) -> None:
    latency_ms = _elapsed_ms(start)
    Metrics.inc_decision("error")
    Metrics.observe_latency(latency_ms)
    log_event(
        "decision_failed",
        endpoint=endpoint,
        scenario_type=scenario_type,
        event_id=event_id,
        tenant_id=tenant_id,
        status="error",
        latency_ms=round(latency_ms, 3),
        exception=type(error).__name__,
        message=str(error),
    )


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _tenant_id_from_request(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", "default").strip() or "default"


def _as_mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _risk_index(
    audit_entry: dict[str, object],
    inventory_risk: dict[str, object],
) -> float | None:
    raw = (
        audit_entry.get("inventory_risk_index")
        or inventory_risk.get("inventory_risk_index")
        or inventory_risk.get("risk_index")
    )
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# 演示/单机部署：直接托管构建好的前端
#
# 目的是让答辩现场只跑一个进程、一个端口：不需要 umi dev（首屏要现编译、
# 默认堆下会 OOM、崩溃后 src/.umi 还会残留损坏产物），也不需要反向代理，
# 因而不存在前后端端口错配和 CORS 这两类现场事故。
#
# 仅当构建产物存在时才启用，因此对开发与 CI 完全无影响（那里没有 dist）。
# 路由注册在所有 API 路由之后，FastAPI 按注册顺序匹配，兜底路由不会遮蔽
# /api/v1、/healthz、/readyz、/docs 等任何既有路径。
# --------------------------------------------------------------------------

def _web_dist() -> Path | None:
    configured = os.getenv("CHAINGUARD_WEB_DIST")
    candidate = Path(configured) if configured else Path(__file__).resolve().parents[2] / "chainguard-web" / "dist"
    return candidate if (candidate / "index.html").is_file() else None


_WEB_DIST = _web_dist()

if _WEB_DIST is not None:
    from fastapi.responses import FileResponse

    @app.get("/", include_in_schema=False)
    def _spa_root() -> FileResponse:
        return FileResponse(_WEB_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa_fallback(full_path: str) -> FileResponse:
        """静态文件命中就返回文件，否则回 index.html 交给前端路由。"""
        target = (_WEB_DIST / full_path).resolve()
        # 防目录穿越：请求路径必须仍落在 dist 内，否则一律回 index.html
        if target.is_file() and target.is_relative_to(_WEB_DIST.resolve()):
            return FileResponse(target)
        return FileResponse(_WEB_DIST / "index.html")
