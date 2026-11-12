"""MOCK connector: DEVELOPMENT AND TESTS ONLY.

Produces deterministic, clearly labelled fake data so the scanning engine and UI can be built
before real marketplace credentials exist. Every snapshot has source "MOCK" and the MOCK_DATA
limitation; seller ids start with "MOCK". The app refuses to start in staging/production with
ENABLE_MOCK_CONNECTOR=true (see core.config), and the registry never offers it there.

Scenarios are chosen from a hash of the ASIN so results are stable across scans, and mimic
real SP-API shapes, including what SP-API does NOT provide (seller names, full lists > 20).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from sellerscope.connectors.base import (
    ConnectorCapabilities,
    ConnectorContext,
    ConnectorError,
    Limitation,
    ObservedOffer,
    OfferSnapshot,
)

MOCK_SOURCE = "MOCK"
MAX_LIST = 20


def _digest(asin: str) -> bytes:
    return hashlib.sha256(asin.encode()).digest()


class MockConnector:
    code = "mock"
    capabilities = ConnectorCapabilities(
        total_offer_count=True,
        offer_list=True,
        offer_list_max=MAX_LIST,
        seller_id=True,
        seller_name=False,
        price=True,
        fulfilment=True,
        batch_size=20,
        requests_per_second=5.0,
        burst=5,
    )

    def rate_limit_key(self, ctx: ConnectorContext) -> str:
        return f"mock:{ctx.organization_id}"

    def snapshot(self, asin: str) -> OfferSnapshot:
        d = _digest(asin)
        now = datetime.now(UTC)
        limitations: list[str] = [Limitation.MOCK_DATA, Limitation.SELLER_NAME_NOT_PROVIDED]
        scenario = d[0] % 10
        if scenario == 0:
            return OfferSnapshot(
                asin,
                "not_found",
                MOCK_SOURCE,
                now,
                None,
                [],
                None,
                limitations=[Limitation.MOCK_DATA, Limitation.PRODUCT_NOT_FOUND],
            )
        if scenario == 1:
            return OfferSnapshot(
                asin,
                "unavailable",
                MOCK_SOURCE,
                now,
                None,
                [],
                None,
                limitations=[Limitation.MOCK_DATA, Limitation.SOURCE_UNAVAILABLE],
            )
        if scenario == 2:
            total = 1  # single seller
        elif scenario == 3:
            total = 25 + d[1] % 20  # more offers than the list returns
        else:
            total = 2 + d[1] % 8
        observed = min(total, MAX_LIST)
        base = Decimal(199 + (d[2] * 7) % 4800)
        offers = []
        for i in range(observed):
            seller = f"MOCK{(d[3] + i * 37) % 1000:04d}"
            listing = (base + Decimal(i * (10 + d[4] % 40))).quantize(Decimal("1.00"))
            shipping = Decimal("0.00") if (d[5] + i) % 3 else Decimal("40.00")
            offers.append(
                ObservedOffer(
                    seller_id=seller,
                    seller_name=None,  # like SP-API: names are not provided
                    listing_price=listing,
                    shipping_price=shipping,
                    currency="INR",
                    fulfilment_channel="amazon" if (d[6] + i) % 2 else "merchant",
                    condition="New",
                    is_buy_box_winner=i == 0,
                    is_featured_merchant=i < 3,
                    seller_feedback_rating=Decimal(80 + (d[7] + i) % 20),
                    seller_feedback_count=(d[8] + i * 13) % 5000,
                )
            )
        truncated = total > observed
        if truncated:
            limitations.append(Limitation.OFFER_LIST_TRUNCATED)
        return OfferSnapshot(
            external_id=asin,
            status="partial" if truncated else "ok",
            source=MOCK_SOURCE,
            retrieved_at=now,
            total_offer_count=total,
            offers=offers,
            is_offer_list_truncated=truncated,
            buy_box_price=offers[0].landed_price,
            currency="INR",
            offer_count_breakdown=[
                {"condition": "new", "fulfillment_channel": "all", "count": total}
            ],
            limitations=limitations,
            raw_payload={"mock": True, "asin": asin},
        )

    async def fetch_offers(
        self, ctx: ConnectorContext, external_ids: list[str]
    ) -> dict[str, OfferSnapshot | ConnectorError]:
        return {asin: self.snapshot(asin) for asin in external_ids}
