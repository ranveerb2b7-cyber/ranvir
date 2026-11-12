"""Periodic work (Celery beat): scheduled scans and recovery of stuck jobs/uploads."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sellerscope.connectors.base import ConnectorUnavailableError
from sellerscope.connectors.registry import ConnectorRegistry
from sellerscope.core.errors import AppError
from sellerscope.db.tenant import set_tenant_context
from sellerscope.models.enums import ScanTrigger
from sellerscope.scanning.jobs import create_scan_job
from sellerscope.uploads.dispatch import TaskDispatcher

log = structlog.get_logger()


async def schedule_due_scans(
    session_factory: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    dispatcher: TaskDispatcher,
    *,
    now: datetime,
    batch: int,
) -> list[uuid.UUID]:
    """Creates one scheduled job per organization for its due products. Returns job ids."""
    async with session_factory() as session:
        rows = (
            await session.execute(text("SELECT * FROM due_scan_products(:n)"), {"n": batch})
        ).all()
    by_org: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for org, product in rows:
        by_org[org].append(product)

    jobs: list[uuid.UUID] = []
    for org, products in by_org.items():
        try:
            async with session_factory() as session, session.begin():
                await set_tenant_context(session, organization_id=org, user_id=None)
                await registry.resolve(session, org, "amazon_in")
                created = await create_scan_job(
                    session,
                    organization_id=org,
                    requested_by=None,
                    product_ids=products,
                    trigger=ScanTrigger.SCHEDULED,
                    now=now,
                    cap_to_quota=True,
                )
                job_id = created.job.id
        except ConnectorUnavailableError:
            log.info(
                "scheduled_scan_skipped",
                organization_id=str(org),
                reason="connector_unavailable",
                products=len(products),
            )
            continue
        except AppError as exc:  # quota exhausted, products already running
            log.info(
                "scheduled_scan_skipped",
                organization_id=str(org),
                reason=exc.code,
                products=len(products),
            )
            continue
        await dispatcher.run_scan_job(org, job_id)
        jobs.append(job_id)
    return jobs


async def recover_stale_work(
    session_factory: async_sessionmaker[AsyncSession],
    dispatcher: TaskDispatcher,
    *,
    stale_after_s: int,
) -> tuple[int, int]:
    """Re-queues work a lost worker or message left behind. Returns (scan jobs, uploads)."""
    async with session_factory() as session, session.begin():
        jobs = (
            await session.execute(
                text("SELECT * FROM reset_stale_scan_items(:s)"), {"s": stale_after_s}
            )
        ).all()
        uploads = (
            await session.execute(
                text("SELECT * FROM reset_stale_uploads(:s)"), {"s": stale_after_s}
            )
        ).all()
    for org, job in jobs:
        await dispatcher.run_scan_job(org, job)
    for org, batch in uploads:
        await dispatcher.parse_upload(org, batch)
    from sellerscope.reports.service import recover_stale_reports

    reports = await recover_stale_reports(session_factory, dispatcher, stale_after_s=stale_after_s)
    if reports:
        log.warning("stale_reports_recovered", reports=reports)
    if jobs or uploads:
        log.warning("stale_work_recovered", scan_jobs=len(jobs), uploads=len(uploads))
    return len(jobs), len(uploads)
