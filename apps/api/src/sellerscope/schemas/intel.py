"""Seller intelligence and product history schemas. Unknown values are null, never 0."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from sellerscope.schemas.common import ApiModel

Presence = Literal["observed", "no_longer_observed", "not_observed_inconclusive", "unknown"]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class SellerRef(ApiModel):
    id: uuid.UUID
    external_seller_id: str
    display_name: str | None


class ProductRef(ApiModel):
    id: uuid.UUID
    external_id: str
    product_name: str | None
    brand_name: str | None


class SellerSummary(ApiModel):
    id: uuid.UUID
    external_seller_id: str
    display_name: str | None
    display_name_source: str | None
    tags: list[str]
    first_observed_at: datetime
    last_observed_at: datetime
    # Products whose LATEST scan includes an offer from this seller.
    products_currently_offering: int
    buy_box_count: int
    lowest_current_price: Decimal | None
    currency: str | None
    is_mock: bool


class SellerPage(ApiModel):
    items: list[SellerSummary]
    total: int
    page: int
    page_size: int


class SellerOffer(ApiModel):
    listing_price: Decimal | None
    shipping_price: Decimal | None
    landed_price: Decimal | None
    currency: str | None
    fulfilment_channel: str
    is_buy_box_winner: bool | None
    is_featured_merchant: bool | None
    is_prime: bool | None
    seller_feedback_rating: Decimal | None
    seller_feedback_count: int | None
    ships_from_country: str | None
    condition: str | None


class SellerProduct(ApiModel):
    product: ProductRef
    presence: Presence
    last_seen_at: datetime
    latest_scan_at: datetime | None
    current_offer: SellerOffer | None


class ChangeEvent(ApiModel):
    id: uuid.UUID
    created_at: datetime
    event_type: str
    confidence: str | None
    product: ProductRef
    seller: SellerRef | None
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    scan_result_id: uuid.UUID
    previous_scan_result_id: uuid.UUID | None


class ChangePage(ApiModel):
    items: list[ChangeEvent]
    total: int
    page: int
    page_size: int


class SellerDetail(SellerSummary):
    notes: str | None
    products: list[SellerProduct]
    recent_changes: list[ChangeEvent]


class SellerUpdate(ApiModel):
    display_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None
    ) = None
    tags: Annotated[list[Tag], Field(max_length=10)] | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None


class CompareCell(ApiModel):
    seller_id: uuid.UUID
    offer: SellerOffer | None


class CompareRow(ApiModel):
    product: ProductRef
    cells: list[CompareCell]


class SellerComparison(ApiModel):
    sellers: list[SellerSummary]
    rows: list[CompareRow]


class OfferRow(SellerOffer):
    position: int
    seller: SellerRef | None
    seller_tags: list[str]


class ScanSnapshot(ApiModel):
    id: uuid.UUID
    status: str
    data_source: str
    retrieved_at: datetime
    total_offer_count: int | None
    observed_offer_count: int
    unique_seller_count: int | None
    is_offer_list_truncated: bool | None
    lowest_observed_price: Decimal | None
    highest_observed_price: Decimal | None
    buy_box_price: Decimal | None
    currency: str | None
    limitations: list[str]
    error_code: str | None


class ProductOffers(ApiModel):
    snapshot: ScanSnapshot | None
    offers: list[OfferRow]


class SnapshotPage(ApiModel):
    items: list[ScanSnapshot]
    total: int
    page: int
    page_size: int


class TrendPoint(ApiModel):
    retrieved_at: datetime
    status: str
    total_offer_count: int | None
    observed_offer_count: int
    unique_seller_count: int | None
    lowest_observed_price: Decimal | None
    highest_observed_price: Decimal | None
    is_offer_list_truncated: bool | None
    data_source: str
