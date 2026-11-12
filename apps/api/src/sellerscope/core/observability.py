"""Metrics (Prometheus) and optional error tracking (Sentry).

HTTP metrics are recorded per API process. Background work runs in separate Celery
processes, so its health is measured at scrape time instead: queue lengths from Redis and
backlog/failure counts from the database (ops_metrics(), counts only, migration 0010).
"""

from __future__ import annotations

import hmac
import time
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import text

from sellerscope.core.config import Settings
from sellerscope.workers.queues import QUEUES

log = structlog.get_logger()

API_PREFIX = "/api/v1"
BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
OPS_FIELDS = (
    ("scan_items_pending", "Scan items waiting to be processed"),
    ("scan_items_processing", "Scan items being processed"),
    ("oldest_pending_scan_item_s", "Age in seconds of the oldest due scan item"),
    ("scan_results_last_hour", "Scan results recorded in the last hour"),
    ("scan_errors_last_hour", "Failed scan results recorded in the last hour"),
    ("alert_deliveries_pending", "Alert emails waiting to be sent"),
    ("alert_deliveries_failed", "Alert emails that gave up after all retries"),
    ("reports_active", "Report exports queued or running"),
    ("reports_failed_last_day", "Report exports that failed in the last day"),
)


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.requests = Counter(
            "sellerscope_http_requests_total",
            "HTTP requests",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "sellerscope_http_request_duration_seconds",
            "HTTP request duration",
            ["method", "route"],
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.queue_length = Gauge(
            "sellerscope_queue_length",
            "Messages waiting in a Celery queue",
            ["queue"],
            registry=self.registry,
        )
        self.ops = {
            name: Gauge(f"sellerscope_{name}", doc, registry=self.registry)
            for name, doc in OPS_FIELDS
        }
        self.scrape_errors = Counter(
            "sellerscope_metrics_scrape_errors_total",
            "Failures while collecting scrape-time metrics",
            ["source"],
            registry=self.registry,
        )

    async def refresh(self, app: FastAPI) -> None:
        try:
            async with app.state.session_factory() as session:
                row = (await session.execute(text("SELECT * FROM ops_metrics()"))).one()
            for (name, _), value in zip(OPS_FIELDS, row, strict=True):
                self.ops[name].set(float(value))
        except Exception:  # reported as a metric and a log line; the scrape still succeeds
            self.scrape_errors.labels("database").inc()
            log.exception("metrics_database_failed")
        try:
            for queue in QUEUES:
                self.queue_length.labels(queue).set(await app.state.redis.llen(queue))
        except Exception:
            self.scrape_errors.labels("redis").inc()
            log.exception("metrics_redis_failed")


def route_of(request: Request) -> str:
    """The route TEMPLATE (e.g. /api/v1/products/{product_id}): bounded label cardinality."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not template:
        return "unmatched"
    # Included routers report their path without the app-level API prefix.
    if request.url.path.startswith(API_PREFIX) and not template.startswith(API_PREFIX):
        template = API_PREFIX + template
    return str(template)


def install(app: FastAPI, settings: Settings) -> None:
    metrics = Metrics()
    app.state.metrics = metrics

    @app.middleware("http")
    async def record(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = route_of(request)
            if route != "/metrics":
                metrics.requests.labels(request.method, route, str(status)).inc()
                metrics.latency.labels(request.method, route).observe(time.perf_counter() - started)

    @app.get("/metrics", include_in_schema=False)
    async def scrape(request: Request) -> Response:
        token = settings.metrics_token.get_secret_value() if settings.metrics_token else None
        if token:
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        await metrics.refresh(request.app)
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)


def init_sentry(settings: Settings, *, component: str) -> bool:
    """Error tracking, only when SENTRY_DSN is set. Never sends request bodies or user PII."""
    if not settings.sentry_dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.app_env,
        release=f"sellerscope@{settings.release}",
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        server_name=component,
    )
    return True
