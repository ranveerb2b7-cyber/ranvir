from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sellerscope.schemas.common import ApiModel

BatchStatusOut = Literal["uploaded", "parsing", "preview_ready", "committed", "failed", "discarded"]
RowStatusOut = Literal["valid", "invalid", "duplicate_in_file", "duplicate_existing"]


class PlanUsage(ApiModel):
    limit: int | None
    current: int
    remaining: int | None


class BatchOut(ApiModel):
    id: uuid.UUID
    original_filename: str
    file_size_bytes: int
    status: BatchStatusOut
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_in_file_rows: int
    duplicate_existing_rows: int
    committed_rows: int
    column_mapping: dict[str, str] | None
    error_code: str | None
    error_message: str | None
    uploaded_by: uuid.UUID | None
    created_at: datetime
    parsed_at: datetime | None
    committed_at: datetime | None


class BatchDetail(BatchOut):
    plan: PlanUsage
    # Set when the exact same file was already added in an earlier upload.
    same_file_as: uuid.UUID | None


class BatchPage(ApiModel):
    items: list[BatchOut]
    total: int
    page: int
    page_size: int


class RowIssue(ApiModel):
    code: str
    message: str


class BatchRowOut(ApiModel):
    row_number: int
    status: RowStatusOut
    asin: str | None
    product_name: str | None
    brand_name: str | None
    original: dict[str, str]
    errors: list[RowIssue]
    warnings: list[RowIssue]
    product_id: uuid.UUID | None


class BatchRowPage(ApiModel):
    items: list[BatchRowOut]
    total: int
    page: int
    page_size: int
