"""Alert rule evaluation: unknown or inconclusive data must never fire (or clear) an alert."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from sellerscope.alerts.engine import (
    EventFacts,
    OfferFacts,
    ProductFacts,
    Raise,
    Resolve,
    Rule,
    ScanOutcome,
    SellerFacts,
    evaluate,
)
from sellerscope.alerts.rules import ParamsError, RuleScope, parse_params
from sellerscope.models.enums import AlertRuleType, Confidence, HistoryEventType
from sellerscope.scanning.diff import Change

PRODUCT = ProductFacts(uuid.uuid4(), "B0TESTASIN", "Steel bottle", "Acme")
OWN = SellerFacts(uuid.uuid4(), "AOWNSELLER", "Acme Store", frozenset({"Authorized"}))
OTHER = SellerFacts(uuid.uuid4(), "AOTHER1", None, frozenset())


def rule(rule_type: AlertRuleType, params: dict[str, Any] | None = None, **scope: Any) -> Rule:
    return Rule(
        id=uuid.uuid4(),
        name=str(rule_type),
        rule_type=rule_type,
        severity="warning",
        params=parse_params(rule_type, params or {}),
        scope=RuleScope(**scope),
    )


def event(kind: HistoryEventType, seller: SellerFacts | None = None, **kw: Any) -> EventFacts:
    return EventFacts(
        uuid.uuid4(),
        Change(kind, seller.profile_id if seller else None, **kw),
        seller,
    )


def scan(status: str = "ok", **kw: Any) -> ScanOutcome:
    return ScanOutcome(result_id=uuid.uuid4(), status=status, **kw)


def offer(
    seller: SellerFacts | None, price: str | None, currency: str | None = "INR"
) -> OfferFacts:
    return OfferFacts(seller, Decimal(price) if price else None, currency)


# ----------------------------------------------------------------------------- event rules


def test_new_seller_raises_once_per_event_with_confidence_note() -> None:
    r = rule(AlertRuleType.NEW_SELLER)
    high = event(
        HistoryEventType.SELLER_NEWLY_OBSERVED,
        OTHER,
        new_value={"seller_id": "AOTHER1"},
        confidence=Confidence.HIGH,
    )
    medium = event(
        HistoryEventType.SELLER_NEWLY_OBSERVED,
        OWN,
        new_value={"seller_id": "AOWNSELLER"},
        confidence=Confidence.MEDIUM,
    )
    out = evaluate([r], PRODUCT, scan(events=[high, medium]))
    assert [type(d) for d in out] == [Raise, Raise]
    first, second = out
    assert isinstance(first, Raise) and isinstance(second, Raise)
    assert first.dedupe_key == f"event:{high.history_id}"
    assert first.scan_history_id == high.history_id
    assert "AOTHER1" in first.title and "cut off" not in first.body
    assert "Acme Store (AOWNSELLER)" in second.title and "cut off" in second.body


def test_new_seller_filters() -> None:
    medium = event(
        HistoryEventType.SELLER_NEWLY_OBSERVED,
        OTHER,
        new_value={"seller_id": "AOTHER1"},
        confidence=Confidence.MEDIUM,
    )
    own = event(
        HistoryEventType.SELLER_NEWLY_OBSERVED,
        OWN,
        new_value={"seller_id": "AOWNSELLER"},
        confidence=Confidence.HIGH,
    )
    only_high = rule(AlertRuleType.NEW_SELLER, {"min_confidence": "high"})
    assert evaluate([only_high], PRODUCT, scan(events=[medium])) == []
    # Tag match is case-insensitive.
    skip_own = rule(AlertRuleType.NEW_SELLER, {"exclude_seller_tags": ["authorized"]})
    assert evaluate([skip_own], PRODUCT, scan(events=[own])) == []
    # Other event types are ignored.
    gone = event(HistoryEventType.SELLER_NO_LONGER_OBSERVED, OTHER, old_value={"seller_id": "X"})
    assert evaluate([rule(AlertRuleType.NEW_SELLER)], PRODUCT, scan(events=[gone])) == []


def test_seller_gone_ignores_inconclusive_unless_opted_in() -> None:
    gone = event(
        HistoryEventType.SELLER_NO_LONGER_OBSERVED,
        OTHER,
        old_value={"seller_id": "AOTHER1"},
        confidence=Confidence.HIGH,
    )
    maybe = event(
        HistoryEventType.SELLER_NOT_OBSERVED_INCONCLUSIVE,
        OTHER,
        old_value={"seller_id": "AOTHER1"},
        confidence=Confidence.LOW,
    )
    default = evaluate([rule(AlertRuleType.SELLER_GONE)], PRODUCT, scan(events=[gone, maybe]))
    assert len(default) == 1 and isinstance(default[0], Raise)
    assert "complete offer list" in default[0].body

    opted = rule(AlertRuleType.SELLER_GONE, {"include_inconclusive": True})
    out = evaluate([opted], PRODUCT, scan(events=[maybe]))
    assert len(out) == 1 and isinstance(out[0], Raise)
    assert "inconclusive" in out[0].title and "may still be selling" in out[0].body


def test_buy_box_change_can_skip_own_seller() -> None:
    to_own = event(
        HistoryEventType.BUY_BOX_CHANGED,
        OWN,
        old_value={"seller_id": "AOTHER1"},
        new_value={"seller_id": "AOWNSELLER"},
    )
    to_other = event(
        HistoryEventType.BUY_BOX_CHANGED,
        OTHER,
        old_value={"seller_id": "AOWNSELLER"},
        new_value={"seller_id": "AOTHER1"},
    )
    r = rule(AlertRuleType.BUY_BOX_CHANGED, {"exclude_seller_tags": ["Authorized"]})
    out = evaluate([r], PRODUCT, scan(events=[to_own, to_other]))
    assert len(out) == 1 and isinstance(out[0], Raise)
    assert "moved to AOTHER1" in out[0].title and "AOWNSELLER" in out[0].body


@pytest.mark.parametrize(
    ("params", "old", "new", "fires"),
    [
        ({}, 3, 4, True),
        ({"min_change": 2}, 3, 4, False),
        ({"min_change": 2}, 5, 3, True),
        ({"direction": "increase"}, 5, 3, False),
        ({"direction": "decrease"}, 5, 3, True),
    ],
)
def test_offer_count_change(params: dict[str, Any], old: int, new: int, fires: bool) -> None:
    e = event(
        HistoryEventType.OFFER_COUNT_CHANGED,
        old_value={"total_offer_count": old},
        new_value={"total_offer_count": new},
    )
    out = evaluate([rule(AlertRuleType.OFFER_COUNT_CHANGE, params)], PRODUCT, scan(events=[e]))
    assert bool(out) is fires


# ------------------------------------------------------------------------- threshold rules


def test_seller_count_above_uses_known_counts_only() -> None:
    r = rule(AlertRuleType.SELLER_COUNT_ABOVE, {"threshold": 3})
    key = f"product:{PRODUCT.id}"

    fired = evaluate([r], PRODUCT, scan(unique_seller_count=5, is_offer_list_truncated=False))
    assert isinstance(fired[0], Raise) and fired[0].dedupe_key == key
    assert fired[0].details["at_least"] is False

    cut = evaluate([r], PRODUCT, scan(unique_seller_count=5, is_offer_list_truncated=True))
    assert isinstance(cut[0], Raise) and "at least 5" in cut[0].title

    assert evaluate([r], PRODUCT, scan(unique_seller_count=2, is_offer_list_truncated=False)) == [
        Resolve(r, key)
    ]
    # Below threshold on a cut-off list: there may be more sellers. Neither fire nor resolve.
    assert evaluate([r], PRODUCT, scan(unique_seller_count=2, is_offer_list_truncated=True)) == []
    assert evaluate([r], PRODUCT, scan(unique_seller_count=2, is_offer_list_truncated=None)) == []
    # Unknown seller count (some offers had no seller id) is not zero.
    assert (
        evaluate([r], PRODUCT, scan(unique_seller_count=None, is_offer_list_truncated=False)) == []
    )
    assert evaluate([r], PRODUCT, scan("unavailable")) == []
    assert evaluate([r], PRODUCT, scan("error", error_code="timeout")) == []


def test_price_below() -> None:
    r = rule(AlertRuleType.PRICE_BELOW, {"threshold": "500", "exclude_seller_tags": ["authorized"]})
    key = f"product:{PRODUCT.id}"
    cheap_own = offer(OWN, "300.00")
    cheap = offer(OTHER, "450.00")
    cheaper_unknown = offer(None, "420.00")
    fine = offer(OTHER, "520.00")

    out = evaluate(
        [r],
        PRODUCT,
        scan(offers=[cheap_own, cheap, cheaper_unknown], is_offer_list_truncated=False),
    )
    assert len(out) == 1 and isinstance(out[0], Raise)
    # Own (excluded) offer is ignored; the cheapest remaining one is reported.
    assert "₹420.00" in out[0].title and out[0].details["offers_below"] == 2
    assert "an unidentified seller" in out[0].body

    assert evaluate(
        [r], PRODUCT, scan(offers=[cheap_own, fine], is_offer_list_truncated=False)
    ) == [Resolve(r, key)]
    # A cut-off list may hide a cheaper offer: don't resolve.
    assert evaluate([r], PRODUCT, scan(offers=[fine], is_offer_list_truncated=True)) == []
    # Unknown price, or another currency: can't prove nothing is below.
    assert (
        evaluate(
            [r], PRODUCT, scan(offers=[fine, offer(OTHER, None)], is_offer_list_truncated=False)
        )
        == []
    )
    usd = offer(OTHER, "1.00", "USD")
    assert evaluate([r], PRODUCT, scan(offers=[fine, usd], is_offer_list_truncated=False)) == []
    assert evaluate([r], PRODUCT, scan("not_found")) == []


def test_scan_failed() -> None:
    r = rule(AlertRuleType.SCAN_FAILED)
    key = f"product:{PRODUCT.id}"
    out = evaluate([r], PRODUCT, scan("error", error_code="rate_limited"))
    assert isinstance(out[0], Raise) and "rate_limited" in out[0].body
    assert evaluate([r], PRODUCT, scan("unavailable")) == [Resolve(r, key)]
    assert evaluate([r], PRODUCT, scan("ok")) == [Resolve(r, key)]

    strict = rule(AlertRuleType.SCAN_FAILED, {"include_unavailable": True})
    out = evaluate([strict], PRODUCT, scan("not_found"))
    assert isinstance(out[0], Raise) and "not found" in out[0].body


def test_scope_limits_products_and_brands() -> None:
    e = event(
        HistoryEventType.SELLER_NEWLY_OBSERVED,
        OTHER,
        new_value={"seller_id": "AOTHER1"},
        confidence=Confidence.HIGH,
    )
    other_product = rule(AlertRuleType.NEW_SELLER, product_ids=[uuid.uuid4()])
    this_product = rule(AlertRuleType.NEW_SELLER, product_ids=[PRODUCT.id])
    brand = rule(AlertRuleType.NEW_SELLER, brands=["ACME"])
    other_brand = rule(AlertRuleType.NEW_SELLER, brands=["Globex"])
    out = evaluate([other_product, this_product, brand, other_brand], PRODUCT, scan(events=[e]))
    assert [d.rule for d in out] == [this_product, brand]
    unbranded = ProductFacts(uuid.uuid4(), "B0NOBRAND1")
    assert evaluate([brand], unbranded, scan(events=[e])) == []


def test_params_are_validated_per_type() -> None:
    with pytest.raises(ParamsError) as exc:
        parse_params(AlertRuleType.PRICE_BELOW, {})
    assert exc.value.errors[0]["field"] == "threshold"
    with pytest.raises(ParamsError):
        parse_params(AlertRuleType.PRICE_BELOW, {"threshold": "-1"})
    with pytest.raises(ParamsError):
        parse_params(AlertRuleType.NEW_SELLER, {"unknown": 1})
    with pytest.raises(ParamsError):
        parse_params(AlertRuleType.SELLER_COUNT_ABOVE, {"threshold": -1})
    assert parse_params(AlertRuleType.SCAN_FAILED, None).model_dump() == {
        "include_unavailable": False
    }
