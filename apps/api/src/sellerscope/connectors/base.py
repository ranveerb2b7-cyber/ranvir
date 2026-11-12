"""Marketplace connector contract.

A connector turns product identifiers into OfferSnapshots using an AUTHORIZED data source.
It declares what it can provide (capabilities); the engine never assumes a field exists.
Unknown values stay None. Connectors never invent data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from sellerscope.models import MarketplaceConnection


class Limitation(StrEnum):
    """Machine codes stored on scan results to explain incomplete data."""

    MOCK_DATA = "MOCK_DATA"
    SELLER_NAME_NOT_PROVIDED = "SELLER_NAME_NOT_PROVIDED"
    SELLER_ID_NOT_PROVIDED = "SELLER_ID_NOT_PROVIDED"
    OFFER_LIST_TRUNCATED = "OFFER_LIST_TRUNCATED"
    TOTAL_OFFER_COUNT_NOT_PROVIDED = "TOTAL_OFFER_COUNT_NOT_PROVIDED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class ConnectorCapabilities:
    total_offer_count: bool
    offer_list: bool
    offer_list_max: int | None  # e.g. 20 for Amazon getItemOffers: lists can be truncated
    seller_id: bool
    seller_name: bool
    price: bool
    fulfilment: bool
    batch_size: int  # identifiers per request; 1 = no batching
    requests_per_second: float
    burst: int


@dataclass(frozen=True, slots=True)
class ObservedOffer:
    seller_id: str | None
    seller_name: str | None
    listing_price: Decimal | None
    shipping_price: Decimal | None
    currency: str | None
    fulfilment_channel: Literal["amazon", "merchant", "unknown"] = "unknown"
    condition: str | None = None
    sub_condition: str | None = None
    is_buy_box_winner: bool | None = None
    is_featured_merchant: bool | None = None
    is_prime: bool | None = None
    seller_feedback_rating: Decimal | None = None
    seller_feedback_count: int | None = None
    ships_from_country: str | None = None

    @property
    def landed_price(self) -> Decimal | None:
        if self.listing_price is None:
            return None
        if self.shipping_price is None:
            return self.listing_price
        return self.listing_price + self.shipping_price


SnapshotStatus = Literal["ok", "partial", "not_found", "unavailable"]


@dataclass(slots=True)
class OfferSnapshot:
    external_id: str
    status: SnapshotStatus
    source: str  # e.g. "amazon_sp_api.getItemOffers.v0" or "MOCK"
    retrieved_at: datetime
    total_offer_count: int | None
    offers: list[ObservedOffer]
    is_offer_list_truncated: bool | None
    buy_box_price: Decimal | None = None
    currency: str | None = None
    offer_count_breakdown: list[dict[str, Any]] | None = None
    limitations: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] | None = None


# ------------------------------------------------------------------------------ errors


class ConnectorError(Exception):
    """Base class. `code` is stored on the scan item; `message` is shown to users."""

    retryable = False

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RateLimitedError(ConnectorError):
    retryable = True

    def __init__(
        self,
        message: str = "The marketplace asked us to slow down.",
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__("rate_limited", message)
        self.retry_after_s = retry_after_s


class TransientError(ConnectorError):
    """Timeouts, 5xx, network errors: worth retrying."""

    retryable = True


class PermanentError(ConnectorError):
    """Authorization revoked, role missing, invalid request: retrying won't help."""


class ConnectorUnavailableError(Exception):
    def __init__(self, marketplace: str, reason: str) -> None:
        super().__init__(reason)
        self.marketplace = marketplace
        self.reason = reason


# ------------------------------------------------------------------------------ protocol


@dataclass(frozen=True, slots=True)
class ConnectorContext:
    organization_id: uuid.UUID
    marketplace_code: str
    external_marketplace_id: str | None
    connection: MarketplaceConnection | None


class MarketplaceConnector(Protocol):
    code: str  # connector identity, e.g. "mock", "amazon_sp_api"
    capabilities: ConnectorCapabilities

    def rate_limit_key(self, ctx: ConnectorContext) -> str:
        """Requests sharing a key share one rate limit (e.g. per seller authorization)."""
        ...

    async def fetch_offers(
        self, ctx: ConnectorContext, external_ids: list[str]
    ) -> dict[str, OfferSnapshot | ConnectorError]:
        """One request's worth of identifiers (≤ batch_size).

        Returns a snapshot or an error per identifier. A connector may instead raise a
        ConnectorError that applies to the whole request (e.g. rate limited).
        """
        ...
