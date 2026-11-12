"""Product file uploads: template, upload, preview, commit, discard, history."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import func, select

from sellerscope.auth.deps import (
    OrgContext,
    OrgDep,
    PrincipalDep,
    SessionDep,
    rate_limit,
    require,
)
from sellerscope.auth.permissions import Permission
from sellerscope.core.config import Settings
from sellerscope.core.errors import AppError, not_found
from sellerscope.models import ProductBatch, ProductBatchRow
from sellerscope.models.enums import BatchRowStatus
from sellerscope.schemas.uploads import (
    BatchDetail,
    BatchOut,
    BatchPage,
    BatchRowOut,
    BatchRowPage,
    PlanUsage,
    RowIssue,
    RowStatusOut,
)
from sellerscope.services import audit
from sellerscope.services.products import product_quota
from sellerscope.storage import Storage
from sellerscope.uploads.dispatch import TaskDispatcher
from sellerscope.uploads.files import XLSX_CONTENT_TYPE
from sellerscope.uploads.service import (
    commit_batch,
    create_batch,
    discard_batch,
    previous_same_file,
    row_message,
    warning_message,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])
WriteProducts = Annotated[OrgContext, Depends(require(Permission.PRODUCTS_WRITE))]

TEMPLATE_COLUMNS = ("ASIN", "Product name", "Brand")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection (CSV injection) in exported cells."""
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


# ------------------------------------------------------------------------------ template


@router.get("/template", summary="Download an empty upload template")
async def template(_: PrincipalDep, format: Literal["csv", "xlsx"] = "xlsx") -> Response:
    if format == "csv":
        buffer = io.StringIO()
        csv.writer(buffer).writerow(TEMPLATE_COLUMNS)
        return Response(
            "﻿" + buffer.getvalue(),  # BOM so Excel opens it as UTF-8
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="sellerscope-products.csv"'},
        )
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Products"
    sheet.append(TEMPLATE_COLUMNS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.column_dimensions["A"].width = 48
    sheet.column_dimensions["B"].width = 40
    sheet.column_dimensions["C"].width = 24
    help_sheet = workbook.create_sheet("Instructions")
    for line in (
        "Fill the 'Products' sheet: one product per row. Keep the header row.",
        "ASIN (required): a 10-character Amazon ASIN, or a full Amazon.in product link.",
        "Short links (amzn.in, amzn.to) are not accepted: open them and copy the full link.",
        "Product name and Brand are optional.",
        "Format the ASIN column as Text so Excel keeps leading zeros.",
        "Flipkart FSNs are not supported yet.",
    ):
        help_sheet.append([line])
    buffer_bytes = io.BytesIO()
    workbook.save(buffer_bytes)
    return Response(
        buffer_bytes.getvalue(),
        media_type=XLSX_CONTENT_TYPE,
        headers={"Content-Disposition": 'attachment; filename="sellerscope-products.xlsx"'},
    )


# ------------------------------------------------------------------------------ upload


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise AppError(
                413,
                "file_too_large",
                "File rejected",
                f"The file is larger than the {limit // (1024 * 1024)} MB limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "",
    response_model=BatchOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("upload", limit=30, window_s=3600))],
)
async def upload(
    request: Request,
    session: SessionDep,
    ctx: WriteProducts,
    file: Annotated[UploadFile, File(description=".csv or .xlsx, max 10 MB")],
) -> BatchOut:
    """Stores the file and queues it for parsing. Poll GET /uploads/{id} for the preview."""
    settings: Settings = request.app.state.settings
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.upload_max_bytes + 65536:
        raise AppError(
            413,
            "file_too_large",
            "File rejected",
            f"The file is larger than the {settings.upload_max_bytes // 1048576} MB limit.",
        )
    data = await _read_limited(file, settings.upload_max_bytes)
    storage: Storage = request.app.state.storage
    batch = await create_batch(
        session,
        storage,
        settings,
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        filename=file.filename or "upload",
        data=data,
    )
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="upload.create",
        entity_type="product_batch",
        entity_id=batch.id,
        request=request,
        details={"filename": batch.original_filename, "bytes": batch.file_size_bytes},
    )
    await session.refresh(batch)
    out = BatchOut.model_validate(batch)
    await session.commit()
    dispatcher: TaskDispatcher = request.app.state.task_dispatcher
    await dispatcher.parse_upload(ctx.organization_id, batch.id)
    return out


# ------------------------------------------------------------------------------ read


