"""Scan jobs: start, track, cancel, retry."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select

from sellerscope.auth.deps import OrgContext, OrgDep, SessionDep, rate_limit, require
from sellerscope.auth.permissions import Permission
from sellerscope.connectors.base import ConnectorUnavailableError
from sellerscope.connectors.registry import ConnectorRegistry
from sellerscope.core.errors import AppError, not_found
from sellerscope.models import Product, ScanJob, ScanJobItem, ScanResult
from sellerscope.models.enums import ScanTrigger
from sellerscope.scanning.jobs import (
    cancel_job,
    create_scan_job,
    failed_product_ids,
    month_start,
    scan_quota,
)
from sellerscope.scanning.runner import utcnow
from sellerscope.schemas.scans import (
    ItemStatus,
    ScanItemOut,
    ScanItemPage,
    ScanItemResult,
    ScanJobCreate,
    ScanJobCreated,
    ScanJobOut,
    ScanJobPage,
    ScanQuota,
)
from sellerscope.services import audit
from sellerscope.uploads.dispatch import TaskDispatcher

router = APIRouter(prefix="/scan-jobs", tags=["scans"])
RunScans = Annotated[OrgContext, Depends(require(Permission.SCANS_RUN))]


async def _ensure_connector(request: Request, session: SessionDep, ctx: OrgContext) -> None:
    registry: ConnectorRegistry = request.app.state.connector_registry
    try:
        await registry.resolve(session, ctx.organization_id, "amazon_in")
    except ConnectorUnavailableError as exc:
        raise AppError(409, "connector_unavailable", "Scanning not available", exc.reason) from exc


async def _start(
    request: Request, session: SessionDep, ctx: OrgContext, product_ids: list[uuid.UUID]
) -> ScanJobCreated:
    created = await create_scan_job(
        session,
        organization_id=ctx.organization_id,
        requested_by=ctx.user_id,
        product_ids=product_ids,
        trigger=ScanTrigger.MANUAL,
        now=utcnow(),
    )
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="scan.start",
        entity_type="scan_job",
        entity_id=created.job.id,
        request=request,
        details={"products": created.job.total_items},
    )
    await session.flush()
    await session.refresh(created.job)
    out = ScanJobCreated(
        **ScanJobOut.model_validate(created.job).model_dump(),
        already_running=created.already_running,
        not_found=created.not_found,
    )
    await session.commit()
    dispatcher: TaskDispatcher = request.app.state.task_dispatcher
    await dispatcher.run_scan_job(ctx.organization_id, created.job.id)
    return out


@router.post(
    "",
    response_model=ScanJobCreated,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("scan-create", limit=60, window_s=3600))],
)
async def start_scan(
    body: ScanJobCreate, request: Request, session: SessionDep, ctx: RunScans
) -> ScanJobCreated:
    """Queues a scan. Products already being scanned are skipped (listed in the response)."""
    await _ensure_connector(request, session, ctx)
    if body.all_monitored:
        ids = list(
            (
                await session.execute(
                    select(Product.id).where(
                        Product.organization_id == ctx.organization_id,
                        Product.deleted_at.is_(None),
                        Product.monitoring_enabled.is_(True),
                    )
                )
            ).scalars()
        )
        if not ids:
            raise AppError(
                404, "not_found", "No products to scan", "There are no monitored products."
            )
    else:
        ids = body.product_ids or []
    return await _start(request, session, ctx, ids)


@router.get("/quota", response_model=ScanQuota)
async def quota(session: SessionDep, ctx: OrgDep) -> ScanQuota:
    now = utcnow()
    limit, used = await scan_quota(session, ctx.organization_id, now)
    return ScanQuota(
        limit=limit,
        used=used,
        remaining=None if limit is None else max(limit - used, 0),
        period_start=month_start(now),
    )


@router.get("", response_model=ScanJobPage)
async def list_jobs(
    session: SessionDep,
    ctx: OrgDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ScanJobPage:
    base = select(ScanJob).where(ScanJob.organization_id == ctx.organization_id)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    jobs = (
        await session.execute(
            base.order_by(ScanJob.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
        )
    ).scalars()
    return ScanJobPage(
        items=[ScanJobOut.model_validate(j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _job(session: SessionDep, ctx: OrgContext, job_id: uuid.UUID) -> ScanJob:
    job = (
        await session.execute(
            select(ScanJob).where(
                ScanJob.id == job_id, ScanJob.organization_id == ctx.organization_id
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise not_found("Scan")
    return job


@router.get("/{job_id}", response_model=ScanJobOut)
async def get_job(job_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> ScanJobOut:
    return ScanJobOut.model_validate(await _job(session, ctx, job_id))


@router.get("/{job_id}/items", response_model=ScanItemPage)
async def job_items(
    job_id: uuid.UUID,
    session: SessionDep,
    ctx: OrgDep,
    status_filter: Annotated[ItemStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ScanItemPage:
    await _job(session, ctx, job_id)
    base = (
        select(ScanJobItem, Product.external_id, Product.product_name, ScanResult)
        .join(
            Product,
            (Product.id == ScanJobItem.product_id)
            & (Product.organization_id == ScanJobItem.organization_id),
        )
        .outerjoin(
            ScanResult,
            (ScanResult.scan_job_item_id == ScanJobItem.id)
            & (ScanResult.organization_id == ScanJobItem.organization_id),
        )
        .where(
            ScanJobItem.scan_job_id == job_id, ScanJobItem.organization_id == ctx.organization_id
        )
    )
    if status_filter:
        base = base.where(ScanJobItem.status == status_filter)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.execute(
            base.order_by(Product.external_id).limit(page_size).offset((page - 1) * page_size)
        )
    ).all()
    return ScanItemPage(
        items=[
            ScanItemOut(
                product_id=item.product_id,
                external_id=external_id,
                product_name=name,
                status=item.status,
                attempt_count=item.attempt_count,
                next_attempt_at=item.next_attempt_at,
                last_error_code=item.last_error_code,
                last_error_message=item.last_error_message,
                started_at=item.started_at,
                finished_at=item.finished_at,
                result=ScanItemResult.model_validate(result) if result else None,
            )
            for item, external_id, name, result in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{job_id}/cancel", response_model=ScanJobOut)
async def cancel(
    job_id: uuid.UUID, request: Request, session: SessionDep, ctx: RunScans
) -> ScanJobOut:
    """Cancels products not yet started. Products being fetched right now still finish."""
    job = await cancel_job(session, ctx.organization_id, job_id, utcnow())
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="scan.cancel",
        entity_type="scan_job",
        entity_id=job.id,
        request=request,
    )
    await session.flush()
    await session.refresh(job)
    out = ScanJobOut.model_validate(job)
    await session.commit()
    return out


@router.post(
    "/{job_id}/retry-failed",
    response_model=ScanJobCreated,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("scan-create", limit=60, window_s=3600))],
)
async def retry_failed(
    job_id: uuid.UUID, request: Request, session: SessionDep, ctx: RunScans
) -> ScanJobCreated:
    """Starts a new scan for the products that failed in this one."""
    ids = await failed_product_ids(session, ctx.organization_id, job_id)
    if not ids:
        raise AppError(
            409, "nothing_to_retry", "Nothing to retry", "No products failed in this scan."
        )
    await _ensure_connector(request, session, ctx)
    return await _start(request, session, ctx, ids)
