"""Change detection between consecutive comparable snapshots of a product.

Rules (docs/plan/02 §2.4), designed so missing data is never mistaken for a change:
- The first usable snapshot is a baseline: no events.
- Seller events need seller ids for every observed offer in BOTH snapshots.
- A seller in the new list but not the previous one is "newly observed"
  (confidence high; medium if the previous list was truncated, since it may have been there).
- A seller in the previous list but missing from the new one is "no longer observed" ONLY if
  the new list is complete; if the new list is truncated it is "not observed (inconclusive)".
- Failed scans are never diffed. A product becoming unavailable is one event, not a seller
  wipe-out, and seller comparison resumes against the last usable snapshot.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.core.ids import uuid7
from sellerscope.models import ProductOffer, ScanHistory, ScanResult, SellerProfile
from sellerscope.models.enums import Confidence, HistoryEventType, ScanResultStatus

USABLE = (ScanResultStatus.OK, ScanResultStatus.PARTIAL)
NO_DATA = (ScanResultStatus.UNAVAILABLE, ScanResultStatus.NOT_FOUND)


@dataclass(frozen=True, slots=True)
class OfferView:
    seller_profile_id: uuid.UUID | None
    seller_id: str | None
    landed_price: Decimal | None
    currency: str | None
    is_buy_box_winner: bool | None


@dataclass(slots=True)
class SnapshotView:
    result_id: uuid.UUID
    status: str
    total_offer_count: int | None
    is_offer_list_truncated: bool | None
    unique_seller_count: int | None
    offers: list[OfferView] = field(default_factory=list)

    @property
    def sellers_known(self) -> bool:
        return self.unique_seller_count is not None

    def seller_prices(self) -> dict[uuid.UUID, tuple[Decimal, str | None]]:
        best: dict[uuid.UUID, tuple[Decimal, str | None]] = {}
        for o in self.offers:
            if o.seller_profile_id is None or o.landed_price is None:
                continue
            if o.seller_profile_id not in best or o.landed_price < best[o.seller_profile_id][0]:
                best[o.seller_profile_id] = (o.landed_price, o.currency)
        return best

    def sellers(self) -> dict[uuid.UUID, str | None]:
        return {o.seller_profile_id: o.seller_id for o in self.offers if o.seller_profile_id}

    def buy_box_seller(self) -> uuid.UUID | None:
        return next((o.seller_profile_id for o in self.offers if o.is_buy_box_winner), None)


@dataclass(frozen=True, slots=True)
class Change:
    event_type: HistoryEventType
    seller_profile_id: uuid.UUID | None = None
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    confidence: Confidence | None = None


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def diff(
    previous: SnapshotView | None, current: SnapshotView, last_status: str | None = None
) -> list[Change]:
    """`previous` = last USABLE snapshot; `last_status` = status of the last non-failed one."""
    if current.status in NO_DATA:
        if last_status in USABLE:
            return [
                Change(
                    HistoryEventType.SCAN_UNAVAILABLE,
                    old_value={"status": last_status},
                    new_value={"status": current.status},
                )
            ]
        return []
    if current.status not in USABLE or previous is None:
        return []  # baseline (or nothing comparable)

    changes: list[Change] = []
    if (
        previous.total_offer_count is not None
        and current.total_offer_count is not None
        and previous.total_offer_count != current.total_offer_count
    ):
        changes.append(
            Change(
                HistoryEventType.OFFER_COUNT_CHANGED,
                old_value={"total_offer_count": previous.total_offer_count},
                new_value={"total_offer_count": current.total_offer_count},
                confidence=Confidence.HIGH,
            )
        )

    if previous.sellers_known and current.sellers_known:
        before, after = previous.sellers(), current.sellers()
        for seller in sorted(after.keys() - before.keys()):
            changes.append(
                Change(
                    HistoryEventType.SELLER_NEWLY_OBSERVED,
                    seller,
                    new_value={"seller_id": after[seller]},
                    confidence=Confidence.MEDIUM
                    if previous.is_offer_list_truncated
                    else Confidence.HIGH,
                )
            )
        for seller in sorted(before.keys() - after.keys()):
            if current.is_offer_list_truncated is False:
                changes.append(
                    Change(
                        HistoryEventType.SELLER_NO_LONGER_OBSERVED,
                        seller,
                        old_value={"seller_id": before[seller]},
                        confidence=Confidence.HIGH,
                    )
                )
            else:  # truncated or unknown completeness: absence proves nothing
                changes.append(
                    Change(
                        HistoryEventType.SELLER_NOT_OBSERVED_INCONCLUSIVE,
                        seller,
                        old_value={"seller_id": before[seller]},
                        confidence=Confidence.LOW,
                    )
                )

        old_prices, new_prices = previous.seller_prices(), current.seller_prices()
        for seller in sorted(old_prices.keys() & new_prices.keys()):
            (old_p, old_c), (new_p, new_c) = old_prices[seller], new_prices[seller]
            if old_p != new_p:
                changes.append(
                    Change(
                        HistoryEventType.PRICE_CHANGED,
                        seller,
                        old_value={
                            "seller_id": before.get(seller),
                            "price": _money(old_p),
                            "currency": old_c,
                        },
                        new_value={
                            "seller_id": after.get(seller),
                            "price": _money(new_p),
                            "currency": new_c,
                        },
                        confidence=Confidence.HIGH,
                    )
                )

        old_box, new_box = previous.buy_box_seller(), current.buy_box_seller()
        if old_box and new_box and old_box != new_box:
            changes.append(
                Change(
                    HistoryEventType.BUY_BOX_CHANGED,
                    new_box,
                    old_value={"seller_id": before.get(old_box)},
                    new_value={"seller_id": after.get(new_box)},
                    confidence=Confidence.HIGH,
                )
            )
    return changes


# ------------------------------------------------------------------------------ persistence


async def load_view(
    session: AsyncSession, organization_id: uuid.UUID, result: ScanResult
) -> SnapshotView:
    rows = (
        await session.execute(
            select(
                ProductOffer.seller_profile_id,
                SellerProfile.external_seller_id,
                ProductOffer.landed_price,
                ProductOffer.currency,
                ProductOffer.is_buy_box_winner,
            )
            .outerjoin(
                SellerProfile,
                (SellerProfile.id == ProductOffer.seller_profile_id)
                & (SellerProfile.organization_id == ProductOffer.organization_id),
            )
            .where(
                ProductOffer.scan_result_id == result.id,
                ProductOffer.organization_id == organization_id,
            )
            .order_by(ProductOffer.position)
        )
    ).all()
    return SnapshotView(
        result.id,
        result.status,
        result.total_offer_count,
        result.is_offer_list_truncated,
        result.unique_seller_count,
        [OfferView(*r) for r in rows],
    )


async def record_changes(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    result_id: uuid.UUID,
) -> list[tuple[uuid.UUID, Change]]:
    """Diffs a just-written snapshot against the product's earlier ones; writes scan_history.

    Returns (scan_history id, change) pairs, in event order.
    """
    current = (
        await session.execute(select(ScanResult).where(ScanResult.id == result_id))
    ).scalar_one()
    earlier = (
        select(ScanResult)
        .where(
            ScanResult.organization_id == organization_id,
            ScanResult.product_id == product_id,
            ScanResult.id != result_id,
            ScanResult.retrieved_at <= current.retrieved_at,
            ScanResult.status != ScanResultStatus.ERROR,
        )
        .order_by(ScanResult.retrieved_at.desc(), ScanResult.id.desc())
        .limit(1)
    )
    last_any = (await session.execute(earlier)).scalar_one_or_none()
    last_usable = (
        await session.execute(earlier.where(ScanResult.status.in_(USABLE)))
    ).scalar_one_or_none()
    previous = await load_view(session, organization_id, last_usable) if last_usable else None
    changes = diff(
        previous,
        await load_view(session, organization_id, current),
        last_any.status if last_any else None,
    )
    recorded = [(uuid7(), c) for c in changes]
    if recorded:
        reference = last_usable if current.status in USABLE else last_any
        await session.execute(
            insert(ScanHistory),
            [
                {
                    "id": history_id,
                    "organization_id": organization_id,
                    "product_id": product_id,
                    "scan_result_id": result_id,
                    "previous_scan_result_id": reference.id if reference else None,
                    "event_type": c.event_type,
                    "seller_profile_id": c.seller_profile_id,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "confidence": c.confidence,
                }
                for history_id, c in recorded
            ],
        )
    return recorded
