"""Report exports."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from sellerscope.schemas.common import ApiModel

ReportTypeLit = Literal[
    "product", "marketplace", "brand", "seller", "scan_summary", "errors", "alerts"
]
FormatLit = Literal["csv", "xlsx"]
StatusLit = Literal["queued", "running", "completed", "failed", "expired"]


class ReportCreate(ApiModel):
    report_type: ReportTypeLit
    format: FormatLit = "xlsx"
    filters: dict[str, Any] = Field(default_factory=dict)


class ReportOut(ApiModel):
    id: uuid.UUID
    report_type: ReportTypeLit
    format: FormatLit
    filters: dict[str, Any]
    status: StatusLit
    requested_by: uuid.UUID | None
    requested_by_email: str | None = None
    row_count: int | None
    size_bytes: int | None
    contains_mock: bool | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    file_name: str | None = None


class ReportPage(ApiModel):
    items: list[ReportOut]
    total: int
    page: int
    page_size: int
    retention_days: int
