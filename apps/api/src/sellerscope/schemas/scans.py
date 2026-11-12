from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from sellerscope.schemas.common import ApiModel

JobStatus = Literal[
    "queued", "running", "completed", "completed_with_errors", "failed", "cancelled"
]
ItemStatus = Literal[
    "pending", "processing", "completed", "partial", "unavailable", "failed", "cancelled"
]


class ScanJobCreate(ApiModel):
    product_ids: Annotated[list[uuid.UUID], Field(max_length=1000)] | None = None
    # Scan every monitored product in the organization instead of a list.
    all_monitored: bool = False

    @model_validator(mode="after")
    def _one_target(self) -> ScanJobCreate:
        if bool(self.product_ids) == self.all_monitored:
            raise ValueError("Send either product_ids or all_monitored=true")
        return self


class ScanJobOut(ApiModel):
    id: uuid.UUID
    trigger: Literal["manual", "scheduled", "extension", "api"]
    status: JobStatus
    total_items: int
    completed_items: int
    failed_items: int
    unavailable_items: int
    cancelled_items: int
    requested_by: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None


class ScanJobCreated(ScanJobOut):
    already_running: list[uuid.UUID]
    not_found: list[uuid.UUID]


class ScanJobPage(ApiModel):
    items: list[ScanJobOut]
    total: int
    page: int
    page_size: int


class ScanItemResult(ApiModel):
    status: str
    data_source: str
    total_offer_count: int | None
    observed_offer_count: int
    unique_seller_count: int | None
    lowest_observed_price: Decimal | None
    highest_observed_price: Decimal | None
    currency: str | None
    limitations: list[str]
    error_code: str | None


class ScanItemOut(ApiModel):
    product_id: uuid.UUID
    external_id: str
    product_name: str | None
    status: ItemStatus
    attempt_count: int
    next_attempt_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    result: ScanItemResult | None


class ScanItemPage(ApiModel):
    items: list[ScanItemOut]
    total: int
    page: int
    page_size: int


class ScanQuota(ApiModel):
    limit: int | None
    used: int
    remaining: int | None
    period_start: datetime


class Meta(ApiModel):
    environment: str
    version: str
    mock_connector_enabled: bool
