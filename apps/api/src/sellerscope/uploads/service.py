"""Upload batches: store the file, parse it (worker), preview, commit or discard."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sellerscope.connectors.identifiers import ERROR_MESSAGES as IDENTIFIER_MESSAGES
from sellerscope.connectors.identifiers import WARNING_MESSAGES as IDENTIFIER_WARNINGS
from sellerscope.core.config import Settings
from sellerscope.core.errors import AppError
from sellerscope.core.ids import uuid7
from sellerscope.db.tenant import set_tenant_context
from sellerscope.models import Product, ProductBatch, ProductBatchRow
from sellerscope.models.enums import BatchRowStatus, BatchStatus
from sellerscope.services.products import ensure_product_quota, marketplace_by_code
from sellerscope.storage import Storage
from sellerscope.uploads.files import FileRejectedError, inspect_upload
from sellerscope.uploads.parse import RowError, RowWarning, classify, parse_table, read_rows

log = structlog.get_logger()
INSERT_CHUNK = 2_000

ROW_MESSAGES: dict[str, str] = {
    **{str(k): v for k, v in IDENTIFIER_MESSAGES.items()},
    RowError.MISSING_IDENTIFIER: "No ASIN in this row.",
    RowError.FLIPKART_NOT_SUPPORTED: "Flipkart is not supported yet (Amazon.in only).",
    RowError.UNKNOWN_MARKETPLACE: "Unknown marketplace. Use Amazon.in or leave the column empty.",
    RowError.ALREADY_EXISTS: "This ASIN is already in your products.",
}
WARNING_TEXT: dict[str, str] = {
    **{str(k): v for k, v in IDENTIFIER_WARNINGS.items()},
    RowWarning.NAME_TRUNCATED: "Product name was longer than 300 characters and was shortened.",
    RowWarning.BRAND_TRUNCATED: "Brand was longer than 120 characters and was shortened.",
}
_DUP_RE = re.compile(rf"^{RowError.DUPLICATE_IN_FILE}:(\d+)$")


def row_message(code: str) -> str:
    match = _DUP_RE.match(code)
    if match:
        return f"Same ASIN as row {match.group(1)}; only the first occurrence is added."
    return ROW_MESSAGES.get(code, code)


def warning_message(code: str) -> str:
    return WARNING_TEXT.get(code, code)


def _safe_filename(name: str) -> str:
    """Display name only (never used as a storage path)."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable())[:200]
    return name or "upload"


# ------------------------------------------------------------------------------ create


async def create_batch(
    session: AsyncSession,
    storage: Storage,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
) -> ProductBatch:
    try:
        inspected = inspect_upload(filename, data, max_bytes=settings.upload_max_bytes)
    except FileRejectedError as exc:
        raise AppError(
            413 if exc.code == "file_too_large" else 422,
            exc.code,
            "File rejected",
            exc.message,
        ) from exc
    batch_id = uuid7()
    key = f"org/{organization_id}/uploads/{batch_id}/original.{inspected.kind}"
    await storage.put(key, data, inspected.content_type)
    batch = ProductBatch(
        id=batch_id,
        organization_id=organization_id,
        uploaded_by=user_id,
        original_filename=_safe_filename(filename),
        storage_key=key,
        file_sha256=hashlib.sha256(data).hexdigest(),
        file_size_bytes=len(data),
        status=BatchStatus.UPLOADED,
    )
    session.add(batch)
    await session.flush()
    return batch


# ------------------------------------------------------------------------------ parse (worker)


