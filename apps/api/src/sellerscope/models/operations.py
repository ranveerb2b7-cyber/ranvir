"""Alerts, report exports, extension tokens and audit logs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
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
    ActorType,
    AlertChannel,
    AlertRuleType,
    AlertSeverity,
    AlertStatus,
    DeliveryStatus,
    ReportFormat,
    ReportStatus,
    ReportType,
)


class AlertRule(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        tenant_unique("alert_rules"),
        check_in("rule_type", AlertRuleType),
        check_in("severity", AlertSeverity),
        CheckConstraint(
            "channels <@ ARRAY['in_app', 'email']::text[] AND 'in_app' = ANY(channels)",
            name="channels_valid",
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{AlertSeverity.WARNING}'")
    )
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql("'{}'::jsonb")
    )
    scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql("'{}'::jsonb")
    )
    channels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql(f"'{{{AlertChannel.IN_APP}}}'")
    )
    # Members who receive email for this rule (checked again at send time).
    recipient_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=sql("'{}'")
    )
    is_enabled: Mapped[bool] = mapped_column(nullable=False, server_default=sql("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Alert(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        tenant_unique("alerts"),
        Index(None, "organization_id", "status", sql("created_at DESC")),
        tenant_fk("alert_rule_id", "alert_rules"),
        tenant_fk("product_id", "products"),
        tenant_fk("scan_history_id", "scan_history"),
        tenant_fk("scan_result_id", "scan_results"),
        tenant_fk("seller_profile_id", "seller_profiles"),
        check_in("severity", AlertSeverity),
        check_in("status", AlertStatus),
        # One unresolved alert per rule and condition (e.g. "seller count above 5" on a product).
        Index(
            "uq_alerts_open_dedupe",
            "organization_id",
            "alert_rule_id",
            "dedupe_key",
            unique=True,
            postgresql_where=sql("status <> 'resolved'"),
        ),
        Index(None, "organization_id", "product_id", sql("created_at DESC")),
    )

    alert_rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Kept so an alert still says which rule raised it after the rule is deleted.
    rule_name: Mapped[str | None] = mapped_column(Text)
    rule_type: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    scan_result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    seller_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql("'{}'::jsonb")
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    scan_history_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{AlertStatus.OPEN}'")
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Null with resolved_at set = resolved automatically when the condition cleared.
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    delivered_channels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql("'{}'")
    )


class AlertDelivery(UUIDPk, TenantOwned, Timestamps, Base):
    """One outbound notification of an alert (an email to one member). Retried on failure."""

    __tablename__ = "alert_deliveries"
    __table_args__ = (
        tenant_unique("alert_deliveries"),
        tenant_fk("alert_id", "alerts", ondelete="CASCADE"),
        UniqueConstraint("alert_id", "channel", "recipient_user_id"),
        Index(None, "organization_id", "status", "next_attempt_at"),
        check_in("channel", AlertChannel),
        check_in("status", DeliveryStatus),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{DeliveryStatus.PENDING}'")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportExport(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "report_exports"
    __table_args__ = (
        tenant_unique("report_exports"),
        Index(None, "organization_id", sql("created_at DESC")),
        check_in("report_type", ReportType),
        check_in("format", ReportFormat),
        check_in("status", ReportStatus),
    )

    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    report_type: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{ReportStatus.QUEUED}'")
    )
    storage_key: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    # True when any row came from the MOCK connector (the file says so, too).
    contains_mock: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtensionToken(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "extension_tokens"
    __table_args__ = (tenant_unique("extension_tokens"), Index(None, "user_id"))

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of the opaque token; the raw token is shown to the extension once.
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql("'{}'")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtensionPairing(UUIDPk, TenantOwned, Timestamps, Base):
    """A one-time code a signed-in member approves on the web to connect a browser extension.

    The code is stored hashed and is bound to the extension's PKCE challenge, so seeing the
    code is not enough to redeem it. Redeemed codes and expired codes can't be used again.
    """

    __tablename__ = "extension_pairings"
    __table_args__ = (
        tenant_unique("extension_pairings"),
        UniqueConstraint("code_hash"),
        CheckConstraint("char_length(code_challenge) BETWEEN 43 AND 128", name="challenge_length"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)  # S256, base64url
    device_name: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extension_token_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AuditLog(UUIDPk, TenantOwned, CreatedAt, Base):
    """Append-only. actor_user_id is deliberately not a FK so records outlive users."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        tenant_unique("audit_logs"),
        Index(None, "organization_id", sql("created_at DESC")),
        check_in("actor_type", ActorType),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "product.delete"
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql("'{}'::jsonb")
    )
