"""Celery tasks. Each task builds its own engine/event loop (Celery workers are synchronous)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sellerscope.alerts.delivery import deliver_all_due, deliver_pending
from sellerscope.connectors.registry import ConnectorRegistry
from sellerscope.core.config import Settings, get_settings
from sellerscope.db.session import create_engine, create_session_factory
from sellerscope.scanning.maintenance import recover_stale_work, schedule_due_scans
from sellerscope.scanning.ratelimit import TokenBucket
from sellerscope.scanning.runner import ScanDeps, run_job, utcnow
from sellerscope.services.mailer import SmtpMailer
from sellerscope.storage import create_storage
from sellerscope.uploads.dispatch import (
    ALERTS_QUEUE,
    ALERTS_TASK,
    IMPORTS_QUEUE,
    PARSE_TASK,
    SCAN_TASK,
    SCANS_QUEUE,
    CeleryDispatcher,
)
from sellerscope.workers.celery_app import celery_app


async def _with_db[T](
    fn: Callable[[Settings, async_sessionmaker[AsyncSession]], Awaitable[T]],
) -> T:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        return await fn(settings, create_session_factory(engine))
    finally:
        await engine.dispose()


@celery_app.task(name="system.ping")
def ping() -> str:
    """Round-trip check used by tests and ops tooling."""
    return "pong"


@celery_app.task(name=PARSE_TASK, queue=IMPORTS_QUEUE, acks_late=True)
def parse_upload(organization_id: str, batch_id: str) -> str:
    """Parses an uploaded product file. Failures are recorded on the batch itself."""
    from sellerscope.uploads.service import parse_batch

    async def go(settings: Settings, factory: async_sessionmaker[AsyncSession]) -> str:
        return await parse_batch(
            factory,
            create_storage(settings),
            settings,
            organization_id=uuid.UUID(organization_id),
            batch_id=uuid.UUID(batch_id),
        )

    return asyncio.run(_with_db(go))


@celery_app.task(name=SCAN_TASK, queue=SCANS_QUEUE, acks_late=True)
def run_scan_job(organization_id: str, job_id: str) -> str:
    """Processes a scan job; re-queues itself while delayed retries remain."""

    async def go(settings: Settings, factory: async_sessionmaker[AsyncSession]) -> float | None:
        redis = Redis.from_url(settings.redis_url.get_secret_value())
        try:
            deps = ScanDeps(
                session_factory=factory,
                registry=ConnectorRegistry(settings),
                limiter=TokenBucket(redis),
                storage=create_storage(settings),
                settings=settings,
            )
            return await run_job(deps, uuid.UUID(organization_id), uuid.UUID(job_id))
        finally:
            await redis.aclose()

    again_in = asyncio.run(_with_db(go))
    # Alerts raised by this run are committed; email them now rather than at the next beat.
    deliver_alerts.apply_async(args=[organization_id], queue=ALERTS_QUEUE)
    if again_in is not None:
        run_scan_job.apply_async(
            args=[organization_id, job_id], queue=SCANS_QUEUE, countdown=max(again_in, 0.5)
        )
        return f"requeued in {again_in:.1f}s"
    return "done"


@celery_app.task(name="scans.schedule_due")
def schedule_due() -> int:
    async def go(settings: Settings, factory: async_sessionmaker[AsyncSession]) -> int:
        jobs = await schedule_due_scans(
            factory,
            ConnectorRegistry(settings),
            CeleryDispatcher(),
            now=utcnow(),
            batch=settings.scan_schedule_batch,
        )
        return len(jobs)

    return asyncio.run(_with_db(go))


@celery_app.task(name="maintenance.recover_stale")
def recover_stale() -> str:
    async def go(settings: Settings, factory: async_sessionmaker[AsyncSession]) -> str:
        jobs, uploads = await recover_stale_work(
            factory, CeleryDispatcher(), stale_after_s=settings.scan_stale_after_s
        )
        return f"scan jobs: {jobs}, uploads: {uploads}"

    return asyncio.run(_with_db(go))


@celery_app.task(name=ALERTS_TASK, queue=ALERTS_QUEUE, acks_late=True)
def deliver_alerts(organization_id: str) -> str:
    """Sends pending alert emails for one organization (outcomes recorded per delivery)."""

    async def go(settings: Settings, factory: async_sessionmaker[AsyncSession]) -> str:
        report = await deliver_pending(
            factory,
            SmtpMailer(settings),
            settings,
            organization_id=uuid.UUID(organization_id),
            now=utcnow(),
        )
        return (
            f"sent {report.sent}, retrying {report.retrying}, failed {report.failed}, "
            f"skipped {report.skipped}"
        )

    return asyncio.run(_with_db(go))


@celery_app.task(name="alerts.deliver_due")
def deliver_due() -> int:
    """Beat: retries and anything a lost task message left behind."""

    async def go(settings: Settings, factory: async_sessionmaker[AsyncSession]) -> int:
        return await deliver_all_due(factory, SmtpMailer(settings), settings, now=utcnow())

    return asyncio.run(_with_db(go))