async def parse_batch(
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> str:
    """Parses an uploaded batch into rows. Idempotent: only acts on status `uploaded`.

    Returns the final batch status. Failures are recorded on the batch, never swallowed.
    """
    async with session_factory() as session:
        await set_tenant_context(session, organization_id=organization_id, user_id=None)
        claimed = (
            await session.execute(
                update(ProductBatch)
                .where(
                    ProductBatch.id == batch_id,
                    ProductBatch.organization_id == organization_id,
                    ProductBatch.status == BatchStatus.UPLOADED,
                )
                .values(status=BatchStatus.PARSING)
                .returning(ProductBatch.storage_key)
            )
        ).scalar_one_or_none()
        await session.commit()
    if claimed is None:
        return "skipped"

    try:
        data = await storage.get(claimed)
        kind = claimed.rsplit(".", 1)[-1]
        table = parse_table(read_rows(kind, data), max_rows=settings.upload_max_rows)  # type: ignore[arg-type]
    except FileRejectedError as exc:
        await _fail(session_factory, organization_id, batch_id, exc.code, exc.message)
        return BatchStatus.FAILED
    except Exception:
        log.exception("upload_parse_failed", batch_id=str(batch_id))
        await _fail(
            session_factory,
            organization_id,
            batch_id,
            "processing_failed",
            "The file could not be processed. Please try uploading it again.",
        )
        return BatchStatus.FAILED

    try:
        async with session_factory() as session, session.begin():
            await set_tenant_context(session, organization_id=organization_id, user_id=None)
            marketplace = await marketplace_by_code(session, "amazon_in")
            existing = set(
                (
                    await session.execute(
                        select(Product.external_id).where(
                            Product.organization_id == organization_id,
                            Product.marketplace_id == marketplace.id,
                            Product.deleted_at.is_(None),
                        )
                    )
                ).scalars()
            )
            outcomes = classify(table.rows, existing)
            rows: list[dict[str, Any]] = [
                {
                    "id": uuid7(),
                    "organization_id": organization_id,
                    "batch_id": batch_id,
                    "row_number": o.source.row_number,
                    "raw": o.source.raw,
                    "marketplace_code": o.marketplace_code,
                    "external_id_normalized": o.normalized,
                    "brand_name": o.brand_name,
                    "product_name": o.product_name,
                    "status": o.status,
                    "errors": o.errors,
                    "warnings": o.warnings,
                }
                for o in outcomes
            ]
            for start in range(0, len(rows), INSERT_CHUNK):
                await session.execute(insert(ProductBatchRow), rows[start : start + INSERT_CHUNK])

            def count(status: BatchRowStatus) -> int:
                return sum(1 for o in outcomes if o.status == status)

            in_file = count(BatchRowStatus.DUPLICATE_IN_FILE)
            existing_dupes = count(BatchRowStatus.DUPLICATE_EXISTING)
            await session.execute(
                update(ProductBatch)
                .where(ProductBatch.id == batch_id)
                .values(
                    status=BatchStatus.PREVIEW_READY,
                    total_rows=len(outcomes),
                    valid_rows=count(BatchRowStatus.VALID),
                    invalid_rows=count(BatchRowStatus.INVALID),
                    duplicate_in_file_rows=in_file,
                    duplicate_existing_rows=existing_dupes,
                    duplicate_rows=in_file + existing_dupes,
                    column_mapping=table.mapping,
                    parsed_at=datetime.now(UTC),
                )
            )
    except Exception:
        log.exception("upload_store_rows_failed", batch_id=str(batch_id))
        await _fail(
            session_factory,
            organization_id,
            batch_id,
            "processing_failed",
            "The file could not be processed. Please try uploading it again.",
        )
        return BatchStatus.FAILED
    return BatchStatus.PREVIEW_READY


async def _fail(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
    code: str,
    message: str,
) -> None:
    async with session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=organization_id, user_id=None)
        await session.execute(
            update(ProductBatch)
            .where(ProductBatch.id == batch_id)
            .values(
                status=BatchStatus.FAILED,
                error_code=code,
                error_message=message,
                parsed_at=datetime.now(UTC),
            )
        )


# ------------------------------------------------------------------------------ commit


