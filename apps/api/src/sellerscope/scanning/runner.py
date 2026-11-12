"""Worker-side execution of a scan job.

`run_job` processes due items in batches until the job is done, its time budget runs out, or
only delayed retries remain. It returns how many seconds until it should run again (None when
nothing is left). Several workers may run the same job concurrently: items are claimed with
FOR UPDATE SKIP LOCKED, so each item is fetched by exactly one worker at a time.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sellerscope.connectors.base import (
    ConnectorContext,
    ConnectorError,
    ConnectorUnavailableError,
    MarketplaceConnector,
    OfferSnapshot,
    TransientError,
)
from sellerscope.connectors.registry import ConnectorRegistry
from sellerscope.core.config import Settings
from sellerscope.db.tenant import set_tenant_context
from sellerscope.models import Marketplace, Product, ScanJob, ScanJobItem
from sellerscope.models.enums import ScanItemStatus, ScanJobStatus
from sellerscope.scanning.backoff import backoff_delay
from sellerscope.scanning.diff import record_changes
from sellerscope.scanning.jobs import TERMINAL_JOB, finalize_job
from sellerscope.scanning.ratelimit import TokenBucket
from sellerscope.scanning.results import record_failure, record_snapshot
from sellerscope.storage import Storage

log = structlog.get_logger()

ITEM_STATUS_FOR_SNAPSHOT = {
    "ok": ScanItemStatus.COMPLETED,
    "partial": ScanItemStatus.PARTIAL,
    "not_found": ScanItemStatus.UNAVAILABLE,
    "unavailable": ScanItemStatus.UNAVAILABLE,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ScanDeps:
    session_factory: async_sessionmaker[AsyncSession]
    registry: ConnectorRegistry
    limiter: TokenBucket
    storage: Storage | None
    settings: Settings
    clock: Callable[[], datetime] = utcnow
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


@dataclass(slots=True)
class Claimed:
    item_id: uuid.UUID
    product_id: uuid.UUID
    external_id: str
    marketplace_id: uuid.UUID
    marketplace_code: str
    attempt: int


async def _claim(
    deps: ScanDeps, org: uuid.UUID, job_id: uuid.UUID, limit: int
) -> tuple[list[Claimed], bool]:
    """Claims up to `limit` due items. Returns (claimed, cancel_requested)."""
    now = deps.clock()
    async with deps.session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=org, user_id=None)
        job = (
            await session.execute(
                select(ScanJob).where(ScanJob.id == job_id, ScanJob.organization_id == org)
            )
        ).scalar_one_or_none()
        if job is None or job.status in TERMINAL_JOB:
            return [], False
        if job.cancel_requested_at is not None:
            return [], True
        rows = (
            await session.execute(
                select(
                    ScanJobItem.id,
                    ScanJobItem.product_id,
                    ScanJobItem.attempt_count,
                    Product.external_id,
                    Product.marketplace_id,
                    Marketplace.code,
                )
                .join(
                    Product,
                    (Product.id == ScanJobItem.product_id)
                    & (Product.organization_id == ScanJobItem.organization_id),
                )
                .join(Marketplace, Marketplace.id == Product.marketplace_id)
                .where(
                    ScanJobItem.scan_job_id == job_id,
                    ScanJobItem.organization_id == org,
                    ScanJobItem.status == ScanItemStatus.PENDING,
                    or_(ScanJobItem.next_attempt_at.is_(None), ScanJobItem.next_attempt_at <= now),
                )
                .order_by(ScanJobItem.created_at, ScanJobItem.id)
                .limit(limit)
                .with_for_update(of=ScanJobItem, skip_locked=True)
            )
        ).all()
        if not rows:
            return [], False
        await session.execute(
            update(ScanJobItem)
            .where(ScanJobItem.id.in_([r.id for r in rows]))
            .values(
                status=ScanItemStatus.PROCESSING,
                started_at=now,
                attempt_count=ScanJobItem.attempt_count + 1,
            )
        )
        if job.status == ScanJobStatus.QUEUED:
            job.status = ScanJobStatus.RUNNING
            job.started_at = now
        return [
            Claimed(
                r.id, r.product_id, r.external_id, r.marketplace_id, r.code, r.attempt_count + 1
            )
            for r in rows
        ], False


async def _release(deps: ScanDeps, org: uuid.UUID, items: list[Claimed], delay_s: float) -> None:
    """Puts claimed items back without counting the attempt (we never called the source)."""
    async with deps.session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=org, user_id=None)
        await session.execute(
            update(ScanJobItem)
            .where(ScanJobItem.id.in_([c.item_id for c in items]))
            .values(
                status=ScanItemStatus.PENDING,
                next_attempt_at=deps.clock() + timedelta(seconds=delay_s),
                attempt_count=ScanJobItem.attempt_count - 1,
            )
        )


async def _apply_results(
    deps: ScanDeps,
    org: uuid.UUID,
    job_id: uuid.UUID,
    connector: MarketplaceConnector,
    ctx: ConnectorContext,
    items: list[Claimed],
    outcome: dict[str, OfferSnapshot | ConnectorError],
) -> None:
    settings = deps.settings
    now = deps.clock()
    async with deps.session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=org, user_id=None)
        for item in items:
            result = outcome.get(item.external_id) or TransientError(
                "missing_result", "The data source returned no result for this product."
            )
            if isinstance(result, OfferSnapshot):
                result_id = await record_snapshot(
                    session,
                    deps.storage,
                    organization_id=org,
                    marketplace_id=item.marketplace_id,
                    product_id=item.product_id,
                    scan_job_item_id=item.item_id,
                    connection_id=ctx.connection.id if ctx.connection else None,
                    snapshot=result,
                )
                await record_changes(
                    session, organization_id=org, product_id=item.product_id, result_id=result_id
                )
                await session.execute(
                    update(ScanJobItem)
                    .where(ScanJobItem.id == item.item_id)
                    .values(
                        status=ITEM_STATUS_FOR_SNAPSHOT[result.status],
                        finished_at=now,
                        next_attempt_at=None,
                        last_error_code=None,
                        last_error_message=None,
                    )
                )
                continue
            retry = result.retryable and item.attempt < settings.scan_max_attempts
            if retry:
                delay = backoff_delay(
                    item.attempt,
                    base_s=settings.scan_backoff_base_s,
                    cap_s=settings.scan_backoff_cap_s,
                    retry_after_s=getattr(result, "retry_after_s", None),
                )
                await session.execute(
                    update(ScanJobItem)
                    .where(ScanJobItem.id == item.item_id)
                    .values(
                        status=ScanItemStatus.PENDING,
                        next_attempt_at=now + timedelta(seconds=delay),
                        last_error_code=result.code,
                        last_error_message=result.message,
                    )
                )
            else:
                await record_failure(
                    session,
                    organization_id=org,
                    product_id=item.product_id,
                    scan_job_item_id=item.item_id,
                    source=connector.code,
                    error_code=result.code,
                    at=now,
                )
                await session.execute(
                    update(ScanJobItem)
                    .where(ScanJobItem.id == item.item_id)
                    .values(
                        status=ScanItemStatus.FAILED,
                        finished_at=now,
                        next_attempt_at=None,
                        last_error_code=result.code,
                        last_error_message=(
                            result.message
                            if not result.retryable
                            else f"{result.message} (gave up after {item.attempt} attempts)"
                        ),
                    )
                )
        await finalize_job(session, org, job_id, now)


async def _fail_unavailable(
    deps: ScanDeps, org: uuid.UUID, job_id: uuid.UUID, items: list[Claimed], reason: str
) -> None:
    now = deps.clock()
    async with deps.session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=org, user_id=None)
        for item in items:
            await record_failure(
                session,
                organization_id=org,
                product_id=item.product_id,
                scan_job_item_id=item.item_id,
                source="none",
                error_code="connector_unavailable",
                at=now,
            )
        await session.execute(
            update(ScanJobItem)
            .where(ScanJobItem.id.in_([i.item_id for i in items]))
            .values(
                status=ScanItemStatus.FAILED,
                finished_at=now,
                last_error_code="connector_unavailable",
                last_error_message=reason,
            )
        )
        await finalize_job(session, org, job_id, now)


async def _next_due_in(deps: ScanDeps, org: uuid.UUID, job_id: uuid.UUID) -> float | None:
    now = deps.clock()
    async with deps.session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=org, user_id=None)
        earliest = (
            await session.execute(
                select(func.min(ScanJobItem.next_attempt_at)).where(
                    ScanJobItem.scan_job_id == job_id,
                    ScanJobItem.organization_id == org,
                    ScanJobItem.status == ScanItemStatus.PENDING,
                )
            )
        ).scalar_one_or_none()
        await finalize_job(session, org, job_id, now)
    if earliest is None:
        return None
    return max((earliest - now).total_seconds(), 0.0)


async def _cancel_pending(deps: ScanDeps, org: uuid.UUID, job_id: uuid.UUID) -> None:
    now = deps.clock()
    async with deps.session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=org, user_id=None)
        await session.execute(
            update(ScanJobItem)
            .where(
                ScanJobItem.scan_job_id == job_id,
                ScanJobItem.organization_id == org,
                ScanJobItem.status == ScanItemStatus.PENDING,
            )
            .values(status=ScanItemStatus.CANCELLED, finished_at=now)
        )
        await finalize_job(session, org, job_id, now)


async def _acquire(deps: ScanDeps, connector: MarketplaceConnector, ctx: ConnectorContext) -> float:
    """Waits for a rate-limit token. Returns 0 when granted, else seconds still to wait."""
    caps = connector.capabilities
    key = connector.rate_limit_key(ctx)
    while True:
        wait = await deps.limiter.acquire(
            key, rate=caps.requests_per_second, burst=caps.burst, now_s=deps.clock().timestamp()
        )
        if wait == 0 or wait > deps.settings.scan_inline_wait_max_s:
            return wait
        await deps.sleep(wait)


async def run_job(deps: ScanDeps, organization_id: uuid.UUID, job_id: uuid.UUID) -> float | None:
    started = deps.clock()
    budget = timedelta(seconds=deps.settings.scan_run_budget_s)
    resolved: dict[str, tuple[MarketplaceConnector, ConnectorContext]] = {}
    while deps.clock() - started < budget:
        # Batch size is decided per connector; claim generously, then split by marketplace.
        items, cancelled = await _claim(deps, organization_id, job_id, limit=20)
        if cancelled:
            await _cancel_pending(deps, organization_id, job_id)
            return None
        if not items:
            return await _next_due_in(deps, organization_id, job_id)

        by_market: dict[str, list[Claimed]] = {}
        for item in items:
            by_market.setdefault(item.marketplace_code, []).append(item)
        # (connector, ctx, chunk) units of work, one source request each.
        work: list[tuple[MarketplaceConnector, ConnectorContext, list[Claimed]]] = []
        for code, group in by_market.items():
            if code not in resolved:
                try:
                    async with deps.session_factory() as session, session.begin():
                        await set_tenant_context(
                            session, organization_id=organization_id, user_id=None
                        )
                        resolved[code] = await deps.registry.resolve(session, organization_id, code)
                except ConnectorUnavailableError as exc:
                    await _fail_unavailable(deps, organization_id, job_id, group, exc.reason)
                    continue
            connector, ctx = resolved[code]
            size = max(connector.capabilities.batch_size, 1)
            work += [(connector, ctx, group[i : i + size]) for i in range(0, len(group), size)]

        for index, (connector, ctx, chunk) in enumerate(work):
            wait = await _acquire(deps, connector, ctx)
            if wait > 0:
                # Too long to sleep: hand every unprocessed item back and come back later.
                untouched = [c for _, _, ch in work[index:] for c in ch]
                await _release(deps, organization_id, untouched, wait)
                return wait
            try:
                outcome = await connector.fetch_offers(ctx, [c.external_id for c in chunk])
            except ConnectorError as exc:
                outcome = {c.external_id: exc for c in chunk}
            except Exception as exc:  # unexpected connector bug: retry, but record it
                log.exception("connector_unexpected_error", connector=connector.code)
                err = TransientError("unexpected_error", f"Unexpected error: {type(exc).__name__}")
                outcome = {c.external_id: err for c in chunk}
            await _apply_results(deps, organization_id, job_id, connector, ctx, chunk, outcome)
    return 0.0  # budget used up: re-queue immediately so other jobs get a turn
