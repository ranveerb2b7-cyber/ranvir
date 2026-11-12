"""Pure scanning logic: backoff, MOCK connector, snapshot summaries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sellerscope.connectors.base import Limitation, ObservedOffer, OfferSnapshot
from sellerscope.connectors.mock import MOCK_SOURCE, MockConnector
from sellerscope.connectors.registry import ConnectorRegistry
from sellerscope.core.config import AppEnv, Settings
from sellerscope.scanning.backoff import backoff_delay
from sellerscope.scanning.results import summarize

# ------------------------------------------------------------------------------ backoff


@pytest.mark.parametrize(("attempt", "ceiling"), [(1, 2.0), (2, 4.0), (3, 8.0), (10, 300.0)])
def test_backoff_grows_exponentially_up_to_cap(attempt: int, ceiling: float) -> None:
    assert backoff_delay(attempt, base_s=2, cap_s=300, rand=lambda: 1.0) == ceiling
    assert backoff_delay(attempt, base_s=2, cap_s=300, rand=lambda: 0.0) == 0.0


def test_backoff_never_shorter_than_retry_after() -> None:
    assert backoff_delay(1, base_s=2, cap_s=300, retry_after_s=45, rand=lambda: 0.1) == 45
    # Retry-After longer than the cap is still honoured.
    assert backoff_delay(1, base_s=2, cap_s=300, retry_after_s=900, rand=lambda: 0.5) == 900


# ------------------------------------------------------------------------------ MOCK connector


def _asin_for(scenario: int) -> str:
    for i in range(10_000):
        asin = f"B0MOCK{i:04d}"
        import hashlib

        if hashlib.sha256(asin.encode()).digest()[0] % 10 == scenario:
            return asin
    raise AssertionError


def test_mock_is_deterministic_and_clearly_labelled() -> None:
    connector = MockConnector()
    a, b = connector.snapshot("B0CHX1W1XY"), connector.snapshot("B0CHX1W1XY")
    assert (a.total_offer_count, [o.seller_id for o in a.offers]) == (
        b.total_offer_count,
        [o.seller_id for o in b.offers],
    )
    assert a.source == MOCK_SOURCE
    assert Limitation.MOCK_DATA in a.limitations
    assert all((o.seller_id or "").startswith("MOCK") for o in a.offers)
    assert all(o.seller_name is None for o in a.offers)  # like SP-API: no names


def test_mock_truncated_list_mimics_sp_api_cap() -> None:
    snap = MockConnector().snapshot(_asin_for(3))
    assert snap.status == "partial"
    assert snap.total_offer_count is not None and snap.total_offer_count > 20
    assert len(snap.offers) == 20
    assert snap.is_offer_list_truncated is True


def test_mock_not_found_and_unavailable_carry_no_numbers() -> None:
    for scenario, status in ((0, "not_found"), (1, "unavailable")):
        snap = MockConnector().snapshot(_asin_for(scenario))
        assert snap.status == status
        assert snap.total_offer_count is None
        assert snap.offers == []


def test_registry_never_offers_mock_in_production_like_envs() -> None:
    dev = ConnectorRegistry(Settings(app_env=AppEnv.DEVELOPMENT, enable_mock_connector=True))
    off = ConnectorRegistry(Settings(app_env=AppEnv.DEVELOPMENT, enable_mock_connector=False))
    assert dev.mock_enabled and not off.mock_enabled


# ------------------------------------------------------------------------------ summarize


def _snap(offers: list[ObservedOffer], total: int | None, **kw: object) -> OfferSnapshot:
    return OfferSnapshot(
        "B0X", "ok", "test", datetime.now(UTC), total, offers, kw.pop("truncated", None), **kw
    )  # type: ignore[arg-type]


def _offer(seller: str | None, price: str | None, shipping: str | None = None) -> ObservedOffer:
    return ObservedOffer(
        seller_id=seller,
        seller_name=None,
        listing_price=Decimal(price) if price else None,
        shipping_price=Decimal(shipping) if shipping else None,
        currency="INR",
    )


def test_summary_metrics_are_independent() -> None:
    s = summarize(_snap([_offer("A", "100", "40"), _offer("B", "120"), _offer("A", "90")], 37))
    assert s["total_offer_count"] == 37  # reported
    assert s["observed_offer_count"] == 3  # received
    assert s["unique_seller_count"] == 2  # distinct ids
    assert (s["lowest_observed_price"], s["highest_observed_price"]) == (Decimal(90), Decimal(140))
    assert s["is_offer_list_truncated"] is True
    assert Limitation.OFFER_LIST_TRUNCATED in s["limitations"]  # type: ignore[operator]


def test_unknown_seller_ids_make_unique_count_unknown_not_zero() -> None:
    s = summarize(_snap([_offer("A", "100"), _offer(None, "110")], 2))
    assert s["unique_seller_count"] is None
    assert Limitation.SELLER_ID_NOT_PROVIDED in s["limitations"]  # type: ignore[operator]


def test_zero_sellers_only_when_source_reports_zero_offers() -> None:
    assert summarize(_snap([], 0))["unique_seller_count"] == 0
    s = summarize(_snap([], None))
    assert s["unique_seller_count"] is None
    assert s["lowest_observed_price"] is None
    assert s["currency"] is None
    assert Limitation.TOTAL_OFFER_COUNT_NOT_PROVIDED in s["limitations"]  # type: ignore[operator]
