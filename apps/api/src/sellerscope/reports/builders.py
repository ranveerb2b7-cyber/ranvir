"""Report contents. Each builder runs inside the organization's tenant context.

Unknown values stay None (written as empty cells) and every row that has one says why in its
"Notes" column. Metrics are never derived from one another (CLAUDE.md).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.connectors.base import Limitation
from sellerscope.models import (
    Alert,
    AlertDelivery,
    Marketplace,
    Organization,
    Product,
    ProductOffer,
    ScanJob,
    ScanJobItem,
    ScanResult,
    SellerProfile,
    User,
)
from sellerscope.models.enums import AlertChannel, ReportType, ScanResultStatus
from sellerscope.reports.filters import (
    AlertFilters,
    DateRange,
    ProductFilters,
    SellerFilters,
    _Filters,
)
from sellerscope.reports.writers import Cell, Column, Report

USABLE = (ScanResultStatus.OK, ScanResultStatus.PARTIAL)
NO_DATA = (ScanResultStatus.UNAVAILABLE, ScanResultStatus.NOT_FOUND)
MOCK_SOURCE = "MOCK"

LIMITATION_TEXT: dict[str, str] = {
    Limitation.MOCK_DATA: "MOCK data: generated for testing, not real Amazon.in offers.",
    Limitation.SELLER_NAME_NOT_PROVIDED: (
        "Amazon does not provide seller names; sellers are identified by ID."
    ),
    Limitation.SELLER_ID_NOT_PROVIDED: (
        "Some offers had no seller ID, so the seller count is unknown."
    ),
    Limitation.OFFER_LIST_TRUNCATED: (
        "Amazon returned only part of the offer list; observed counts are a lower bound."
    ),
    Limitation.TOTAL_OFFER_COUNT_NOT_PROVIDED: "Amazon did not report a total offer count.",
    Limitation.SOURCE_UNAVAILABLE: "The data source could not provide data.",
    Limitation.PRODUCT_NOT_FOUND: "The product was not found on the marketplace.",
}
STATUS_TEXT = {
    "ok": "OK",
    "partial": "Partial",
    "unavailable": "Unavailable",
    "not_found": "Not found",
    "error": "Failed",
}
BLANKS = "Empty cells mean the value is not available (never zero). The Notes column says why."


class TooManyRowsError(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(
            f"This report has more than {limit:,} rows. Narrow the filters and try again."
        )


@dataclass(slots=True)
class Ctx:
    session: AsyncSession
    org: uuid.UUID
    now: datetime
    max_rows: int

    def check(self, rows: Sequence[Any]) -> None:
        if len(rows) > self.max_rows:
            raise TooManyRowsError(self.max_rows)


def _notes(*parts: str | None) -> str | None:
    seen = [p for p in dict.fromkeys(parts) if p]
    return " ".join(seen) or None


def _is_mock(source: str | None, limitations: Sequence[str] | None) -> bool:
    return source == MOCK_SOURCE or Limitation.MOCK_DATA in (limitations or [])


def _bounds(f: DateRange, now: datetime) -> tuple[datetime, datetime, str]:
    start, end = f.resolved(now.date())
    lo = datetime.combine(start, time.min, UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, UTC)
    return lo, hi, f"Period: {start.isoformat()} to {end.isoformat()} (UTC, inclusive)."


async def _header(ctx: Ctx, title: str, filters: list[str]) -> list[str]:
    org_name = (
        await ctx.session.execute(select(Organization.name).where(Organization.id == ctx.org))
    ).scalar_one()
    return [
        f"SellerScope {title} report for {org_name}",
        f"Generated {ctx.now.astimezone(UTC):%Y-%m-%d %H:%M} UTC. All times are UTC.",
        *filters,
        BLANKS,
    ]


def _mock_line(contains_mock: bool) -> list[str]:
    return (
        ["WARNING: this report contains MOCK data generated for testing, not real Amazon.in data."]
        if contains_mock
        else []
    )


# ------------------------------------------------------------------------------ products

PRODUCT_COLUMNS = (
    Column("ASIN", width=14),
    Column("Product name", width=36),
    Column("Brand", width=20),
    Column("Marketplace", width=12),
    Column("Monitoring", "bool", 11),
    Column("Identifier status", width=16),
    Column("Data as of (UTC)", "datetime", 20),
    Column("Data status", width=12),
    Column("Data source", width=22),
    Column("Total offers (reported by Amazon)", "int", 14),
    Column("Offers observed", "int", 12),
    Column("Unique sellers", "int", 12),
    Column("Offer list complete", "bool", 12),
    Column("Lowest price", "money", 12),
    Column("Highest price", "money", 12),
    Column("Buy Box price", "money", 12),
    Column("Currency", width=9),
    Column("Last scan attempt (UTC)", "datetime", 20),
    Column("Last attempt result", width=14),
    Column("Notes", width=60),
)


async def product_report(ctx: Ctx, f: ProductFilters) -> Report:
    last_attempt = (
        select(
            ScanResult.product_id,
            ScanResult.status,
            ScanResult.error_code,
            ScanResult.retrieved_at,
        )
        .where(ScanResult.organization_id == ctx.org)
        .order_by(ScanResult.product_id, ScanResult.retrieved_at.desc(), ScanResult.id.desc())
        .ext(distinct_on(ScanResult.product_id))
        .subquery()
    )
    stmt = (
        select(Product, Marketplace.name, ScanResult, last_attempt)
        .join(Marketplace, Marketplace.id == Product.marketplace_id)
        .outerjoin(
            ScanResult,
            and_(
                ScanResult.id == Product.latest_scan_result_id,
                ScanResult.organization_id == Product.organization_id,
            ),
        )
        .outerjoin(last_attempt, last_attempt.c.product_id == Product.id)
        .where(Product.organization_id == ctx.org, Product.deleted_at.is_(None))
        .order_by(Product.external_id, Product.id)
        .limit(ctx.max_rows + 1)
    )
    applied = []
    if f.brand == "__none__":
        stmt = stmt.where(Product.brand_name.is_(None))
        applied.append("Brand: (no brand)")
    elif f.brand:
        stmt = stmt.where(Product.brand_name == f.brand)
        applied.append(f"Brand: {f.brand}")
    if f.monitoring is not None:
        stmt = stmt.where(Product.monitoring_enabled.is_(f.monitoring))
        applied.append(f"Monitoring: {'on' if f.monitoring else 'off'}")
    rows = (await ctx.session.execute(stmt)).all()
    ctx.check(rows)

    out: list[Sequence[Cell]] = []
    mock = False
    for p, market, r, _pid, a_status, a_error, a_at in rows:
        usable = r is not None and r.status in USABLE
        if r is not None and _is_mock(r.data_source, r.limitations):
            mock = True
        notes: list[str | None] = []
        if r is None:
            notes.append("Not scanned yet." if a_status is None else "No successful scan yet.")
        elif r.status in NO_DATA:
            notes.append(
                f"Amazon reported the product as {STATUS_TEXT[r.status].lower()}; "
                "offer data is not available."
            )
        if r is not None:
            notes += [LIMITATION_TEXT.get(code, code) for code in r.limitations]
            if usable and r.is_offer_list_truncated is None:
                notes.append("Whether the offer list is complete is unknown.")
        if a_status == ScanResultStatus.ERROR and (r is None or a_at > r.retrieved_at):
            notes.append(
                f"The latest scan failed ({a_error or 'unknown error'})"
                + ("; data shown is from the previous successful scan." if r else ".")
            )
        out.append(
            [
                p.external_id,
                p.product_name,
                p.brand_name,
                market,
                p.monitoring_enabled,
                p.identifier_status,
                r.retrieved_at if r else None,
                STATUS_TEXT.get(r.status, r.status) if r else None,
                r.data_source if r else None,
                r.total_offer_count if usable and r else None,
                r.observed_offer_count if usable and r else None,
                r.unique_seller_count if usable and r else None,
                (None if r.is_offer_list_truncated is None else not r.is_offer_list_truncated)
                if usable and r
                else None,
                r.lowest_observed_price if usable and r else None,
                r.highest_observed_price if usable and r else None,
                r.buy_box_price if usable and r else None,
                r.currency if usable and r else None,
                a_at,
                STATUS_TEXT.get(a_status, a_status) if a_status else None,
                _notes(*notes),
            ]
        )
    about = await _header(ctx, "Products", applied or ["Filters: none (all products)."])
    about += [
        "One row per product. Offer figures come from the product's latest scan that returned "
        "data; a newer failed scan is noted but does not replace them.",
        "'Total offers' is what Amazon reports; 'Offers observed' is how many individual offers "
        "were received (Amazon returns at most about 20). They are different numbers.",
        "Prices include shipping (landed price).",
    ]
    about += _mock_line(mock)
    return Report("Products", PRODUCT_COLUMNS, out, about, mock)


# ------------------------------------------------------------------------------ marketplace

MARKET_COLUMNS = (
    Column("Marketplace", width=14),
    Column("Products", "int", 10),
    Column("Monitored", "int", 10),
    Column("Scanned", "int", 10),
    Column("With usable data", "int", 12),
    Column("With multiple sellers", "int", 12),
    Column("Seller count unknown", "int", 12),
    Column("Offers observed", "int", 12),
    Column("Unavailable or not found", "int", 14),
    Column("Last scan (UTC)", "datetime", 20),
    Column("Notes", width=60),
)


def _count_if(condition: Any) -> Any:
    return func.count().filter(condition)


async def marketplace_report(ctx: Ctx, _: _Filters) -> Report:
    stmt = (
        select(
            Marketplace.name,
            func.count(Product.id),
            func.count(Product.id).filter(Product.monitoring_enabled),
            func.count(ScanResult.id),
            _count_if(ScanResult.status.in_(USABLE)),
            _count_if(and_(ScanResult.status.in_(USABLE), ScanResult.unique_seller_count >= 2)),
            _count_if(
                and_(ScanResult.status.in_(USABLE), ScanResult.unique_seller_count.is_(None))
            ),
            func.sum(ScanResult.observed_offer_count).filter(ScanResult.status.in_(USABLE)),
            _count_if(ScanResult.status.in_(NO_DATA)),
            func.max(ScanResult.retrieved_at),
            func.bool_or(ScanResult.data_source == MOCK_SOURCE),
        )
        .select_from(Marketplace)
        .outerjoin(
            Product,
            and_(
                Product.marketplace_id == Marketplace.id,
                Product.organization_id == ctx.org,
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
    rows = (await ctx.session.execute(stmt)).all()
    out: list[Sequence[Cell]] = []
    mock = False
    for name, products, monitored, scanned, usable, multi, unknown, offers, nodata, last, m in rows:
        mock = mock or bool(m)
        if not scanned:
            out.append(
                [
                    name,
                    products,
                    monitored,
                    0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "No scans yet: scan-based figures are not available.",
                ]
            )
            continue
        out.append(
            [
                name,
                products,
                monitored,
                scanned,
                usable,
                multi if usable else None,
                unknown if usable else None,
                int(offers) if offers is not None else None,
                nodata,
                last,
                _notes(
                    f"'With multiple sellers' excludes {unknown} product(s) whose seller "
                    "count is unknown."
                    if unknown
                    else None,
                    "No product has usable offer data yet." if not usable else None,
                    LIMITATION_TEXT[Limitation.MOCK_DATA] if m else None,
                ),
            ]
        )
    about = await _header(ctx, "Marketplace", ["Filters: none."])
    about += [
        "Figures use each product's latest scan that returned data.",
        "'Scanned' counts products with at least one such scan.",
    ]
    about += _mock_line(mock)
    return Report("Marketplaces", MARKET_COLUMNS, out, about, mock)


# ------------------------------------------------------------------------------ brands

BRAND_COLUMNS = (
    Column("Brand", width=24),
    Column("Products", "int", 10),
    Column("Monitored", "int", 10),
    Column("With usable data", "int", 12),
    Column("With multiple sellers", "int", 12),
    Column("Seller count unknown", "int", 12),
    Column("Offers observed", "int", 12),
    Column("Distinct sellers observed", "int", 14),
    Column("Lowest price", "money", 12),
    Column("Highest price", "money", 12),
    Column("Currency", width=9),
    Column("Unavailable or not found", "int", 14),
    Column("Notes", width=60),
)


async def brand_report(ctx: Ctx, _: _Filters) -> Report:
    usable = ScanResult.status.in_(USABLE)
    stmt = (
        select(
            Product.brand_name,
            func.count(Product.id),
            func.count(Product.id).filter(Product.monitoring_enabled),
            _count_if(usable),
            _count_if(and_(usable, ScanResult.unique_seller_count >= 2)),
            _count_if(and_(usable, ScanResult.unique_seller_count.is_(None))),
            func.sum(ScanResult.observed_offer_count).filter(usable),
            func.min(ScanResult.lowest_observed_price).filter(usable),
            func.max(ScanResult.highest_observed_price).filter(usable),
            func.max(ScanResult.currency).filter(usable),
            _count_if(ScanResult.status.in_(NO_DATA)),
            _count_if(and_(usable, ScanResult.is_offer_list_truncated.is_not(False))),
            func.bool_or(ScanResult.data_source == MOCK_SOURCE),
        )
        .outerjoin(
            ScanResult,
            and_(
                ScanResult.id == Product.latest_scan_result_id,
                ScanResult.organization_id == Product.organization_id,
            ),
        )
        .where(Product.organization_id == ctx.org, Product.deleted_at.is_(None))
        .group_by(Product.brand_name)
        .order_by(Product.brand_name.nulls_last())
        .limit(ctx.max_rows + 1)
    )
    rows = (await ctx.session.execute(stmt)).all()
    ctx.check(rows)
    distinct = dict(
        (
            await ctx.session.execute(
                select(
                    Product.brand_name, func.count(func.distinct(ProductOffer.seller_profile_id))
                )
                .join(
                    ProductOffer,
                    and_(
                        ProductOffer.scan_result_id == Product.latest_scan_result_id,
                        ProductOffer.organization_id == Product.organization_id,
                    ),
                )
                .where(Product.organization_id == ctx.org, Product.deleted_at.is_(None))
                .group_by(Product.brand_name)
            )
        ).all()
    )
    out: list[Sequence[Cell]] = []
    mock = False
    for (
        brand,
        products,
        monitored,
        n_usable,
        multi,
        unknown,
        offers,
        lo,
        hi,
        cur,
        nodata,
        cut,
        m,
    ) in rows:
        mock = mock or bool(m)
        has = n_usable > 0
        sellers = distinct.get(brand, 0) if has and not unknown else None
        out.append(
            [
                brand if brand is not None else "(no brand)",
                products,
                monitored,
                n_usable,
                multi if has else None,
                unknown if has else None,
                int(offers) if has and offers is not None else None,
                sellers,
                lo,
                hi,
                cur if lo is not None else None,
                nodata,
                _notes(
                    "No product of this brand has usable offer data yet." if not has else None,
                    f"{unknown} product(s) have an unknown seller count, so distinct sellers "
                    "is not available and they are excluded from 'With multiple sellers'."
                    if has and unknown
                    else None,
                    f"{cut} product(s) had a cut-off or possibly incomplete offer list: "
                    "observed figures are a lower bound."
                    if has and cut
                    else None,
                    LIMITATION_TEXT[Limitation.MOCK_DATA] if m else None,
                ),
            ]
        )
    about = await _header(ctx, "Brands", ["Filters: none."])
    about += [
        "One row per brand (products without a brand are grouped as '(no brand)').",
        "Figures use each product's latest scan that returned data. Prices include shipping.",
    ]
    about += _mock_line(mock)
    return Report("Brands", BRAND_COLUMNS, out, about, mock)


# ------------------------------------------------------------------------------ sellers

SELLER_COLUMNS = (
    Column("Seller ID", width=18),
    Column("Your name for the seller", width=24),
    Column("Tags", width=20),
    Column("Your notes", width=30),
    Column("First observed (UTC)", "datetime", 20),
    Column("Last observed (UTC)", "datetime", 20),
    Column("Products offering now", "int", 12),
    Column("Buy Box held now", "int", 12),
    Column("Lowest current price", "money", 12),
    Column("Currency", width=9),
    Column("ASINs offering now", width=40),
    Column("Notes", width=50),
)


async def seller_report(ctx: Ctx, f: SellerFilters) -> Report:
    current = (
        select(
            ProductOffer.seller_profile_id,
            Product.external_id,
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
            ProductOffer.organization_id == ctx.org,
            Product.deleted_at.is_(None),
            ProductOffer.seller_profile_id.is_not(None),
        )
    )
    by_seller: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for row in (await ctx.session.execute(current)).all():
        by_seller[row.seller_profile_id].append(row)
    stmt = (
        select(SellerProfile)
        .where(SellerProfile.organization_id == ctx.org)
        .order_by(SellerProfile.external_seller_id)
        .limit(ctx.max_rows + 1)
    )
    applied = []
    if f.tag:
        stmt = stmt.where(SellerProfile.tags.contains([f.tag]))
        applied.append(f"Tag: {f.tag}")
    sellers = list((await ctx.session.execute(stmt)).scalars())
    ctx.check(sellers)
    out: list[Sequence[Cell]] = []
    mock = False
    for s in sellers:
        offers = by_seller.get(s.id, [])
        if f.currently_offering is not None and bool(offers) != f.currently_offering:
            continue
        is_mock = s.external_seller_id.startswith(MOCK_SOURCE)
        mock = mock or is_mock
        prices = [(o.landed_price, o.currency) for o in offers if o.landed_price is not None]
        low = min(prices, default=None, key=lambda p: p[0])
        out.append(
            [
                s.external_seller_id,
                s.display_name,
                ", ".join(s.tags) or None,
                s.notes,
                s.first_observed_at,
                s.last_observed_at,
                len({o.external_id for o in offers}),
                sum(1 for o in offers if o.is_buy_box_winner),
                low[0] if low else None,
                low[1] if low else None,
                "; ".join(sorted({o.external_id for o in offers})) or None,
                _notes(
                    "Not in any product's latest scan." if not offers else None,
                    "No current offer had a known price." if offers and not low else None,
                    "MOCK seller generated for testing." if is_mock else None,
                ),
            ]
        )
    if f.currently_offering is not None:
        applied.append(f"Currently offering: {'yes' if f.currently_offering else 'no'}")
    about = await _header(ctx, "Sellers", applied or ["Filters: none (all sellers)."])
    about += [
        "Every seller seen on your products. 'Now' columns use each product's latest scan "
        "that returned data. Amazon gives seller IDs, not names; names are your own labels.",
    ]
    about += _mock_line(mock)
    return Report("Sellers", SELLER_COLUMNS, out, about, mock)


# ------------------------------------------------------------------------------ scan summary

SCAN_COLUMNS = (
    Column("Job ID", width=38),
    Column("Type", width=12),
    Column("Status", width=22),
    Column("Requested by", width=28),
    Column("Created (UTC)", "datetime", 20),
    Column("Started (UTC)", "datetime", 20),
    Column("Finished (UTC)", "datetime", 20),
    Column("Products", "int", 10),
    Column("Completed", "int", 10),
    Column("Unavailable", "int", 11),
    Column("Failed", "int", 10),
    Column("Cancelled", "int", 10),
)


async def scan_summary_report(ctx: Ctx, f: DateRange) -> Report:
    lo, hi, period = _bounds(f, ctx.now)
    rows = (
        await ctx.session.execute(
            select(ScanJob, User.email)
            .outerjoin(User, User.id == ScanJob.requested_by)
            .where(
                ScanJob.organization_id == ctx.org,
                ScanJob.created_at >= lo,
                ScanJob.created_at < hi,
            )
            .order_by(ScanJob.created_at.desc(), ScanJob.id.desc())
            .limit(ctx.max_rows + 1)
        )
    ).all()
    ctx.check(rows)
    out: list[Sequence[Cell]] = [
        [
            str(j.id),
            j.trigger,
            j.status.replace("_", " "),
            email or ("Scheduler" if j.trigger == "scheduled" else None),
            j.created_at,
            j.started_at,
            j.finished_at,
            j.total_items,
            j.completed_items,
            j.unavailable_items,
            j.failed_items,
            j.cancelled_items,
        ]
        for j, email in rows
    ]
    about = await _header(ctx, "Scan summary", [period])
    about.append("One row per scan job, newest first.")
    return Report("Scans", SCAN_COLUMNS, out, about, False)


# ------------------------------------------------------------------------------ errors

ERROR_COLUMNS = (
    Column("Time (UTC)", "datetime", 20),
    Column("ASIN", width=14),
    Column("Product name", width=30),
    Column("Brand", width=18),
    Column("Result", width=12),
    Column("Error code", width=22),
    Column("Message", width=60),
    Column("Data source", width=22),
    Column("Job ID", width=38),
)


async def errors_report(ctx: Ctx, f: DateRange) -> Report:
    lo, hi, period = _bounds(f, ctx.now)
    rows = (
        await ctx.session.execute(
            select(ScanResult, Product, ScanJobItem.scan_job_id, ScanJobItem.last_error_message)
            .join(
                Product,
                and_(
                    Product.id == ScanResult.product_id,
                    Product.organization_id == ScanResult.organization_id,
                ),
            )
            .join(
                ScanJobItem,
                and_(
                    ScanJobItem.id == ScanResult.scan_job_item_id,
                    ScanJobItem.organization_id == ScanResult.organization_id,
                ),
            )
            .where(
                ScanResult.organization_id == ctx.org,
                ScanResult.status.in_((ScanResultStatus.ERROR, *NO_DATA)),
                ScanResult.retrieved_at >= lo,
                ScanResult.retrieved_at < hi,
            )
            .order_by(ScanResult.retrieved_at.desc(), ScanResult.id.desc())
            .limit(ctx.max_rows + 1)
        )
    ).all()
    ctx.check(rows)
    out: list[Sequence[Cell]] = []
    mock = False
    for r, p, job_id, message in rows:
        mock = mock or _is_mock(r.data_source, r.limitations)
        if r.status == ScanResultStatus.ERROR:
            text = message or "The scan failed."
        else:
            text = f"Amazon reported the product as {STATUS_TEXT[r.status].lower()}."
        out.append(
            [
                r.retrieved_at,
                p.external_id,
                p.product_name,
                p.brand_name,
                STATUS_TEXT.get(r.status, r.status),
                r.error_code,
                text,
                r.data_source,
                str(job_id),
            ]
        )
    about = await _header(ctx, "Errors and unavailable products", [period])
    about += [
        "Every scan in the period that failed or found no offer data, newest first. A failed "
        "scan never replaces a product's last good data.",
    ]
    about += _mock_line(mock)
    return Report("Errors", ERROR_COLUMNS, out, about, mock)


# ------------------------------------------------------------------------------ alerts

ALERT_COLUMNS = (
    Column("Raised (UTC)", "datetime", 20),
    Column("Severity", width=10),
    Column("Status", width=13),
    Column("Rule", width=22),
    Column("Rule type", width=18),
    Column("Alert", width=50),
    Column("Details", width=60),
    Column("ASIN", width=14),
    Column("Seller ID", width=18),
    Column("Acknowledged (UTC)", "datetime", 20),
    Column("Resolved (UTC)", "datetime", 20),
    Column("Resolved automatically", "bool", 12),
    Column("Email", width=30),
)


async def alerts_report(ctx: Ctx, f: AlertFilters) -> Report:
    lo, hi, period = _bounds(f, ctx.now)
    stmt = (
        select(Alert, Product.external_id, SellerProfile.external_seller_id)
        .outerjoin(
            Product,
            and_(Product.id == Alert.product_id, Product.organization_id == Alert.organization_id),
        )
        .outerjoin(
            SellerProfile,
            and_(
                SellerProfile.id == Alert.seller_profile_id,
                SellerProfile.organization_id == Alert.organization_id,
            ),
        )
        .where(Alert.organization_id == ctx.org, Alert.created_at >= lo, Alert.created_at < hi)
        .order_by(Alert.created_at.desc(), Alert.id.desc())
        .limit(ctx.max_rows + 1)
    )
    filters = [period]
    if f.status:
        stmt = stmt.where(Alert.status == f.status)
        filters.append(f"Status: {f.status}")
    rows = (await ctx.session.execute(stmt)).all()
    ctx.check(rows)
    emails: dict[uuid.UUID, list[str]] = defaultdict(list)
    if rows:
        for alert_id, status, n in (
            await ctx.session.execute(
                select(AlertDelivery.alert_id, AlertDelivery.status, func.count())
                .where(
                    AlertDelivery.organization_id == ctx.org,
                    AlertDelivery.channel == AlertChannel.EMAIL,
                    AlertDelivery.alert_id.in_([r[0].id for r in rows]),
                )
                .group_by(AlertDelivery.alert_id, AlertDelivery.status)
                .order_by(AlertDelivery.status)
            )
        ).all():
            emails[alert_id].append(f"{n} {status}")
    out: list[Sequence[Cell]] = []
    for a, asin, seller in rows:
        out.append(
            [
                a.created_at,
                a.severity,
                a.status,
                a.rule_name,
                a.rule_type,
                a.title,
                a.body,
                asin,
                seller,
                a.acknowledged_at,
                a.resolved_at,
                (a.resolved_by is None) if a.resolved_at else None,
                ", ".join(emails.get(a.id, [])) or None,
            ]
        )
    about = await _header(ctx, "Alerts", filters)
    about.append("Every alert raised in the period, newest first. Email shows delivery counts.")
    return Report("Alerts", ALERT_COLUMNS, out, about, False)


Builder = Callable[[Ctx, Any], Awaitable[Report]]
BUILDERS: dict[ReportType, Builder] = {
    ReportType.PRODUCT: product_report,
    ReportType.MARKETPLACE: marketplace_report,
    ReportType.BRAND: brand_report,
    ReportType.SELLER: seller_report,
    ReportType.SCAN_SUMMARY: scan_summary_report,
    ReportType.ERRORS: errors_report,
    ReportType.ALERTS: alerts_report,
}
