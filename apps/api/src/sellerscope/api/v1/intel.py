"""Seller intelligence, product offers/history/trends and the organization change feed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.auth.deps import OrgContext, OrgDep, SessionDep, require
from sellerscope.auth.permissions import Permission
from sellerscope.core.errors import AppError, not_found
from sellerscope.models import Product, ProductOffer, ScanHistory, ScanResult, SellerProfile
from sellerscope.models.enums import HistoryEventType, ScanResultStatus
from sellerscope.schemas.intel import (
    ChangeEvent,
    ChangePage,
    CompareCell,
    CompareRow,
    OfferRow,
    Presence,
    ProductOffers,
    ProductRef,
    ScanSnapshot,
    SellerComparison,
    SellerDetail,
    SellerOffer,
    SellerPage,
    SellerProduct,
    SellerRef,
    SellerSummary,
    SellerUpdate,
    SnapshotPage,
    TrendPoint,
)
from sellerscope.services import audit

router = APIRouter(tags=["seller intelligence"])
WriteProducts = Annotated[OrgContext, Depends(require(Permission.PRODUCTS_WRITE))]
USABLE = (ScanResultStatus.OK, ScanResultStatus.PARTIAL)


def _product_ref(p: Product) -> ProductRef:
    return ProductRef(
        id=p.id, external_id=p.external_id, product_name=p.product_name, brand_name=p.brand_name
    )


def _seller_ref(s: SellerProfile | None) -> SellerRef | None:
    return SellerRef.model_validate(s) if s else None


def _offer(o: ProductOffer) -> SellerOffer:
    return SellerOffer.model_validate(o)


# ------------------------------------------------------------------------------ sellers


def _current_offers(org: uuid.UUID) -> Any:
    """Offers in each live product's LATEST snapshot."""
    return (
        select(
            ProductOffer.seller_profile_id.label("sid"),
            ProductOffer.product_id,
            ProductOffer.landed_price,
            ProductOffer.currency,
            ProductOffer.is_buy_box_winner,
        )
        .join(
            Product,
            and_(
                Product.latest_scan_result_id == ProductOffer.scan_result_id,
                Product.organization_id == ProductOffer.organization_id,
            ),
        )
        .where(
            ProductOffer.organization_id == org,
            Product.deleted_at.is_(None),
            ProductOffer.seller_profile_id.isnot(None),
        )
        .subquery()
    )


def _summary_query(org: uuid.UUID) -> Select[Any]:
    cur = _current_offers(org)
    return (
        select(
            SellerProfile,
            func.count(func.distinct(cur.c.product_id)).label("products"),
            func.coalesce(func.sum(case((cur.c.is_buy_box_winner.is_(True), 1), else_=0)), 0).label(
                "buy_box"
            ),
            func.min(cur.c.landed_price).label("lowest"),
            func.max(cur.c.currency).label("currency"),
        )
        .outerjoin(cur, cur.c.sid == SellerProfile.id)
        .where(SellerProfile.organization_id == org)
        .group_by(SellerProfile.id)
    )


def _summary(row: Any) -> SellerSummary:
    s: SellerProfile = row[0]
    return SellerSummary(
        id=s.id,
        external_seller_id=s.external_seller_id,
        display_name=s.display_name,
        display_name_source=s.display_name_source,
        tags=s.tags,
        first_observed_at=s.first_observed_at,
        last_observed_at=s.last_observed_at,
        products_currently_offering=row.products,
        buy_box_count=row.buy_box,
        lowest_current_price=row.lowest,
        currency=row.currency if row.lowest is not None else None,
        is_mock=s.external_seller_id.startswith("MOCK"),
    )