async def commit_batch(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> ProductBatch:
    """Creates products from the batch's valid rows (all-or-nothing)."""
    batch = (
        await session.execute(
            select(ProductBatch)
            .where(ProductBatch.id == batch_id, ProductBatch.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise AppError(404, "not_found", "Upload not found")
    if batch.status != BatchStatus.PREVIEW_READY:
        raise AppError(
            409,
            "invalid_state",
            "Conflict",
            f"This upload is {batch.status} and can no longer be added.",
        )

    marketplace = await marketplace_by_code(session, "amazon_in")
    valid = (
        (
            await session.execute(
                select(ProductBatchRow)
                .where(
                    ProductBatchRow.batch_id == batch_id,
                    ProductBatchRow.status == BatchRowStatus.VALID,
                )
                .order_by(ProductBatchRow.row_number)
            )
        )
        .scalars()
        .all()
    )

    # Products may have been added since the preview was built.
    now_existing = set(
        (
            await session.execute(
                select(Product.external_id).where(
                    Product.organization_id == organization_id,
                    Product.marketplace_id == marketplace.id,
                    Product.deleted_at.is_(None),
                    Product.external_id.in_([r.external_id_normalized for r in valid]),
                )
            )
        ).scalars()
    )
    to_add = [r for r in valid if r.external_id_normalized not in now_existing]
    became_duplicate = [r for r in valid if r.external_id_normalized in now_existing]
    for row in became_duplicate:
        row.status = BatchRowStatus.DUPLICATE_EXISTING
        row.errors = [RowError.ALREADY_EXISTS]

    if to_add:
        await ensure_product_quota(session, organization_id, len(to_add))
    products = [
        {
            "id": uuid7(),
            "organization_id": organization_id,
            "marketplace_id": marketplace.id,
            "external_id": r.external_id_normalized,
            "product_name": r.product_name,
            "brand_name": r.brand_name,
            "source_batch_id": batch_id,
            "created_by": user_id,
        }
        for r in to_add
    ]
    try:
        for start in range(0, len(products), INSERT_CHUNK):
            await session.execute(insert(Product), products[start : start + INSERT_CHUNK])
    except IntegrityError as exc:
        raise AppError(
            409, "products_changed", "Conflict", "Products changed while adding. Please try again."
        ) from exc
    await session.execute(
        text(
            "UPDATE product_batch_rows r SET product_id = p.id FROM products p "
            "WHERE r.batch_id = :b AND r.status = 'valid' AND p.source_batch_id = :b "
            "AND p.organization_id = r.organization_id "
            "AND p.external_id = r.external_id_normalized AND p.deleted_at IS NULL"
        ),
        {"b": batch_id},
    )
    batch.status = BatchStatus.COMMITTED
    batch.committed_rows = len(to_add)
    batch.committed_at = datetime.now(UTC)
    batch.valid_rows = len(to_add)
    batch.duplicate_existing_rows += len(became_duplicate)
    batch.duplicate_rows += len(became_duplicate)
    await session.flush()
    return batch


async def discard_batch(
    session: AsyncSession, *, organization_id: uuid.UUID, batch_id: uuid.UUID
) -> ProductBatch:
    batch = (
        await session.execute(
            select(ProductBatch)
            .where(ProductBatch.id == batch_id, ProductBatch.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise AppError(404, "not_found", "Upload not found")
    if batch.status in (BatchStatus.COMMITTED, BatchStatus.DISCARDED):
        raise AppError(409, "invalid_state", "Conflict", f"This upload is already {batch.status}.")
    batch.status = BatchStatus.DISCARDED
    await session.flush()
    return batch


async def previous_same_file(
    session: AsyncSession, organization_id: uuid.UUID, batch: ProductBatch
) -> uuid.UUID | None:
    return (
        await session.execute(
            select(ProductBatch.id)
            .where(
                ProductBatch.organization_id == organization_id,
                ProductBatch.file_sha256 == batch.file_sha256,
                ProductBatch.id != batch.id,
                ProductBatch.created_at < batch.created_at,
                ProductBatch.status == BatchStatus.COMMITTED,
            )
            .order_by(ProductBatch.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
