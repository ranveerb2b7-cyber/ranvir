"""Scan job lifecycle: create (with duplicate-scan guard and quota), cancel, retry, finalize."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.core.errors import AppError
from sellerscope.core.ids import uuid7
from sellerscope.models import Plan, Product, ScanJob, ScanJobItem, Subscription
from sellerscope.models.enums import (
    ACTIVE_SCAN_ITEM_STATUSES,
    ScanItemStatus,
    ScanJobStatus,
    ScanTrigger,
)
from sellerscope.services.products import LIVE_SUBSCRIPTION

TERMINAL_JOB = (
    ScanJobStatus.COMPLETED,
    ScanJobStatus.COMPLETED_WITH_ERRORS,
    ScanJobStatus.FAILED,
    ScanJobStatus.CANCELLED,
)


def month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def scan_quota(
    session: AsyncSession, organization_id: uuid.UUID, now: datetime
) -> tuple[int | None, int]:
    """(plan's monthly scan limit or None without a live subscription, scans used this month).

    A "scan" is one product scan (one job item), counted per UTC calendar month.
    """
    limit = (
        await session.execute(
            select(Plan.max_scans_per_month)
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(
                Subscription.organization_id == organization_id,
                Subscription.status.in_(LIVE_SUBSCRIPTION),
            )
        )
    ).scalar_one_or_none()
    used = (
        await session.execute(
            select(func.count())
            .select_from(ScanJobItem)
            .where(
                ScanJobItem.organization_id == organization_id,
                ScanJobItem.created_at >= month_start(now),
            )
        )
    ).scalar_one()
    return limit, used


@dataclass(slots=True)
class CreatedJob:
    job: ScanJob
    already_running: list[uuid.UUID]
    not_found: list[uuid.UUID]


async def create_scan_job(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    requested_by: uuid.UUID | None,
    product_ids: list[uuid.UUID],
    trigger: ScanTrigger,
    now: datetime,
    cap_to_quota: bool = False,
) -> CreatedJob:
    """Creates a job for the given products.

    Products already being scanned are skipped atomically (partial unique index), so two
    concurrent requests can never scan the same product twice.
    """
    wanted = list(dict.fromkeys(product_ids))
    live = set(
        (
            await session.execute(
                select(Product.id).where(
                    Product.organization_id == organization_id,
                    Product.id.in_(wanted),
                    Product.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    not_found = [p for p in wanted if p not in live]
    candidates = [p for p in wanted if p in live]
    if not candidates:
        raise AppError(
            404, "not_found", "No products to scan", "None of the selected products exist."
        )

    limit, used = await scan_quota(session, organization_id, now)
    if limit is None:
        raise AppError(
            402,
            "subscription_required",
            "Subscription required",
            "This organization has no active subscription.",
        )
    remaining = max(limit - used, 0)
    if len(candidates) > remaining:
        if not cap_to_quota or remaining == 0:
            raise AppError(
                402,
                "scan_quota_exceeded",
                "Monthly scan limit reached",
                f"Your plan allows {limit} product scans per month; {used} used, "
                f"{len(candidates)} requested.",
                extra={"limit": limit, "used": used, "requested": len(candidates)},
            )
        candidates = candidates[:remaining]

    job = ScanJob(
        id=uuid7(),
        organization_id=organization_id,
        requested_by=requested_by,
        trigger=trigger,
        status=ScanJobStatus.QUEUED,
    )
    session.add(job)
    await session.flush()
    active = ", ".join(f"'{s}'" for s in ACTIVE_SCAN_ITEM_STATUSES)
    inserted = (
        (
            await session.execute(
                pg_insert(ScanJobItem)
                .values(
                    [
                        {
                            "id": uuid7(),
                            "organization_id": organization_id,
                            "scan_job_id": job.id,
                            "product_id": pid,
                            "status": ScanItemStatus.PENDING,
                        }
                        for pid in candidates
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=["product_id"], index_where=text(f"status IN ({active})")
                )
                .returning(ScanJobItem.product_id)
            )
        )
        .scalars()
        .all()
    )
    created = set(inserted)
    already_running = [p for p in candidates if p not in created]
    if not created:
        await session.delete(job)
        await session.flush()
        raise AppError(
            409,
            "scan_already_running",
            "Already scanning",
            "The selected products are already being scanned.",
            extra={"already_running": [str(p) for p in already_running]},
        )
    job.total_items = len(created)
    await session.flush()
    return CreatedJob(job=job, already_running=already_running, not_found=not_found)


async def cancel_job(
    session: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID, now: datetime
) -> ScanJob:
    """Pending items are cancelled now; items already being fetched finish normally."""
    job = await _locked_job(session, organization_id, job_id)
    if job.status in TERMINAL_JOB:
        raise AppError(409, "invalid_state", "Conflict", f"This scan is already {job.status}.")
    job.cancel_requested_at = now
    await session.execute(
        update(ScanJobItem)
        .where(
            ScanJobItem.scan_job_id == job_id,
            ScanJobItem.organization_id == organization_id,
            ScanJobItem.status == ScanItemStatus.PENDING,
        )
        .values(status=ScanItemStatus.CANCELLED, finished_at=now)
    )
    await finalize_job(session, organization_id, job_id, now)
    return job


async def failed_product_ids(
    session: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID
) -> list[uuid.UUID]:
    job = await _locked_job(session, organization_id, job_id)
    if job.status not in TERMINAL_JOB:
        raise AppError(409, "invalid_state", "Conflict", "Wait for this scan to finish first.")
    return list(
        (
            await session.execute(
                select(ScanJobItem.product_id).where(
                    ScanJobItem.scan_job_id == job_id,
                    ScanJobItem.organization_id == organization_id,
                    ScanJobItem.status == ScanItemStatus.FAILED,
                )
            )
        ).scalars()
    )


async def _locked_job(
    session: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID
) -> ScanJob:
    job = (
        await session.execute(
            select(ScanJob)
            .where(ScanJob.id == job_id, ScanJob.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise AppError(404, "not_found", "Scan not found")
    return job


async def finalize_job(
    session: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID, now: datetime
) -> ScanJob:
    """Recomputes counters from items and closes the job when no work remains."""
    counts = dict(
        (
            await session.execute(
                select(ScanJobItem.status, func.count())
                .where(
                    ScanJobItem.scan_job_id == job_id,
                    ScanJobItem.organization_id == organization_id,
                )
                .group_by(ScanJobItem.status)
            )
        ).all()
    )
    job = (
        await session.execute(
            select(ScanJob).where(ScanJob.id == job_id, ScanJob.organization_id == organization_id)
        )
    ).scalar_one()
    done = counts.get(ScanItemStatus.COMPLETED, 0) + counts.get(ScanItemStatus.PARTIAL, 0)
    job.completed_items = done
    job.failed_items = counts.get(ScanItemStatus.FAILED, 0)
    job.unavailable_items = counts.get(ScanItemStatus.UNAVAILABLE, 0)
    job.cancelled_items = counts.get(ScanItemStatus.CANCELLED, 0)
    open_items = sum(counts.get(s, 0) for s in ACTIVE_SCAN_ITEM_STATUSES)
    if open_items == 0 and job.status not in TERMINAL_JOB:
        if job.cancel_requested_at and job.cancelled_items:
            job.status = ScanJobStatus.CANCELLED
        elif job.failed_items == job.total_items:
            job.status = ScanJobStatus.FAILED
        elif job.failed_items or job.unavailable_items:
            job.status = ScanJobStatus.COMPLETED_WITH_ERRORS
        else:
            job.status = ScanJobStatus.COMPLETED
        job.finished_at = now
    await session.flush()
    return job