@router.get("/sellers", response_model=SellerPage)
async def list_sellers(
    session: SessionDep,
    ctx: OrgDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    tag: Annotated[str | None, Query(max_length=40)] = None,
    currently_offering: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> SellerPage:
    """Sellers seen on your products, most widespread first.

    Ordering and the "currently offering" filter use per-seller aggregates, so the (bounded)
    per-organization seller list is aggregated in one query and paged in memory.
    """
    stmt = _summary_query(ctx.organization_id)
    if q:
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(
            or_(
                SellerProfile.external_seller_id.ilike(f"%{term}%", escape="\\"),
                SellerProfile.display_name.ilike(f"%{term}%", escape="\\"),
            )
        )
    if tag:
        stmt = stmt.where(SellerProfile.tags.contains([tag]))
    summaries = [_summary(r) for r in (await session.execute(stmt)).all()]
    if currently_offering is not None:
        summaries = [
            s for s in summaries if (s.products_currently_offering > 0) == currently_offering
        ]
    summaries.sort(
        key=lambda s: (
            -s.products_currently_offering,
            -s.last_observed_at.timestamp(),
            s.external_seller_id,
        )
    )
    start = (page - 1) * page_size
    return SellerPage(
        items=summaries[start : start + page_size],
        total=len(summaries),
        page=page,
        page_size=page_size,
    )


async def _seller(session: AsyncSession, ctx: OrgContext, seller_id: uuid.UUID) -> Any:
    row = (
        await session.execute(
            _summary_query(ctx.organization_id).where(SellerProfile.id == seller_id)
        )
    ).one_or_none()
    if row is None:
        raise not_found("Seller")
    return row


def _presence(latest: ScanResult | None, current: ProductOffer | None) -> Presence:
    if current is not None:
        return "observed"
    if latest is None or latest.status not in USABLE or latest.unique_seller_count is None:
        return "unknown"
    return (
        "no_longer_observed"
        if latest.is_offer_list_truncated is False
        else "not_observed_inconclusive"
    )


async def _events(
    session: AsyncSession, org: uuid.UUID, *conditions: Any, limit: int, offset: int = 0
) -> tuple[list[ChangeEvent], int]:
    base = (
        select(ScanHistory, Product, SellerProfile)
        .join(
            Product,
            and_(
                Product.id == ScanHistory.product_id,
                Product.organization_id == ScanHistory.organization_id,
            ),
        )
        .outerjoin(
            SellerProfile,
            and_(
                SellerProfile.id == ScanHistory.seller_profile_id,
                SellerProfile.organization_id == ScanHistory.organization_id,
            ),
        )
        .where(ScanHistory.organization_id == org, *conditions)
    )
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.execute(
            base.order_by(ScanHistory.created_at.desc(), ScanHistory.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        ChangeEvent(
            id=h.id,
            created_at=h.created_at,
            event_type=h.event_type,
            confidence=h.confidence,
            product=_product_ref(p),
            seller=_seller_ref(s),
            old_value=h.old_value,
            new_value=h.new_value,
            scan_result_id=h.scan_result_id,
            previous_scan_result_id=h.previous_scan_result_id,
        )
        for h, p, s in rows
    ], total


@router.get("/sellers/compare", response_model=SellerComparison)
async def compare_sellers(
    session: SessionDep,
    ctx: OrgDep,
    ids: Annotated[list[uuid.UUID], Query(min_length=2, max_length=4)],
) -> SellerComparison:
    """Side by side: products any of these sellers currently offer, with each one's offer."""
    ids = list(dict.fromkeys(ids))
    if len(ids) < 2:
        raise AppError(422, "validation_error", "Choose 2 to 4 different sellers")
    sellers = [_summary(await _seller(session, ctx, i)) for i in ids]
    rows = (
        await session.execute(
            select(ProductOffer, Product)
            .join(
                Product,
                and_(
                    Product.latest_scan_result_id == ProductOffer.scan_result_id,
                    Product.organization_id == ProductOffer.organization_id,
                ),
            )
            .where(
                ProductOffer.organization_id == ctx.organization_id,
                ProductOffer.seller_profile_id.in_(ids),
                Product.deleted_at.is_(None),
            )
            .order_by(Product.external_id, ProductOffer.position)
        )
    ).all()
    matrix: dict[uuid.UUID, tuple[Product, dict[uuid.UUID, ProductOffer]]] = {}
    for offer, product in rows:
        entry = matrix.setdefault(product.id, (product, {}))
        entry[1].setdefault(offer.seller_profile_id, offer)  # type: ignore[arg-type]
    return SellerComparison(
        sellers=sellers,
        rows=[
            CompareRow(
                product=_product_ref(product),
                cells=[
                    CompareCell(seller_id=i, offer=_offer(o) if (o := offers.get(i)) else None)
                    for i in ids
                ],
            )
            for product, offers in matrix.values()
        ],
    )


@router.get("/sellers/{seller_id}", response_model=SellerDetail)
async def get_seller(seller_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> SellerDetail:
    row = await _seller(session, ctx, seller_id)
    org = ctx.organization_id
    seen = (
        await session.execute(
            select(ProductOffer.product_id, func.max(ScanResult.retrieved_at))
            .join(
                ScanResult,
                and_(
                    ScanResult.id == ProductOffer.scan_result_id,
                    ScanResult.organization_id == ProductOffer.organization_id,
                ),
            )
            .where(ProductOffer.organization_id == org, ProductOffer.seller_profile_id == seller_id)
            .group_by(ProductOffer.product_id)
        )
    ).all()
    products: list[SellerProduct] = []
    for product_id, last_seen in seen:
        product = await session.get(Product, product_id)
        if product is None or product.deleted_at is not None:
            continue
        latest = (
            await session.get(ScanResult, product.latest_scan_result_id)
            if product.latest_scan_result_id
            else None
        )
        current = (
            (
                await session.execute(
                    select(ProductOffer)
                    .where(
                        ProductOffer.scan_result_id == product.latest_scan_result_id,
                        ProductOffer.organization_id == org,
                        ProductOffer.seller_profile_id == seller_id,
                    )
                    .order_by(ProductOffer.position)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest
            else None
        )
        products.append(
            SellerProduct(
                product=_product_ref(product),
                presence=_presence(latest, current),
                last_seen_at=last_seen,
                latest_scan_at=latest.retrieved_at if latest else None,
                current_offer=_offer(current) if current else None,
            )
        )
    order = {"observed": 0, "not_observed_inconclusive": 1, "unknown": 2, "no_longer_observed": 3}
    products.sort(key=lambda p: (order[p.presence], p.product.external_id))
    events, _ = await _events(session, org, ScanHistory.seller_profile_id == seller_id, limit=50)
    return SellerDetail(
        **_summary(row).model_dump(), notes=row[0].notes, products=products, recent_changes=events
    )


@router.patch("/sellers/{seller_id}", response_model=SellerDetail)
async def update_seller(
    seller_id: uuid.UUID,
    body: SellerUpdate,
    request: Request,
    session: SessionDep,
    ctx: WriteProducts,
) -> SellerDetail:
    """Your own labels: a display name (marketplace APIs don't provide one), tags, notes."""
    seller = (
        await session.execute(
            select(SellerProfile).where(
                SellerProfile.id == seller_id, SellerProfile.organization_id == ctx.organization_id
            )
        )
    ).scalar_one_or_none()
    if seller is None:
        raise not_found("Seller")
    fields = body.model_fields_set
    if "display_name" in fields:
        seller.display_name = body.display_name or None
        seller.display_name_source = "user" if seller.display_name else None
    if "tags" in fields:
        seller.tags = list(dict.fromkeys(body.tags or []))
    if "notes" in fields:
        seller.notes = body.notes or None
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="seller.update",
        entity_type="seller_profile",
        entity_id=seller.id,
        request=request,
        details={"fields": sorted(fields)},
    )
    await session.flush()
    out = await get_seller(seller_id, session, ctx)
    await session.commit()
    return out


# ------------------------------------------------------------------------------ products


async def _product(session: AsyncSession, ctx: OrgContext, product_id: uuid.UUID) -> Product:
    product = (
        await session.execute(
            select(Product).where(
                Product.id == product_id,
                Product.organization_id == ctx.organization_id,
                Product.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise not_found("Product")
    return product


@router.get("/products/{product_id}/offers", response_model=ProductOffers)
async def product_offers(
    product_id: uuid.UUID,
    session: SessionDep,
    ctx: OrgDep,
    scan_result_id: uuid.UUID | None = None,
) -> ProductOffers:
    """Offers in the latest snapshot (or a given one) with each seller's labels."""
    product = await _product(session, ctx, product_id)
    result_id = scan_result_id or product.latest_scan_result_id
    if result_id is None:
        return ProductOffers(snapshot=None, offers=[])
    result = (
        await session.execute(
            select(ScanResult).where(
                ScanResult.id == result_id,
                ScanResult.product_id == product.id,
                ScanResult.organization_id == ctx.organization_id,
            )
        )
    ).scalar_one_or_none()
    if result is None:
        raise not_found("Scan result")
    rows = (
        await session.execute(
            select(ProductOffer, SellerProfile)
            .outerjoin(
                SellerProfile,
                and_(
                    SellerProfile.id == ProductOffer.seller_profile_id,
                    SellerProfile.organization_id == ProductOffer.organization_id,
                ),
            )
            .where(
                ProductOffer.scan_result_id == result.id,
                ProductOffer.organization_id == ctx.organization_id,
            )
            .order_by(ProductOffer.position)
        )
    ).all()
    return ProductOffers(
        snapshot=ScanSnapshot.model_validate(result),
        offers=[
            OfferRow(
                **_offer(o).model_dump(),
                position=o.position,
                seller=_seller_ref(s),
                seller_tags=s.tags if s else [],
            )
            for o, s in rows
        ],
    )


@router.get("/products/{product_id}/scans", response_model=SnapshotPage)
async def product_scans(
    product_id: uuid.UUID,
    session: SessionDep,
    ctx: OrgDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SnapshotPage:
    """Every snapshot of this product, newest first (failed scans included)."""
    await _product(session, ctx, product_id)
    base = select(ScanResult).where(
        ScanResult.product_id == product_id, ScanResult.organization_id == ctx.organization_id
    )
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.execute(
            base.order_by(ScanResult.retrieved_at.desc(), ScanResult.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars()
    return SnapshotPage(
        items=[ScanSnapshot.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/products/{product_id}/history", response_model=ChangePage)
async def product_history(
    product_id: uuid.UUID,
    session: SessionDep,
    ctx: OrgDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ChangePage:
    await _product(session, ctx, product_id)
    items, total = await _events(
        session,
        ctx.organization_id,
        ScanHistory.product_id == product_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ChangePage(items=items, total=total, page=page, page_size=page_size)


@router.get("/products/{product_id}/trends", response_model=list[TrendPoint])
async def product_trends(
    product_id: uuid.UUID,
    session: SessionDep,
    ctx: OrgDep,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> list[TrendPoint]:
    """Usable snapshots in the period, oldest first. Failed/unavailable scans are gaps."""
    await _product(session, ctx, product_id)
    rows = (
        await session.execute(
            select(ScanResult)
            .where(
                ScanResult.product_id == product_id,
                ScanResult.organization_id == ctx.organization_id,
                ScanResult.status.in_(USABLE),
                ScanResult.retrieved_at >= datetime.now(UTC) - timedelta(days=days),
            )
            .order_by(ScanResult.retrieved_at)
        )
    ).scalars()
    return [TrendPoint.model_validate(r) for r in rows]


# ------------------------------------------------------------------------------ change feed


@router.get("/changes", response_model=ChangePage)
async def change_feed(
    session: SessionDep,
    ctx: OrgDep,
    event_type: HistoryEventType | None = None,
    product_id: uuid.UUID | None = None,
    seller_id: uuid.UUID | None = None,
    include_inconclusive: bool = True,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ChangePage:
    """Detected changes across all products, newest first."""
    conditions: list[Any] = []
    if event_type:
        conditions.append(ScanHistory.event_type == event_type)
    if product_id:
        conditions.append(ScanHistory.product_id == product_id)
    if seller_id:
        conditions.append(ScanHistory.seller_profile_id == seller_id)
    if not include_inconclusive:
        conditions.append(
            ScanHistory.event_type != HistoryEventType.SELLER_NOT_OBSERVED_INCONCLUSIVE
        )
    items, total = await _events(
        session, ctx.organization_id, *conditions, limit=page_size, offset=(page - 1) * page_size
    )
    return ChangePage(items=items, total=total, page=page, page_size=page_size)
