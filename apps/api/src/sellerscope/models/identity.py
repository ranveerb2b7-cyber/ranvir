"""Users, organizations, memberships and invitations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, Text, UniqueConstraint
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sellerscope.db.base import Base, TenantOwned, Timestamps, UUIDPk, check_in, tenant_unique
from sellerscope.models.enums import MemberRole, MemberStatus


class User(Timestamps, Base):
    """Mirror of the identity provider's user. Passwords are never stored here."""

    __tablename__ = "users"

    # Equals the Supabase auth user id, so no default.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql("true"))


class Organization(UUIDPk, Timestamps, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganizationMember(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        tenant_unique("organization_members"),
        UniqueConstraint("organization_id", "user_id"),
        Index(None, "user_id"),
        check_in("role", MemberRole),
        check_in("status", MemberStatus),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql(f"'{MemberStatus.ACTIVE}'")
    )


class Invitation(UUIDPk, TenantOwned, Timestamps, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        tenant_unique("invitations"),
        Index(
            "uq_invitations_org_email_pending",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=sql("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        check_in("role", MemberRole),
    )

    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of the invitation token; the raw token is only ever sent by email.
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
