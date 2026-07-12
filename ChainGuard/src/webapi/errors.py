from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from src.observability import log_event


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


def envelope(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "traceId": request.state.trace_id},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return envelope(request, error.status_code, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        log_event("request_validation_failed", trace_id=request.state.trace_id, errors=error.errors())
        return envelope(request, 422, "CG-1001", "请求参数不合法")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        messages = {401: "请先登录", 403: "没有操作权限", 404: "资源不存在", 409: "当前状态不允许此操作"}
        message = "服务暂时不可用，请稍后重试" if error.status_code >= 500 else messages.get(error.status_code, str(error.detail))
        return envelope(request, error.status_code, f"CG-{error.status_code:04d}", message)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        log_event("unhandled_error", trace_id=request.state.trace_id, exception=type(error).__name__, message=str(error))
        return envelope(request, 500, "CG-5000", "服务暂时不可用，请稍后重试")

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(request: Request, error: RateLimitExceeded) -> JSONResponse:
        return envelope(request, 429, "CG-1006", "请求过于频繁，请稍后重试")
