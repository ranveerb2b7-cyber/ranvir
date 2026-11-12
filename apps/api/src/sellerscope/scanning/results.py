"""Turning connector output into append-only scan snapshots.

Metric rules (see CLAUDE.md):
- total_offer_count   = what the source REPORTED (None if not reported)
- observed_offer_count = offers actually received
- unique_seller_count = distinct seller ids among observed offers, or None if the source did
  not identify the seller of every observed offer
- lowest/highest price = over observed offers' landed price (listing + shipping)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import insert, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.connectors.base import Limitation, OfferSnapshot
from sellerscope.core.ids import uuid7
from sellerscope.models import Product, ProductOffer, ScanResult, SellerProfile
from sellerscope.models.enums import ScanResultStatus
from sellerscope.storage import Storage


def summarize(snapshot: OfferSnapshot) -> dict[str, object]:
    offers = snapshot.offers
    limitations = list(dict.fromkeys(snapshot.limitations))
    seller_ids = [o.seller_id for o in offers]
    if offers and all(seller_ids):
        unique: int | None = len(set(seller_ids))
    elif offers:
        unique = None
        if Limitation.SELLER_ID_NOT_PROVIDED not in limitations:
            limitations.append(Limitation.SELLER_ID_NOT_PROVIDED)
    else:
        # No offers observed: zero sellers only if the source affirmatively reported zero offers.
        unique = 0 if snapshot.total_offer_count == 0 else None
    prices = [p for p in (o.landed_price for o in offers) if p is not None]
    currency = snapshot.currency or next((o.currency for o in offers if o.currency), None)
    truncated = snapshot.is_offer_list_truncated
    if truncated is None and snapshot.total_offer_count is not None:
        truncated = snapshot.total_offer_count > len(offers)
    if truncated and Limitation.OFFER_LIST_TRUNCATED not in limitations:
        limitations.append(Limitation.OFFER_LIST_TRUNCATED)
    if snapshot.total_offer_count is None and snapshot.status in ("ok", "partial"):
        limitations.append(Limitation.TOTAL_OFFER_COUNT_NOT_PROVIDED)
    return {
        "total_offer_count": snapshot.total_offer_count,
        "observed_offer_count": len(offers),
        "unique_seller_count": unique,
        "is_offer_list_truncated": truncated,
        "lowest_observed_price": min(prices) if prices else None,
        "highest_observed_price": max(prices) if prices else None,
        "buy_box_price": snapshot.buy_box_price,
        "currency": currency if (prices or snapshot.buy_box_price is not None) else None,
        "limitations": limitations,
    }


async def record_snapshot(
    session: AsyncSession,
    storage: Storage | None,
    *,
    organization_id: uuid.UUID,
    marketplace_id: uuid.UUID,
    product_id: uuid.UUID,
    scan_job_item_id: uuid.UUID,
    connection_id: uuid.UUID | None,
    snapshot: OfferSnapshot,
) -> uuid.UUID:
    """Writes one immutable scan result (+ offers) and points the product at it."""
    result_id = uuid7()
    raw_key = None
    if storage is not None and snapshot.raw_payload is not None:
        raw_key = f"org/{organization_id}/scans/{result_id}.json"
        await storage.put(
            raw_key, json.dumps(snapshot.raw_payload, default=str).encode(), "application/json"
        )

    seller_profile_ids: dict[str, uuid.UUID] = {}
    seen_at = snapshot.retrieved_at
    for offer in snapshot.offers:
        if not offer.seller_id or offer.seller_id in seller_profile_ids:
            continue
        stmt = (
            pg_insert(SellerProfile)
            .values(
                id=uuid7(),
                organization_id=organization_id,
                marketplace_id=marketplace_id,
                external_seller_id=offer.seller_id,
                display_name=offer.seller_name,
                display_name_source=snapshot.source if offer.seller_name else None,
                first_observed_at=seen_at,
                last_observed_at=seen_at,
            )
            .on_conflict_do_update(
                index_elements=["organization_id", "marketplace_id", "external_seller_id"],
                set_={"last_observed_at": seen_at},
            )
            .returning(SellerProfile.id)
        )
        seller_profile_ids[offer.seller_id] = (await session.execute(stmt)).scalar_one()

    summary = summarize(snapshot)
    await session.execute(
        insert(ScanResult).values(
            id=result_id,
            organization_id=organization_id,
            scan_job_item_id=scan_job_item_id,
            product_id=product_id,
            marketplace_connection_id=connection_id,
            status=snapshot.status,
            data_source=snapshot.source,
            offer_count_breakdown=snapshot.offer_count_breakdown,
            raw_payload_key=raw_key,
            retrieved_at=snapshot.retrieved_at,
            **summary,
        )
    )
    if snapshot.offers:
        await session.execute(
            insert(ProductOffer),
            [
                {
                    "id": uuid7(),
                    "organization_id": organization_id,
                    "scan_result_id": result_id,
                    "product_id": product_id,
                    "seller_profile_id": seller_profile_ids.get(o.seller_id or ""),
                    "listing_price": o.listing_price,
                    "shipping_price": o.shipping_price,
                    "landed_price": o.landed_price,
                    "currency": o.currency if o.listing_price is not None else None,
                    "condition": o.condition,
                    "sub_condition": o.sub_condition,
                    "fulfilment_channel": o.fulfilment_channel,
                    "is_buy_box_winner": o.is_buy_box_winner,
                    "is_featured_merchant": o.is_featured_merchant,
                    "is_prime": o.is_prime,
                    "seller_feedback_rating": o.seller_feedback_rating,
                    "seller_feedback_count": o.seller_feedback_count,
                    "ships_from_country": o.ships_from_country,
                    "position": i,
                }
                for i, o in enumerate(snapshot.offers)
            ],
        )
    await session.execute(
        update(Product)
        .where(Product.id == product_id, Product.organization_id == organization_id)
        .values(latest_scan_result_id=result_id, last_scanned_at=snapshot.retrieved_at)
    )
    return result_id


async def record_failure(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    scan_job_item_id: uuid.UUID,
    source: str,
    error_code: str,
    at: datetime,
) -> uuid.UUID:
    """A failed scan is kept in history but does NOT replace the product's latest data."""
    result_id = uuid7()
    await session.execute(
        insert(ScanResult).values(
            id=result_id,
            organization_id=organization_id,
            scan_job_item_id=scan_job_item_id,
            product_id=product_id,
            status=ScanResultStatus.ERROR,
            data_source=source,
            error_code=error_code,
            retrieved_at=at,
            observed_offer_count=0,
            limitations=[Limitation.SOURCE_UNAVAILABLE],
        )
    )
    return result_id
