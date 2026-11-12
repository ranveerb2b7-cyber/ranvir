"""Dashboard KPIs.

Counts of products are always known. Scan-derived metrics are null (with a reason) until at
least one scan exists, so "nothing scanned yet" is never displayed as 0.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import ColumnElement, Integer, and_, cast, func, select

from sellerscope.auth.deps import OrgDep, SessionDep
from sellerscope.models import Alert, Marketplace, Product, ScanHistory, ScanResult
from sellerscope.models.enums import AlertStatus, HistoryEventType, ScanResultStatus
from sellerscope.schemas.products import DashboardSummary, MarketplaceBreakdown, Metric

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

NO_SCANS = "no_scans_yet"
CHANGE_TRACKING_OFF = "change_tracking_not_available"
# Seller changes are detected by comparing consecutive scans (scanning/diff.py, since M8).
CHANGE_TRACKING_ENABLED = True
SUCCESS = (ScanResultStatus.OK, ScanResultStatus.PARTIAL)
UNAVAILABLE = (ScanResultStatus.UNAVAILABLE, ScanResultStatus.ERROR, ScanResultStatus.NOT_FOUND)


def _count_if(condition: Any) -> ColumnElement[int]:
    """Number of rows where `condition` is true."""
    return func.coalesce(func.sum(cast(condition, Integer)), 0)


@router.get("/summary", response_model=DashboardSummary)
async def summary(session: SessionDep, ctx: OrgDep) -> DashboardSummary:
    latest = (
        select(
            Marketplace.code.label("code"),
            Marketplace.name.label("name"),
            func.count(Product.id).label("products"),
            _count_if(Product.monitoring_enabled).label("monitored"),
            func.count(ScanResult.id).label("scanned"),
            _count_if(ScanResult.status.in_(SUCCESS)).label("successful"),
            _count_if(ScanResult.status.in_(UNAVAILABLE)).label("unavailable"),
            _count_if(ScanResult.unique_seller_count >= 2).label("multi"),
            _count_if(
                and_(ScanResult.id.isnot(None), ScanResult.unique_seller_count.is_(None))
            ).label("seller_unknown"),
            func.coalesce(
                func.sum(ScanResult.observed_offer_count).filter(ScanResult.status.in_(SUCCESS)), 0
            ).label("offers"),
            func.max(ScanResult.retrieved_at).label("last_scan_at"),
        )
        .select_from(Marketplace)
        .outerjoin(
            Product,
            and_(
                Product.marketplace_id == Marketplace.id,
                Product.organization_id == ctx.organization_id,
                Product.deleted_at.is_(None),
            ),
        )
        .outerjoin(
            ScanResult,
            and_(
                ScanResult.id == Product.latest_scan_result_id,
                ScanResult.organization_id == Product.organization_id,
            ),
        )
        .where(Marketplace.is_enabled.is_(True))
        .group_by(Marketplace.code, Marketplace.name)
        .order_by(Marketplace.code)
    )
    rows = (await session.execute(latest)).all()

    scanned = sum(r.scanned for r in rows)
    has_scans = scanned > 0
    unknown = sum(r.seller_unknown for r in rows)

    def scan_metric(value: int, note: str | None = None) -> Metric:
        return (
            Metric(value=value, reason=note) if has_scans else Metric(value=None, reason=NO_SCANS)
        )

    new_sellers = Metric(value=None, reason=NO_SCANS)
    if has_scans and not CHANGE_TRACKING_ENABLED:
        new_sellers = Metric(value=None, reason=CHANGE_TRACKING_OFF)
    elif has_scans:
        count = (
            await session.execute(
                select(func.count())
                .select_from(ScanHistory)
                .where(
                    ScanHistory.organization_id == ctx.organization_id,
                    ScanHistory.event_type == HistoryEventType.SELLER_NEWLY_OBSERVED,
                    ScanHistory.created_at >= datetime.now(UTC) - timedelta(days=7),
                )
            )
        ).scalar_one()
        new_sellers = Metric(value=count)

    unknown_note = (
        f"excludes {unknown} product(s) whose seller data was not available" if unknown else None
    )
    last_scan = max((r.last_scan_at for r in rows if r.last_scan_at), default=None)
    # A count of this organization's own alert records: zero is a known value.
    open_alerts = (
        await session.execute(
            select(func.count())
            .select_from(Alert)
            .where(Alert.organization_id == ctx.organization_id, Alert.status == AlertStatus.OPEN)
        )
    ).scalar_one()
    return DashboardSummary(
        total_products_monitored=Metric(value=sum(r.monitored for r in rows)),
        products_successfully_scanned=scan_metric(sum(r.successful for r in rows)),
        products_with_multiple_sellers=scan_metric(sum(r.multi for r in rows), unknown_note),
        total_offers_observed=scan_metric(sum(r.offers for r in rows)),
        new_sellers_detected_7d=new_sellers,
        products_with_unavailable_data=scan_metric(sum(r.unavailable for r in rows)),
        open_alerts=Metric(value=open_alerts),
        last_scan_at=last_scan,
        marketplaces=[
            MarketplaceBreakdown(
                marketplace=r.code,
                name=r.name,
                products=r.products,
                scanned=r.scanned,
                with_multiple_sellers=(
                    Metric(value=r.multi) if r.scanned else Metric(value=None, reason=NO_SCANS)
                ),
                total_offers_observed=(
                    Metric(value=r.offers) if r.scanned else Metric(value=None, reason=NO_SCANS)
                ),
            )
            for r in rows
        ],
    )
