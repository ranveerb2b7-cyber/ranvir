"""Declarative base, naming convention and shared column helpers."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from sellerscope.core.ids import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TenantOwned:
    """Every customer-owned row belongs to exactly one organization (RLS-enforced)."""

    __tenant_owned__ = True

    @declared_attr
    @classmethod
    def organization_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        )


def check_in(
    column: str, values: Iterable[StrEnum | str], *, nullable: bool = False
) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    expr = f"{column} IN ({allowed})"
    if nullable:
        expr = f"{column} IS NULL OR {expr}"
    return CheckConstraint(expr, name=f"{column}_valid")


def tenant_unique(table: str) -> UniqueConstraint:
    """(organization_id, id) is the target of same-tenant composite foreign keys."""
    return UniqueConstraint("organization_id", "id", name=f"uq_{table}_org_id")


def tenant_fk(
    column: str, parent: str, *, ondelete: str | None = None, use_alter: bool = False
) -> ForeignKeyConstraint:
    """Composite FK guaranteeing the referenced row belongs to the same organization."""
    return ForeignKeyConstraint(
        ["organization_id", column],
        [f"{parent}.organization_id", f"{parent}.id"],
        ondelete=ondelete,
        use_alter=use_alter,
    )
