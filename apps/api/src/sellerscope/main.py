"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from starlette.middleware.base import RequestResponseEndpoint

from sellerscope import __version__
from sellerscope.api.v1.router import api_router
from sellerscope.auth.tokens import TokenVerifier
from sellerscope.core.config import AppEnv, Settings, get_settings
from sellerscope.core.errors import AppError, problem, register_error_handlers
from sellerscope.core.logging import configure_logging
from sellerscope.core.middleware import RequestContextMiddleware
from sellerscope.core.rate_limit import RateLimiter, client_ip
from sellerscope.db.session import create_engine, create_session_factory
from sellerscope.services.mailer import SmtpMailer
from sellerscope.storage import create_storage
from sellerscope.uploads.dispatch import CeleryDispatcher

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.app_env != AppEnv.DEVELOPMENT)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.redis = Redis.from_url(settings.redis_url.get_secret_value())
        app.state.rate_limiter = RateLimiter(app.state.redis, enabled=settings.rate_limit_enabled)
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await engine.dispose()

    docs_enabled = not settings.is_production_like
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json" if docs_enabled else None,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.token_verifier = TokenVerifier(settings)
    app.state.mailer = SmtpMailer(settings)
    app.state.storage = create_storage(settings)
    app.state.task_dispatcher = CeleryDispatcher()

    @app.middleware("http")
    async def ip_rate_limit(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Coarse per-IP limit on the API (health probes excluded)."""
        path = request.url.path
        limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if limiter and path.startswith(API_PREFIX) and not path.startswith(f"{API_PREFIX}/health"):
            try:
                await limiter.check(
                    f"ip:{client_ip(request)}", settings.rate_limit_ip_per_minute, 60
                )
            except AppError as exc:
                return problem(request, exc.status, exc.code, exc.title, exc.detail, exc.headers)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Organization-Id", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app
