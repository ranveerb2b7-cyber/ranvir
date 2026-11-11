"""RFC 9457 problem+json error responses with stable error codes."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"
log = structlog.get_logger()


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    def __init__(self, status: int, code: str, title: str, detail: str | None = None) -> None:
        super().__init__(detail or title)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


def problem(
    request: Request, status: int, code: str, title: str, detail: str | None = None, **extra: Any
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://docs.sellerscope.app/errors/{code}",
        "title": title,
        "status": status,
        "code": code,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
    }
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem(request, exc.status, exc.code, exc.title, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized"}.get(
            exc.status_code, "http_error"
        )
        return problem(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return problem(request, 422, "validation_error", "Request validation failed", errors=errors)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return problem(request, 500, "internal_error", "Internal server error")