@router.get("", response_model=BatchPage)
async def history(
    session: SessionDep,
    ctx: OrgDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BatchPage:
    base = select(ProductBatch).where(ProductBatch.organization_id == ctx.organization_id)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.execute(
            base.order_by(ProductBatch.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars()
    return BatchPage(
        items=[BatchOut.model_validate(b) for b in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _batch(session: SessionDep, ctx: OrgContext, batch_id: uuid.UUID) -> ProductBatch:
    batch = (
        await session.execute(
            select(ProductBatch).where(
                ProductBatch.id == batch_id, ProductBatch.organization_id == ctx.organization_id
            )
        )
    ).scalar_one_or_none()
    if batch is None:
        raise not_found("Upload")
    return batch


async def _detail(session: SessionDep, ctx: OrgContext, batch: ProductBatch) -> BatchDetail:
    limit, current = await product_quota(session, ctx.organization_id)
    return BatchDetail(
        **BatchOut.model_validate(batch).model_dump(),
        plan=PlanUsage(
            limit=limit,
            current=current,
            remaining=None if limit is None else max(limit - current, 0),
        ),
        same_file_as=await previous_same_file(session, ctx.organization_id, batch),
    )


@router.get("/{batch_id}", response_model=BatchDetail)
async def get_batch(batch_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> BatchDetail:
    return await _detail(session, ctx, await _batch(session, ctx, batch_id))


def _row_out(row: ProductBatchRow) -> BatchRowOut:
    return BatchRowOut(
        row_number=row.row_number,
        status=row.status,
        asin=row.external_id_normalized,
        product_name=row.product_name,
        brand_name=row.brand_name,
        original=row.raw,
        errors=[RowIssue(code=c.split(":")[0], message=row_message(c)) for c in row.errors],
        warnings=[RowIssue(code=w, message=warning_message(w)) for w in row.warnings],
        product_id=row.product_id,
    )


@router.get("/{batch_id}/rows", response_model=BatchRowPage)
async def batch_rows(
    batch_id: uuid.UUID,
    session: SessionDep,
    ctx: OrgDep,
    status_filter: Annotated[RowStatusOut | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> BatchRowPage:
    await _batch(session, ctx, batch_id)
    base = select(ProductBatchRow).where(
        ProductBatchRow.batch_id == batch_id,
        ProductBatchRow.organization_id == ctx.organization_id,
    )
    if status_filter:
        base = base.where(ProductBatchRow.status == status_filter)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.execute(
            base.order_by(ProductBatchRow.row_number)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars()
    return BatchRowPage(
        items=[_row_out(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/{batch_id}/rejected.csv", summary="Rows that were not added, with reasons")
async def rejected_csv(batch_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> Response:
    batch = await _batch(session, ctx, batch_id)
    rows = (
        (
            await session.execute(
                select(ProductBatchRow)
                .where(
                    ProductBatchRow.batch_id == batch_id,
                    ProductBatchRow.organization_id == ctx.organization_id,
                    ProductBatchRow.status != BatchRowStatus.VALID,
                )
                .order_by(ProductBatchRow.row_number)
            )
        )
        .scalars()
        .all()
    )
    original_columns: list[str] = []
    for row in rows:
        for key in row.raw:
            if key not in original_columns:
                original_columns.append(key)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Row", "Status", "Reason", *original_columns])
    for row in rows:
        reason = "; ".join(row_message(c) for c in row.errors)
        writer.writerow(
            [
                row.row_number,
                row.status,
                csv_safe(reason),
                *(csv_safe(row.raw.get(c, "")) for c in original_columns),
            ]
        )
    stem = batch.original_filename.rsplit(".", 1)[0] or "upload"
    safe_stem = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in stem)[:80]
    return Response(
        "﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_stem}-rejected.csv"'},
    )


# ------------------------------------------------------------------------------ commit / discard


@router.post("/{batch_id}/commit", response_model=BatchDetail)
async def commit(
    batch_id: uuid.UUID, request: Request, session: SessionDep, ctx: WriteProducts
) -> BatchDetail:
    """Adds the valid rows as products. All-or-nothing; respects the plan's product limit."""
    batch = await commit_batch(
        session, organization_id=ctx.organization_id, user_id=ctx.user_id, batch_id=batch_id
    )
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="upload.commit",
        entity_type="product_batch",
        entity_id=batch.id,
        request=request,
        details={"products_added": batch.committed_rows},
    )
    await session.flush()
    await session.refresh(batch)
    out = await _detail(session, ctx, batch)
    await session.commit()
    return out


@router.post("/{batch_id}/discard", response_model=BatchOut)
async def discard(
    batch_id: uuid.UUID, request: Request, session: SessionDep, ctx: WriteProducts
) -> BatchOut:
    batch = await discard_batch(session, organization_id=ctx.organization_id, batch_id=batch_id)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="upload.discard",
        entity_type="product_batch",
        entity_id=batch.id,
        request=request,
    )
    await session.flush()
    await session.refresh(batch)
    out = BatchOut.model_validate(batch)
    await session.commit()
    return out
