"""Products, upload batches and their parsed rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sellerscope.db.base import (
    Base,
    TenantOwned,
    Timestamps,
    UUIDPk,
    check_in,
    tenant_fk,
    tenant_unique,
)
from sellerscope.models.enums import BatchRowStatus, BatchStatus, IdentifierStatus


class ProductBatch(UUIDPk, TenantOwned, Timestamps, Base):
    """One uploaded file (upload history)."""

    __tablename__ = "product_batches"
    __table_args__ = (
        tenant_unique("product_batches"),
        Index(None, "organization_id", sql("created_at DESC")),
        check_in("status", BatchStatus),
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint(
            "total_rows >= 0 AND valid_rows >= 0 AND invalid_rows >= 0 AND duplicate_rows >= 0",
            name="row_counts_non_negative",
        ),
        CheckConstraint(
            "duplicate_in_file_rows >= 0 AND duplicate_existing_rows >= 0 AND committed_rows >= 0",
            name="extra_counts_non_negative",
        ),
    )

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{BatchStatus.UPLOADED}'")
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    # duplicate_rows = duplicate_in_file_rows + duplicate_existing_rows
    duplicate_in_file_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql("0")
    )
    duplicate_existing_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql("0")
    )
    committed_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    # Which file column was used for which field, e.g. {"identifier": "ASIN", "brand_name": ...}
    column_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class ProductBatchRow(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "product_batch_rows"
    __table_args__ = (
        tenant_unique("product_batch_rows"),
        UniqueConstraint("batch_id", "row_number"),
        tenant_fk("batch_id", "product_batches", ondelete="CASCADE"),
        tenant_fk("product_id", "products"),
        Index(None, "batch_id", "status", "row_number"),
        check_in("status", BatchRowStatus),
        CheckConstraint("row_number > 0", name="row_number_positive"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    marketplace_code: Mapped[str | None] = mapped_column(Text)
    external_id_normalized: Mapped[str | None] = mapped_column(Text)
    brand_name: Mapped[str | None] = mapped_column(Text)
    product_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    errors: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql("'{}'")
    )
    warnings: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql("'{}'")
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Product(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "products"
    __table_args__ = (
        tenant_unique("products"),
        # One live product per identifier per marketplace per organization.
        Index(
            "uq_products_org_marketplace_external_id_live",
            "organization_id",
            "marketplace_id",
            "external_id",
            unique=True,
            postgresql_where=sql("deleted_at IS NULL"),
        ),
        Index(None, "organization_id", "brand_name"),
        Index(None, "organization_id", "marketplace_id"),
        Index(
            "ix_products_product_name_trgm",
            "product_name",
            postgresql_using="gin",
            postgresql_ops={"product_name": "gin_trgm_ops"},
        ),
        tenant_fk("source_batch_id", "product_batches"),
        tenant_fk("latest_scan_result_id", "scan_results", use_alter=True),  # cycle
        check_in("identifier_status", IdentifierStatus),
        CheckConstraint(
            "external_id = upper(btrim(external_id)) AND length(external_id) > 0",
            name="external_id_normalized",
        ),
        CheckConstraint(
            "scan_frequency_minutes IS NULL OR scan_frequency_minutes > 0",
            name="scan_frequency_positive",
        ),
    )

    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplaces.id", ondelete="RESTRICT"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)  # normalized ASIN
    product_name: Mapped[str | None] = mapped_column(Text)  # user-supplied
    brand_name: Mapped[str | None] = mapped_column(Text)  # user-supplied
    catalog_title: Mapped[str | None] = mapped_column(Text)  # from marketplace, if verified
    catalog_brand: Mapped[str | None] = mapped_column(Text)
    identifier_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{IdentifierStatus.FORMAT_VALID}'")
    )
    monitoring_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql("true")
    )
    scan_frequency_minutes: Mapped[int | None] = mapped_column(Integer)
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    latest_scan_result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
