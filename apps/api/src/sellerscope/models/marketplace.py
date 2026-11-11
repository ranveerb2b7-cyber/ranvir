"""Marketplaces (global reference data) and per-organization marketplace connections."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sellerscope.db.base import Base, TenantOwned, Timestamps, UUIDPk, check_in, tenant_unique
from sellerscope.models.enums import ConnectionStatus, ConnectionType


class Marketplace(UUIDPk, Timestamps, Base):
    __tablename__ = "marketplaces"

    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # e.g. Amazon marketplace id A21TJRUUN4KGV for Amazon.in
    external_marketplace_id: Mapped[str | None] = mapped_column(Text)
    identifier_label: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql("true"))


class MarketplaceConnection(UUIDPk, TenantOwned, Timestamps, Base):
    """An authorized data connection (e.g. a customer's Seller Central authorization)."""

    __tablename__ = "marketplace_connections"
    __table_args__ = (
        tenant_unique("marketplace_connections"),
        UniqueConstraint("organization_id", "marketplace_id", "external_account_id"),
        check_in("connection_type", ConnectionType),
        check_in("status", ConnectionStatus),
        # A secret and the key that encrypted it are stored together or not at all.
        CheckConstraint(
            "(encrypted_secret IS NULL) = (encryption_key_id IS NULL)", name="secret_has_key"
        ),
    )

    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketplaces.id", ondelete="RESTRICT"), nullable=False
    )
    connection_type: Mapped[str] = mapped_column(Text, nullable=False)
    # e.g. Amazon selling_partner_id
    external_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{ConnectionStatus.PENDING}'")
    )
    # AES-256-GCM ciphertext (envelope-encrypted). Never returned by the API.
    encrypted_secret: Mapped[bytes | None] = mapped_column(LargeBinary)
    encryption_key_id: Mapped[str | None] = mapped_column(Text)
    granted_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql("'{}'")
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
