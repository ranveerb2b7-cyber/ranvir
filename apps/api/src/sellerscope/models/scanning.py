"""Scan jobs, append-only scan snapshots, offers, seller profiles and change history.

Metric semantics (never derive one from another):
- total_offer_count: what the marketplace REPORTS exists (nullable: may be unknown)
- observed_offer_count: how many individual offers we actually RECEIVED
- unique_seller_count: distinct seller ids among observed offers (nullable: unknown if the
  source does not provide seller ids)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sellerscope.db.base import (
    Base,
    CreatedAt,
    TenantOwned,
    Timestamps,
    UUIDPk,
    check_in,
    tenant_fk,
    tenant_unique,
)
from sellerscope.models.enums import (
    ACTIVE_SCAN_ITEM_STATUSES,
    Confidence,
    FulfilmentChannel,
    HistoryEventType,
    ScanItemStatus,
    ScanJobStatus,
    ScanResultStatus,
    ScanTrigger,
)

Money = Numeric(12, 2)

# Tables that must never be updated (enforced by grants + trigger in migrations).
APPEND_ONLY_TABLES = ("scan_results", "product_offers", "scan_history", "audit_logs")

_ACTIVE_ITEMS = ", ".join(f"'{s}'" for s in ACTIVE_SCAN_ITEM_STATUSES)


class ScanJob(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "scan_jobs"
    __table_args__ = (
        tenant_unique("scan_jobs"),
        Index(None, "organization_id", sql("created_at DESC")),
        check_in("trigger", ScanTrigger),
        check_in("status", ScanJobStatus),
        CheckConstraint(
            "total_items >= 0 AND completed_items >= 0 AND failed_items >= 0 "
            "AND unavailable_items >= 0 AND cancelled_items >= 0",
            name="counters_non_negative",
        ),
    )

    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{ScanJobStatus.QUEUED}'")
    )
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    completed_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    unavailable_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    cancelled_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScanJobItem(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "scan_job_items"
    __table_args__ = (
        tenant_unique("scan_job_items"),
        UniqueConstraint("scan_job_id", "product_id"),
        # Prevents duplicate concurrent scans of the same product.
        Index(
            "uq_scan_job_items_product_active",
            "product_id",
            unique=True,
            postgresql_where=sql(f"status IN ({_ACTIVE_ITEMS})"),
        ),
        Index(
            "ix_scan_job_items_dispatch",
            "status",
            "next_attempt_at",
            postgresql_where=sql(f"status IN ({_ACTIVE_ITEMS})"),
        ),
        tenant_fk("scan_job_id", "scan_jobs", ondelete="CASCADE"),
        tenant_fk("product_id", "products"),
        check_in("status", ScanItemStatus),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
    )

    scan_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{ScanItemStatus.PENDING}'")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScanResult(UUIDPk, TenantOwned, CreatedAt, Base):
    """Immutable snapshot of one product scan. Never updated; new scans add new rows."""

    __tablename__ = "scan_results"
    __table_args__ = (
        tenant_unique("scan_results"),
        Index(None, "organization_id", "product_id", sql("retrieved_at DESC")),
        tenant_fk("scan_job_item_id", "scan_job_items"),
        tenant_fk("product_id", "products"),
        tenant_fk("marketplace_connection_id", "marketplace_connections"),
        check_in("status", ScanResultStatus),
        CheckConstraint(
            "total_offer_count IS NULL OR total_offer_count >= 0", name="total_offers_valid"
        ),
        CheckConstraint("observed_offer_count >= 0", name="observed_offers_valid"),
        CheckConstraint(
            "unique_seller_count IS NULL "
            "OR (unique_seller_count >= 0 AND unique_seller_count <= observed_offer_count)",
            name="unique_sellers_valid",
        ),
        CheckConstraint(
            "lowest_observed_price IS NULL OR highest_observed_price IS NULL "
            "OR lowest_observed_price <= highest_observed_price",
            name="price_range_valid",
        ),
        CheckConstraint(
            "(lowest_observed_price IS NULL AND highest_observed_price IS NULL "
            "AND buy_box_price IS NULL) OR currency IS NOT NULL",
            name="prices_have_currency",
        ),
    )

    scan_job_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
        nullable=False,  # idempotent result writes
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    marketplace_connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # e.g. "amazon_sp_api.getItemOffers.v0"; "MOCK" for the dev/test mock connector.
    data_source: Mapped[str] = mapped_column(Text, nullable=False)
    total_offer_count: Mapped[int | None] = mapped_column(Integer)
    observed_offer_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql("0")
    )
    unique_seller_count: Mapped[int | None] = mapped_column(Integer)
    is_offer_list_truncated: Mapped[bool | None] = mapped_column(Boolean)
    # Marketplace-reported breakdown, e.g. Amazon Summary.NumberOfOffers.
    offer_count_breakdown: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    lowest_observed_price: Mapped[Decimal | None] = mapped_column(Money)
    highest_observed_price: Mapped[Decimal | None] = mapped_column(Money)
    buy_box_price: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(String(3))
    limitations: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql("'{}'")
    )
    error_code: Mapped[str | None] = mapped_column(Text)
    raw_payload_key: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SellerProfile(UUIDPk, TenantOwned, Timestamps, Base):
    """Per-organization record of a seller observed on a marketplace."""

    __tablename__ = "seller_profiles"
    __table_args__ = (
        tenant_unique("seller_profiles"),
        UniqueConstraint("organization_id", "marketplace_id", "external_seller_id"),
        CheckConstraint(
            "display_name IS NULL OR display_name_source IS NOT NULL",
            name="display_name_has_source",
        ),
    )

    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplaces.id", ondelete="RESTRICT"), nullable=False
    )
    external_seller_id: Mapped[str] = mapped_column(Text, nullable=False)
    # Null unless an authorized source or the customer provided it (SP-API gives no names).
    display_name: Mapped[str | None] = mapped_column(Text)
    display_name_source: Mapped[str | None] = mapped_column(Text)
    is_marketplace_retail: Mapped[bool | None] = mapped_column(Boolean)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=sql("'{}'"))
    notes: Mapped[str | None] = mapped_column(Text)


class ProductOffer(UUIDPk, TenantOwned, CreatedAt, Base):
    """One offer observed within a scan snapshot. Append-only."""

    __tablename__ = "product_offers"
    __table_args__ = (
        tenant_unique("product_offers"),
        Index(None, "scan_result_id"),
        Index(None, "organization_id", "seller_profile_id", "created_at"),
        Index(None, "organization_id", "product_id", "created_at"),
        tenant_fk("scan_result_id", "scan_results"),
        tenant_fk("product_id", "products"),
        tenant_fk("seller_profile_id", "seller_profiles"),
        check_in("fulfilment_channel", FulfilmentChannel),
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint(
            "(listing_price IS NULL AND shipping_price IS NULL AND landed_price IS NULL) "
            "OR currency IS NOT NULL",
            name="prices_have_currency",
        ),
    )

    scan_result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seller_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    listing_price: Mapped[Decimal | None] = mapped_column(Money)
    shipping_price: Mapped[Decimal | None] = mapped_column(Money)
    landed_price: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(String(3))
    condition: Mapped[str | None] = mapped_column(Text)
    sub_condition: Mapped[str | None] = mapped_column(Text)
    fulfilment_channel: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{FulfilmentChannel.UNKNOWN}'")
    )
    is_buy_box_winner: Mapped[bool | None] = mapped_column(Boolean)
    is_featured_merchant: Mapped[bool | None] = mapped_column(Boolean)
    is_prime: Mapped[bool | None] = mapped_column(Boolean)
    seller_feedback_rating: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    seller_feedback_count: Mapped[int | None] = mapped_column(Integer)
    ships_from_country: Mapped[str | None] = mapped_column(Text)
    shipping_time: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ScanHistory(UUIDPk, TenantOwned, CreatedAt, Base):
    """Change events between consecutive comparable snapshots. Append-only."""

    __tablename__ = "scan_history"
    __table_args__ = (
        tenant_unique("scan_history"),
        Index(None, "organization_id", "product_id", sql("created_at DESC")),
        Index(None, "organization_id", "event_type", sql("created_at DESC")),
        tenant_fk("product_id", "products"),
        tenant_fk("scan_result_id", "scan_results"),
        tenant_fk("previous_scan_result_id", "scan_results"),
        tenant_fk("seller_profile_id", "seller_profiles"),
        check_in("event_type", HistoryEventType),
        check_in("confidence", Confidence, nullable=True),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scan_result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    previous_scan_result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    seller_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[str | None] = mapped_column(Text)
