"""Alerts, report exports, extension tokens and audit logs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, Text
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
    AlertRuleType,
    AlertSeverity,
    AlertStatus,
    ReportFormat,
    ReportStatus,
    ReportType,
)


class AlertRule(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (tenant_unique("alert_rules"), check_in("rule_type", AlertRuleType))

    name: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql("'{}'::jsonb")
    )
    scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql("'{}'::jsonb")
    )
    channels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql("'{in_app}'")
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
        check_in("severity", AlertSeverity),
        check_in("status", AlertStatus),
    )

    alert_rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
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
    delivered_channels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sql("'{}'")
    )


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
    error_message: Mapped[str | None] = mapped_column(Text)
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
