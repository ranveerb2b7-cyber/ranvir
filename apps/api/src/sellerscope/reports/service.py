"""Report export lifecycle: generate (worker), expire and recover (beat)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sellerscope.core.config import Settings
from sellerscope.db.tenant import set_tenant_context
from sellerscope.models import ReportExport
from sellerscope.models.enums import ReportStatus, ReportType
from sellerscope.reports.builders import BUILDERS, Ctx, TooManyRowsError
from sellerscope.reports.filters import parse_filters
from sellerscope.reports.writers import render
from sellerscope.storage import Storage
from sellerscope.uploads.dispatch import TaskDispatcher

log = structlog.get_logger()

EXTENSION = {"csv": "csv", "xlsx": "xlsx"}


def storage_key(organization_id: uuid.UUID, report_id: uuid.UUID, fmt: str) -> str:
    return f"org/{organization_id}/reports/{report_id}.{EXTENSION[fmt]}"


def file_name(report: ReportExport) -> str:
    return (
        f"sellerscope-{report.report_type.replace('_', '-')}-"
        f"{report.created_at:%Y%m%d-%H%M}.{EXTENSION[report.format]}"
    )


async def _fail(
    session_factory: async_sessionmaker[AsyncSession],
    org: uuid.UUID,
    report_id: uuid.UUID,
    message: str,
) -> None:
    async with session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=org, user_id=None)
        await session.execute(
            update(ReportExport)
            .where(ReportExport.organization_id == org, ReportExport.id == report_id)
            .values(status=ReportStatus.FAILED, error_message=message[:1000])
        )


async def generate_report(
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    report_id: uuid.UUID,
    now: datetime,
) -> str:
    """Builds and stores one export. Every failure is recorded on the export row."""
    org = organization_id
    async with session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=org, user_id=None)
        claimed = (
            await session.execute(
                update(ReportExport)
                .where(
                    ReportExport.organization_id == org,
                    ReportExport.id == report_id,
                    ReportExport.status == ReportStatus.QUEUED,
                )
                .values(status=ReportStatus.RUNNING, started_at=now, error_message=None)
                .returning(ReportExport.report_type, ReportExport.format, ReportExport.filters)
            )
        ).one_or_none()
    if claimed is None:
        return "skipped"  # already running elsewhere, finished, or deleted
    report_type, fmt, raw_filters = claimed
    try:
        async with session_factory() as session, session.begin():
            await set_tenant_context(session, organization_id=org, user_id=None)
            await session.execute(text("SET TRANSACTION READ ONLY"))
            ctx = Ctx(session, org, now, settings.report_max_rows)
            report = await BUILDERS[ReportType(report_type)](
                ctx, parse_filters(report_type, raw_filters)
            )
        data, content_type = render(report, fmt)
        key = storage_key(org, report_id, fmt)
        await storage.put(key, data, content_type)
    except TooManyRowsError as exc:
        await _fail(session_factory, org, report_id, str(exc))
        return "failed"
    except Exception as exc:
        log.exception("report_failed", organization_id=str(org), report_id=str(report_id))
        await _fail(
            session_factory,
            org,
            report_id,
            f"The report could not be generated ({type(exc).__name__}).",
        )
        return "failed"
    async with session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=org, user_id=None)
        await session.execute(
            update(ReportExport)
            .where(ReportExport.organization_id == org, ReportExport.id == report_id)
            .values(
                status=ReportStatus.COMPLETED,
                storage_key=key,
                row_count=len(report.rows),
                size_bytes=len(data),
                contains_mock=report.contains_mock,
                completed_at=now,
                expires_at=now + timedelta(days=settings.report_retention_days),
            )
        )
    return "completed"


async def expire_reports(
    session_factory: async_sessionmaker[AsyncSession], storage: Storage
) -> int:
    """Marks exports past retention as expired and deletes their files."""
    async with session_factory() as session, session.begin():
        rows = (await session.execute(text("SELECT * FROM expire_report_exports()"))).all()
    for org, report_id, key in rows:
        if not key:
            continue
        try:
            await storage.delete(key)
        except Exception as exc:  # recorded on the export; the file is retried by ops tooling
            log.exception("report_file_delete_failed", organization_id=str(org))
            async with session_factory() as session, session.begin():
                await set_tenant_context(session, organization_id=org, user_id=None)
                await session.execute(
                    update(ReportExport)
                    .where(ReportExport.organization_id == org, ReportExport.id == report_id)
                    .values(
                        error_message=f"Expired, but the file could not be deleted: {exc}"[:1000]
                    )
                )
    return len(rows)


async def recover_stale_reports(
    session_factory: async_sessionmaker[AsyncSession],
    dispatcher: TaskDispatcher,
    *,
    stale_after_s: int,
) -> int:
    async with session_factory() as session, session.begin():
        rows = (
            await session.execute(
                text("SELECT * FROM reset_stale_reports(:s)"), {"s": stale_after_s}
            )
        ).all()
    for org, report_id in rows:
        await dispatcher.generate_report(org, report_id)
    return len(rows)


async def active_count(session: AsyncSession, org: uuid.UUID) -> int:
    from sqlalchemy import func

    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(ReportExport)
                .where(
                    ReportExport.organization_id == org,
                    ReportExport.status.in_((ReportStatus.QUEUED, ReportStatus.RUNNING)),
                )
            )
        ).scalar_one()
    )
