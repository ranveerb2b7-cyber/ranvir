"""Product catalogue of an organization: lookup, quota, listing with latest-scan data."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from sellerscope.core.errors import AppError
from sellerscope.models import Marketplace, Plan, Product, ScanResult, Subscription
from sellerscope.models.enums import SubscriptionStatus
from sellerscope.schemas.products import LatestScan, ProductOut, SortField

NO_BRAND = "__none__"  # filter value meaning "products without a brand"

LIVE_SUBSCRIPTION = (
    SubscriptionStatus.TRIALING,
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.PAST_DUE,
)


def clean_text(value: str | None) -> str | None:
    """Trimmed text, with empty strings stored as NULL."""
    if value is None:
        return None
    value = value.strip()
    return value or None


async def marketplace_by_code(session: AsyncSession, code: str) -> Marketplace:
    marketplace = (
        await session.execute(
            select(Marketplace).where(Marketplace.code == code, Marketplace.is_enabled.is_(True))
        )
    ).scalar_one_or_none()
    if marketplace is None:
        raise AppError(422, "unsupported_marketplace", "Unsupported marketplace", code)
    return marketplace


async def existing_products(
    session: AsyncSession,
    organization_id: uuid.UUID,
    marketplace_id: uuid.UUID,
    external_ids: Iterable[str],
) -> dict[str, uuid.UUID]:
    ids = list(set(external_ids))
    if not ids:
        return {}
    rows = await session.execute(
        select(Product.external_id, Product.id).where(
            Product.organization_id == organization_id,
            Product.marketplace_id == marketplace_id,
            Product.external_id.in_(ids),
            Product.deleted_at.is_(None),
        )
    )
    return {external_id: pid for external_id, pid in rows.all()}


async def product_quota(
    session: AsyncSession, organization_id: uuid.UUID
) -> tuple[int | None, int]:
    """(plan product limit or None without a live subscription, current live products)."""
    limit = (
        await session.execute(
            select(Plan.max_products)
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(
                Subscription.organization_id == organization_id,
                Subscription.status.in_(LIVE_SUBSCRIPTION),
            )
        )
    ).scalar_one_or_none()
    current = (
        await session.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.organization_id == organization_id, Product.deleted_at.is_(None))
        )
    ).scalar_one()
    return limit, current


async def ensure_product_quota(
    session: AsyncSession, organization_id: uuid.UUID, adding: int
) -> None:
    """Raises 402 if adding products would exceed the subscription plan's limit."""
    max_products = (
        await session.execute(
            select(Plan.max_products)
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(
                Subscription.organization_id == organization_id,
                Subscription.status.in_(LIVE_SUBSCRIPTION),
            )
        )
    ).scalar_one_or_none()
    if max_products is None:
        raise AppError(
            402,
            "subscription_required",
            "Subscription required",
            "This organization has no active subscription.",
        )
    current = (
        await session.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.organization_id == organization_id, Product.deleted_at.is_(None))
        )
    ).scalar_one()
    if current + adding > max_products:
        raise AppError(
            402,
            "plan_limit_reached",
            "Plan limit reached",
            f"Your plan allows {max_products} products; you have {current}.",
            extra={"limit": max_products, "current": current},
        )


# ------------------------------------------------------------------------------ listing

Latest = aliased(ScanResult, name="latest")
# Rows of (product, marketplace code, latest scan result or None).
ProductSelect = Select[Product, str, ScanResult]


@dataclass(frozen=True, slots=True)
class ProductFilters:
    q: str | None = None
    marketplace: str | None = None
    brand: str | None = None
    scan_status: str | None = None
    multiple_sellers: bool | None = None
    monitoring: bool | None = None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def base_query(organization_id: uuid.UUID) -> ProductSelect:
    return (
        select(Product, Marketplace.code, Latest)
        .join(Marketplace, Marketplace.id == Product.marketplace_id)
        .outerjoin(
            Latest,
            and_(
                Latest.id == Product.latest_scan_result_id,
                Latest.organization_id == Product.organization_id,
            ),
        )
        .where(Product.organization_id == organization_id, Product.deleted_at.is_(None))
    )


def apply_filters(stmt: ProductSelect, f: ProductFilters) -> ProductSelect:
    if f.q:
        term = _escape_like(f.q.strip())
        stmt = stmt.where(
            or_(
                Product.external_id.ilike(f"{term.upper()}%", escape="\\"),
                Product.product_name.ilike(f"%{term}%", escape="\\"),
                Product.brand_name.ilike(f"%{term}%", escape="\\"),
            )
        )
    if f.marketplace:
        stmt = stmt.where(Marketplace.code == f.marketplace)
    if f.brand == NO_BRAND:
        stmt = stmt.where(Product.brand_name.is_(None))
    elif f.brand:
        stmt = stmt.where(Product.brand_name == f.brand)
    if f.scan_status == "not_scanned":
        stmt = stmt.where(Latest.id.is_(None))
    elif f.scan_status:
        stmt = stmt.where(Latest.status == f.scan_status)
    # Products whose seller count is unknown match neither True nor False.
    if f.multiple_sellers is True:
        stmt = stmt.where(Latest.unique_seller_count >= 2)
    elif f.multiple_sellers is False:
        stmt = stmt.where(Latest.unique_seller_count < 2)
    if f.monitoring is not None:
        stmt = stmt.where(Product.monitoring_enabled.is_(f.monitoring))
    return stmt


SORT_COLUMNS: dict[SortField, Any] = {
    "created_at": Product.created_at,
    "external_id": Product.external_id,
    "product_name": Product.product_name,
    "brand_name": Product.brand_name,
    "last_scanned_at": Product.last_scanned_at,
    "total_offer_count": Latest.total_offer_count,
    "unique_seller_count": Latest.unique_seller_count,
    "lowest_observed_price": Latest.lowest_observed_price,
    "highest_observed_price": Latest.highest_observed_price,
}


def apply_sort(stmt: ProductSelect, sort: SortField, descending: bool) -> ProductSelect:
    column = SORT_COLUMNS[sort]
    ordered = column.desc() if descending else column.asc()
    # Unknown values always sort last, whatever the direction; id breaks ties stably.
    return stmt.order_by(ordered.nulls_last(), Product.id)


def to_out(product: Product, marketplace_code: str, latest: ScanResult | None) -> ProductOut:
    return ProductOut(
        id=product.id,
        marketplace=marketplace_code,
        external_id=product.external_id,
        product_name=product.product_name,
        brand_name=product.brand_name,
        identifier_status=product.identifier_status,
        monitoring_enabled=product.monitoring_enabled,
        created_at=product.created_at,
        last_scanned_at=product.last_scanned_at,
        scan_status=latest.status if latest else "not_scanned",
        latest_scan=LatestScan.model_validate(latest) if latest else None,
    )


async def get_product_out(
    session: AsyncSession, organization_id: uuid.UUID, product_id: uuid.UUID
) -> ProductOut | None:
    row = (
        await session.execute(base_query(organization_id).where(Product.id == product_id))
    ).one_or_none()
    return to_out(*row) if row else None
