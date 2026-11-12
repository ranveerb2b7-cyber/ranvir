"""Product management and dashboard schemas.

Scan-derived fields are null when unknown (never scanned, or not provided by the source).
They are never defaulted to 0.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from sellerscope.schemas.common import ApiModel

MarketplaceCodeIn = Literal["amazon_in"]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None
BrandText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None

ScanStatus = Literal["not_scanned", "ok", "partial", "not_found", "unavailable", "error"]
SortField = Literal[
    "created_at",
    "external_id",
    "product_name",
    "brand_name",
    "last_scanned_at",
    "total_offer_count",
    "unique_seller_count",
    "lowest_observed_price",
    "highest_observed_price",
]


class ProductCreate(ApiModel):
    marketplace: MarketplaceCodeIn = "amazon_in"
    # ASIN or Amazon product-page URL; normalized server-side.
    identifier: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    product_name: OptionalText = None
    brand_name: BrandText = None


class ProductUpdate(ApiModel):
    product_name: OptionalText = None
    brand_name: BrandText = None
    monitoring_enabled: bool | None = None


class LatestScan(ApiModel):
    status: ScanStatus
    data_source: str
    retrieved_at: datetime
    total_offer_count: int | None
    observed_offer_count: int
    unique_seller_count: int | None
    is_offer_list_truncated: bool | None
    lowest_observed_price: Decimal | None
    highest_observed_price: Decimal | None
    currency: str | None
    limitations: list[str]


class ProductOut(ApiModel):
    id: uuid.UUID
    marketplace: str
    external_id: str
    product_name: str | None
    brand_name: str | None
    identifier_status: str
    monitoring_enabled: bool
    created_at: datetime
    last_scanned_at: datetime | None
    scan_status: ScanStatus
    # Null until the product has been scanned at least once.
    latest_scan: LatestScan | None


class ProductPage(ApiModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int


class IdentifierCheckIn(ApiModel):
    marketplace: MarketplaceCodeIn = "amazon_in"
    identifier: Annotated[str, StringConstraints(max_length=2000)]


class IdentifierCheckBatch(ApiModel):
    items: Annotated[list[IdentifierCheckIn], Field(min_length=1, max_length=1000)]


class IdentifierCheckOut(ApiModel):
    input: str
    normalized: str | None
    valid: bool
    error: str | None
    message: str | None
    warnings: list[str]
    warning_messages: list[str]
    # Set when an active product with this identifier already exists in the organization.
    existing_product_id: uuid.UUID | None


class BulkAction(ApiModel):
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=500)]
    action: Literal["delete", "enable_monitoring", "disable_monitoring", "set_brand"]
    brand_name: BrandText = None


class BulkResult(ApiModel):
    affected: int
    not_found: list[uuid.UUID]


class BrandCount(ApiModel):
    brand_name: str | None
    products: int


class Metric(ApiModel):
    """A dashboard number. `value` is null when it cannot be known yet; `reason` says why."""

    value: int | None
    reason: str | None = None


class MarketplaceBreakdown(ApiModel):
    marketplace: str
    name: str
    products: int
    scanned: int
    with_multiple_sellers: Metric
    total_offers_observed: Metric


class DashboardSummary(ApiModel):
    total_products_monitored: Metric
    products_successfully_scanned: Metric
    products_with_multiple_sellers: Metric
    total_offers_observed: Metric
    new_sellers_detected_7d: Metric
    products_with_unavailable_data: Metric
    last_scan_at: datetime | None
    marketplaces: list[MarketplaceBreakdown]
