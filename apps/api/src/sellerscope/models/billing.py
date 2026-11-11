"""Plans (global reference data) and per-organization subscriptions."""

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
    Text,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sellerscope.db.base import Base, TenantOwned, Timestamps, UUIDPk, check_in, tenant_unique
from sellerscope.models.enums import BillingProvider, SubscriptionStatus


class Plan(UUIDPk, Timestamps, Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint(
            "max_products > 0 AND max_scans_per_month > 0 AND max_members > 0 "
            "AND min_scan_interval_minutes > 0",
            name="limits_positive",
        ),
    )

    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    max_products: Mapped[int] = mapped_column(Integer, nullable=False)
    max_scans_per_month: Mapped[int] = mapped_column(Integer, nullable=False)
    max_members: Mapped[int] = mapped_column(Integer, nullable=False)
    min_scan_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql("true"))


_LIVE_STATUSES = ", ".join(
    f"'{s}'"
    for s in (SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)
)


class Subscription(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        tenant_unique("subscriptions"),
        # At most one live subscription per organization.
        Index(
            "uq_subscriptions_org_live",
            "organization_id",
            unique=True,
            postgresql_where=sql(f"status IN ({_LIVE_STATUSES})"),
        ),
        check_in("status", SubscriptionStatus),
        check_in("provider", BillingProvider, nullable=True),
        CheckConstraint("scans_used_this_period >= 0", name="scans_used_non_negative"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str | None] = mapped_column(Text)
    provider_customer_id: Mapped[str | None] = mapped_column(Text)
    provider_subscription_id: Mapped[str | None] = mapped_column(Text, unique=True)
    scans_used_this_period: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql("0")
    )
