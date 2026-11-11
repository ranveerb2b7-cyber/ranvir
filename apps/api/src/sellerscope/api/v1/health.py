"""Liveness and readiness probes."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(prefix="/health", tags=["health"])

CheckStatus = Literal["ok", "error"]


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckStatus]


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    """Process is up. Does not touch dependencies."""
    return LiveResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse, "description": "A dependency is unavailable"}},
)
async def ready(request: Request, response: Response) -> ReadyResponse:
    """Checks PostgreSQL and Redis. Returns 503 if either fails."""
    state = request.app.state
    timeout = state.settings.health_check_timeout_s

    async def check_db() -> CheckStatus:
        try:
            async with asyncio.timeout(timeout), state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return "ok"
        except Exception:
            return "error"

    async def check_redis() -> CheckStatus:
        try:
            async with asyncio.timeout(timeout):
                await state.redis.ping()
            return "ok"
        except Exception:
            return "error"

    db_status, redis_status = await asyncio.gather(check_db(), check_redis())
    checks: dict[str, CheckStatus] = {"database": db_status, "redis": redis_status}
    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = 503
    return ReadyResponse(status="ok" if healthy else "degraded", checks=checks)
