"""Alert rule evaluation: pure functions from (rules, product, scan outcome) to decisions.

Principles (CLAUDE.md, docs/plan/02):
- Event rules (new seller, seller gone, Buy Box, offer count) only use change events from the
  diff engine, which already refuses to infer anything from failed or cut-off scans.
- "Seller not observed (inconclusive)" never raises an alert unless the rule opts in.
- Threshold rules (seller count, price) fire only on values that are KNOWN to cross the
  threshold, and resolve only when the data is complete enough to prove they no longer do.
  Unknown values (null counts, cut-off lists, failed scans) neither fire nor resolve.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sellerscope.alerts.rules import (
    BuyBoxChangedParams,
    NewSellerParams,
    OfferCountChangeParams,
    PriceBelowParams,
    RuleParams,
    RuleScope,
    ScanFailedParams,
    SellerCountAboveParams,
    SellerGoneParams,
)
from sellerscope.models.enums import AlertRuleType, Confidence, HistoryEventType
from sellerscope.scanning.diff import NO_DATA, USABLE, Change


@dataclass(frozen=True, slots=True)
class Rule:
    id: uuid.UUID
    name: str
    rule_type: AlertRuleType
    severity: str
    params: RuleParams
    scope: RuleScope
    channels: tuple[str, ...] = ("in_app",)
    recipients: tuple[uuid.UUID, ...] = ()

    def applies_to(self, product: ProductFacts) -> bool:
        if self.scope.product_ids and product.id not in self.scope.product_ids:
            return False
        if self.scope.brands:
            brands = {b.casefold() for b in self.scope.brands}
            if not product.brand or product.brand.strip().casefold() not in brands:
                return False
        return True


@dataclass(frozen=True, slots=True)
class ProductFacts:
    id: uuid.UUID
    external_id: str
    name: str | None = None
    brand: str | None = None

    @property
    def label(self) -> str:
        return f"{self.external_id} ({self.name})" if self.name else self.external_id


@dataclass(frozen=True, slots=True)
class SellerFacts:
    profile_id: uuid.UUID
    seller_id: str
    display_name: str | None = None
    tags: frozenset[str] = frozenset()

    @property
    def label(self) -> str:
        return f"{self.display_name} ({self.seller_id})" if self.display_name else self.seller_id

    def has_any_tag(self, tags: list[str]) -> bool:
        wanted = {t.casefold() for t in tags}
        return any(t.casefold() in wanted for t in self.tags)


@dataclass(frozen=True, slots=True)
class OfferFacts:
    seller: SellerFacts | None
    landed_price: Decimal | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class EventFacts:
    history_id: uuid.UUID
    change: Change
    seller: SellerFacts | None = None


@dataclass(slots=True)
class ScanOutcome:
    """A recorded scan. status is a scan_results status; 'error' = the scan failed."""

    result_id: uuid.UUID
    status: str
    error_code: str | None = None
    unique_seller_count: int | None = None
    is_offer_list_truncated: bool | None = None
    offers: list[OfferFacts] = field(default_factory=list)
    events: list[EventFacts] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Raise:
    rule: Rule
    dedupe_key: str
    title: str
    body: str
    scan_history_id: uuid.UUID | None = None
    seller_profile_id: uuid.UUID | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Resolve:
    rule: Rule
    dedupe_key: str


Decision = Raise | Resolve


def _money(value: Decimal, currency: str | None) -> str:
    return f"₹{value:,.2f}" if currency == "INR" else f"{value:,.2f} {currency or ''}".strip()


def _seller_label(seller: SellerFacts | None, fallback: str | None = None) -> str:
    if seller is not None:
        return seller.label
    return fallback or "an unidentified seller"


def _excluded(seller: SellerFacts | None, tags: list[str]) -> bool:
    return bool(tags) and seller is not None and seller.has_any_tag(tags)


def _event_rule(rule: Rule, product: ProductFacts, event: EventFacts) -> Raise | None:
    change, seller, p = event.change, event.seller, rule.params
    key = f"event:{event.history_id}"

    def make(*, title: str, body: str, details: dict[str, Any]) -> Raise:
        return Raise(
            rule,
            key,
            title,
            body,
            scan_history_id=event.history_id,
            seller_profile_id=change.seller_profile_id,
            details=details,
        )

    raw_id = (change.new_value or change.old_value or {}).get("seller_id")
    who = _seller_label(seller, raw_id)

    if rule.rule_type == AlertRuleType.NEW_SELLER:
        assert isinstance(p, NewSellerParams)
        if change.event_type != HistoryEventType.SELLER_NEWLY_OBSERVED:
            return None
        if p.min_confidence == "high" and change.confidence != Confidence.HIGH:
            return None
        if _excluded(seller, p.exclude_seller_tags):
            return None
        body = f"{who} was observed offering {product.label} for the first time."
        if change.confidence == Confidence.MEDIUM:
            body += (
                " The previous offer list was cut off, so this seller may already have been"
                " offering it."
            )
        return make(
            title=f"New seller on {product.external_id}: {who}",
            body=body,
            details={"seller_id": raw_id, "confidence": change.confidence},
        )

    if rule.rule_type == AlertRuleType.SELLER_GONE:
        assert isinstance(p, SellerGoneParams)
        if _excluded(seller, p.exclude_seller_tags):
            return None
        if change.event_type == HistoryEventType.SELLER_NO_LONGER_OBSERVED:
            return make(
                title=f"{who} no longer offering {product.external_id}",
                body=(
                    f"Amazon returned the complete offer list for {product.label} and {who} "
                    "was not in it."
                ),
                details={"seller_id": raw_id, "confidence": change.confidence},
            )
        if (
            change.event_type == HistoryEventType.SELLER_NOT_OBSERVED_INCONCLUSIVE
            and p.include_inconclusive
        ):
            return make(
                title=f"{who} not seen on {product.external_id} (inconclusive)",
                body=(
                    f"{who} was missing from the latest offers for {product.label}, but the "
                    "offer list was cut off, so they may still be selling."
                ),
                details={"seller_id": raw_id, "confidence": change.confidence},
            )
        return None

    if rule.rule_type == AlertRuleType.BUY_BOX_CHANGED:
        assert isinstance(p, BuyBoxChangedParams)
        if change.event_type != HistoryEventType.BUY_BOX_CHANGED:
            return None
        if _excluded(seller, p.exclude_seller_tags):
            return None
        previous = (change.old_value or {}).get("seller_id")
        return make(
            title=f"Buy Box on {product.external_id} moved to {who}",
            body=(
                f"The Buy Box for {product.label} was previously held by "
                f"{previous or 'another seller'}."
            ),
            details={"seller_id": raw_id, "previous_seller_id": previous},
        )

    if rule.rule_type == AlertRuleType.OFFER_COUNT_CHANGE:
        assert isinstance(p, OfferCountChangeParams)
        if change.event_type != HistoryEventType.OFFER_COUNT_CHANGED:
            return None
        old = int((change.old_value or {})["total_offer_count"])
        new = int((change.new_value or {})["total_offer_count"])
        delta = new - old
        if abs(delta) < p.min_change:
            return None
        if (p.direction == "increase" and delta < 0) or (p.direction == "decrease" and delta > 0):
            return None
        return make(
            title=f"Offers on {product.external_id} went from {old} to {new}",
            body=f"Amazon reported {new} offers for {product.label}, previously {old}.",
            details={"old": old, "new": new},
        )
    return None


def _condition_rule(rule: Rule, product: ProductFacts, outcome: ScanOutcome) -> Decision | None:
    key = f"product:{product.id}"
    p = rule.params
    usable = outcome.status in USABLE
    complete = outcome.is_offer_list_truncated is False

    if rule.rule_type == AlertRuleType.SCAN_FAILED:
        assert isinstance(p, ScanFailedParams)
        if outcome.status == "error":
            return Raise(
                rule,
                key,
                title=f"Scan failed for {product.external_id}",
                body=(
                    f"The latest scan of {product.label} could not get data "
                    f"(error: {outcome.error_code or 'unknown'}). The last good data is kept."
                ),
                details={"error_code": outcome.error_code},
            )
        if outcome.status in NO_DATA and p.include_unavailable:
            return Raise(
                rule,
                key,
                title=f"No offer data for {product.external_id}",
                body=(
                    f"Amazon reported {product.label} as "
                    f"{'not found' if outcome.status == 'not_found' else 'unavailable'}."
                ),
                details={"status": outcome.status},
            )
        return Resolve(rule, key)

    if not usable:
        return None  # nothing is known about counts or prices: neither fire nor resolve

    if rule.rule_type == AlertRuleType.SELLER_COUNT_ABOVE:
        assert isinstance(p, SellerCountAboveParams)
        count = outcome.unique_seller_count
        if count is None:
            return None
        if count > p.threshold:
            at_least = not complete
            shown = f"at least {count}" if at_least else str(count)
            return Raise(
                rule,
                key,
                title=f"{product.external_id} has {shown} sellers (limit {p.threshold})",
                body=(
                    f"{product.label} is offered by {shown} sellers, above your limit of "
                    f"{p.threshold}."
                    + (" The offer list was cut off, so there may be more." if at_least else "")
                ),
                details={"count": count, "threshold": p.threshold, "at_least": at_least},
            )
        return Resolve(rule, key) if complete else None

    if rule.rule_type == AlertRuleType.PRICE_BELOW:
        assert isinstance(p, PriceBelowParams)
        watched = [o for o in outcome.offers if not _excluded(o.seller, p.exclude_seller_tags)]
        comparable = [o for o in watched if o.landed_price is not None and o.currency == p.currency]
        below = sorted(
            (o for o in comparable if o.landed_price is not None and o.landed_price < p.threshold),
            key=lambda o: o.landed_price or Decimal(0),
        )
        if below:
            low = below[0]
            assert low.landed_price is not None
            price = _money(low.landed_price, low.currency)
            others = len(below) - 1
            return Raise(
                rule,
                key,
                title=(
                    f"{product.external_id} offered at {price}, "
                    f"below {_money(p.threshold, p.currency)}"
                ),
                body=(
                    f"{_seller_label(low.seller)} offers {product.label} at {price} including "
                    f"shipping"
                    + (f"; {others} other offer(s) are also below your price." if others else ".")
                ),
                seller_profile_id=low.seller.profile_id if low.seller else None,
                details={
                    "price": f"{low.landed_price:.2f}",
                    "currency": low.currency,
                    "threshold": f"{p.threshold:.2f}",
                    "offers_below": len(below),
                    "seller_id": low.seller.seller_id if low.seller else None,
                },
            )
        # Resolve only when every watched offer was seen, with a comparable price.
        if complete and len(comparable) == len(watched):
            return Resolve(rule, key)
        return None
    return None


EVENT_RULES = {
    AlertRuleType.NEW_SELLER,
    AlertRuleType.SELLER_GONE,
    AlertRuleType.BUY_BOX_CHANGED,
    AlertRuleType.OFFER_COUNT_CHANGE,
}


def evaluate(rules: list[Rule], product: ProductFacts, outcome: ScanOutcome) -> list[Decision]:
    decisions: list[Decision] = []
    for rule in rules:
        if not rule.applies_to(product):
            continue
        if rule.rule_type in EVENT_RULES:
            for event in outcome.events:
                raised = _event_rule(rule, product, event)
                if raised is not None:
                    decisions.append(raised)
        else:
            decision = _condition_rule(rule, product, outcome)
            if decision is not None:
                decisions.append(decision)
    return decisions
