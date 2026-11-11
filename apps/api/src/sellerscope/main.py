"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from sellerscope import __version__
from sellerscope.api.v1.router import api_router
from sellerscope.core.config import AppEnv, Settings, get_settings
from sellerscope.core.errors import register_error_handlers
from sellerscope.core.logging import configure_logging
from sellerscope.core.middleware import RequestContextMiddleware
from sellerscope.db.session import create_engine, create_session_factory

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Organization-Id", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app
