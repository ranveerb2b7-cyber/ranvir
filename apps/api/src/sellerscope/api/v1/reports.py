"""Report exports: request (async), list, download, delete."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.auth.deps import OrgDep, SessionDep, rate_limit
from sellerscope.auth.permissions import Permission
from sellerscope.core.errors import AppError, not_found
from sellerscope.models import ReportExport, User
from sellerscope.models.enums import ReportStatus
from sellerscope.reports.filters import FiltersError, parse_filters
from sellerscope.reports.service import active_count, file_name
from sellerscope.reports.writers import CSV_CONTENT_TYPE, XLSX_CONTENT_TYPE
from sellerscope.scanning.runner import utcnow
from sellerscope.schemas.reports import ReportCreate, ReportOut, ReportPage
from sellerscope.services import audit
from sellerscope.storage import Storage
from sellerscope.uploads.dispatch import TaskDispatcher

router = APIRouter(prefix="/reports", tags=["reports"])


def _out(report: ReportExport, email: str | None = None) -> ReportOut:
    out = ReportOut.model_validate(report)
    out.requested_by_email = email
    out.file_name = file_name(report) if report.status == ReportStatus.COMPLETED else None
    return out


async def _get(session: AsyncSession, org: uuid.UUID, report_id: uuid.UUID) -> ReportExport:
    report = (
        await session.execute(
            select(ReportExport).where(
                ReportExport.organization_id == org, ReportExport.id == report_id
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise not_found("Report")
    return report


@router.post(
    "",
    response_model=ReportOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("report-create", limit=30, window_s=3600))],
)
async def create_report(
    body: ReportCreate, request: Request, session: SessionDep, ctx: OrgDep
) -> ReportOut:
    """Queues an export. Every member may export their organization's data."""
    try:
        filters = parse_filters(body.report_type, body.filters).model_dump(
            mode="json", exclude_none=True
        )
    except FiltersError as exc:
        raise AppError(
            422,
            "validation_error",
            "Invalid report filters",
            "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors),
            extra={"errors": exc.errors},
        ) from exc
    limit = request.app.state.settings.report_max_active
    if await active_count(session, ctx.organization_id) >= limit:
        raise AppError(
            409,
            "too_many_reports_running",
            "Reports already in progress",
            f"Up to {limit} reports can be prepared at once. Wait for one to finish.",
        )
    report = ReportExport(
        organization_id=ctx.organization_id,
        requested_by=ctx.user_id,
        report_type=body.report_type,
        format=body.format,
        filters=filters,
    )
    session.add(report)
    await session.flush()
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="report.create",
        entity_type="report_export",
        entity_id=report.id,
        request=request,
        details={"report_type": body.report_type, "format": body.format, "filters": filters},
    )
    await session.refresh(report)
    out = _out(report, ctx.email)
    await session.commit()
    dispatcher: TaskDispatcher = request.app.state.task_dispatcher
    await dispatcher.generate_report(ctx.organization_id, report.id)
    return out


@router.get("", response_model=ReportPage)
async def list_reports(
    request: Request,
    session: SessionDep,
    ctx: OrgDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ReportPage:
    org = ctx.organization_id
    total = (
        await session.execute(
            select(func.count())
            .select_from(ReportExport)
            .where(ReportExport.organization_id == org)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(ReportExport, User.email)
            .outerjoin(User, User.id == ReportExport.requested_by)
            .where(ReportExport.organization_id == org)
            .order_by(ReportExport.created_at.desc(), ReportExport.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ReportPage(
        items=[_out(r, email) for r, email in rows],
        total=total,
        page=page,
        page_size=page_size,
        retention_days=request.app.state.settings.report_retention_days,
    )


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> ReportOut:
    report = await _get(session, ctx.organization_id, report_id)
    email = (
        await session.execute(select(User.email).where(User.id == report.requested_by))
    ).scalar_one_or_none()
    return _out(report, email)


@router.get(
    "/{report_id}/download",
    dependencies=[Depends(rate_limit("report-download", limit=120, window_s=3600))],
    responses={200: {"content": {CSV_CONTENT_TYPE: {}, XLSX_CONTENT_TYPE: {}}}},
)
async def download_report(
    report_id: uuid.UUID, request: Request, session: SessionDep, ctx: OrgDep
) -> Response:
    """The file itself, streamed through the API for signed-in members only (no shareable link)."""
    report = await _get(session, ctx.organization_id, report_id)
    if report.status == ReportStatus.EXPIRED or (
        report.expires_at is not None and report.expires_at <= utcnow()
    ):
        raise AppError(410, "report_expired", "Report expired", "Create the report again.")
    if report.status != ReportStatus.COMPLETED or not report.storage_key:
        raise AppError(409, "report_not_ready", "Report not ready", f"Status: {report.status}.")
    storage: Storage = request.app.state.storage
    data = await storage.get(report.storage_key)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="report.download",
        entity_type="report_export",
        entity_id=report.id,
        request=request,
        details={"report_type": report.report_type, "rows": report.row_count},
    )
    name = file_name(report)
    await session.commit()
    return Response(
        data,
        media_type=CSV_CONTENT_TYPE if report.format == "csv" else XLSX_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: uuid.UUID, request: Request, session: SessionDep, ctx: OrgDep
) -> None:
    """Deletes an export and its file: the person who requested it, or an admin."""
    report = await _get(session, ctx.organization_id, report_id)
    if report.requested_by != ctx.user_id and not ctx.can(Permission.ORG_MANAGE):
        raise AppError(
            403,
            "forbidden",
            "Forbidden",
            "Only the person who requested it or an admin can delete it.",
        )
    if report.status == ReportStatus.RUNNING:
        raise AppError(409, "report_running", "Report in progress", "Try again when it finishes.")
    key = report.storage_key
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="report.delete",
        entity_type="report_export",
        entity_id=report.id,
        request=request,
        details={"report_type": report.report_type},
    )
    await session.delete(report)
    await session.commit()
    if key:
        storage: Storage = request.app.state.storage
        await storage.delete(key)  # after commit; a failure surfaces as a 500 and is logged
