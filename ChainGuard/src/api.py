from __future__ import annotations

import os
import time
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.observability import Metrics, log_event
from src.webapi.jwt_tokens import require_metrics_token
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


durable_job_worker = None


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


@app.on_event("startup")
def recover_stale_jobs_on_startup() -> None:
    """回收上次进程遗留的 pending/running 作业；多 worker 下实现是幂等的。"""
    from src.webapi.job_recovery import recover_stale_jobs_on_startup as _recover

    _recover()


@app.on_event("startup")
def start_durable_job_worker() -> None:
    global durable_job_worker
    from src.webapi.jobs import DurableJobWorker

    durable_job_worker = DurableJobWorker()
    durable_job_worker.start()


@app.on_event("shutdown")
def stop_durable_job_worker() -> None:
    if durable_job_worker is not None:
        durable_job_worker.stop()


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


# 不是弃用端点：config/prometheus.yml 按 metrics_path=/metrics 实际抓取，
# config/alerts.yml 的告警规则全部挂在这里导出的指标上。此前误标 deprecated，
# 等于在 OpenAPI 里告诉运维"这个要没了"——而它是唯一的监控接入点。
@app.get("/metrics")
def metrics(_: str = Depends(require_metrics_token)) -> PlainTextResponse:
    # Refresh the gauge at scrape time too, so restarts do not report a stale zero.
    from src.webapi.database import SessionLocal
    from src.webapi.jobs import sync_jobs_pending_metric
    with SessionLocal() as db:
        sync_jobs_pending_metric(db)
    return PlainTextResponse(Metrics.render(), media_type="text/plain; version=0.0.4")


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
