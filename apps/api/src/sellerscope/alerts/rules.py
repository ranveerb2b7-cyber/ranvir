"""Alert rule types and their parameters (validated per type)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from sellerscope.models.enums import AlertRuleType, AlertSeverity

Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Brand = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewSellerParams(_Params):
    # "medium" = the previous offer list was cut off, so the seller may already have been there.
    min_confidence: Literal["high", "medium"] = "medium"
    exclude_seller_tags: Annotated[list[Tag], Field(max_length=10)] = []


class SellerGoneParams(_Params):
    # A seller missing from a CUT-OFF offer list may still be selling. Off unless opted in.
    include_inconclusive: bool = False
    exclude_seller_tags: Annotated[list[Tag], Field(max_length=10)] = []


class BuyBoxChangedParams(_Params):
    # No alert when the new Buy Box winner carries one of these tags (e.g. your own seller).
    exclude_seller_tags: Annotated[list[Tag], Field(max_length=10)] = []


class OfferCountChangeParams(_Params):
    min_change: int = Field(default=1, ge=1, le=100_000)
    direction: Literal["any", "increase", "decrease"] = "any"


class SellerCountAboveParams(_Params):
    threshold: int = Field(ge=0, le=100_000)


class PriceBelowParams(_Params):
    threshold: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: Literal["INR"] = "INR"
    exclude_seller_tags: Annotated[list[Tag], Field(max_length=10)] = []


class ScanFailedParams(_Params):
    # Also alert when a scan succeeds but the product has no offer data (unavailable/not found).
    include_unavailable: bool = False


RuleParams = (
    NewSellerParams
    | SellerGoneParams
    | BuyBoxChangedParams
    | OfferCountChangeParams
    | SellerCountAboveParams
    | PriceBelowParams
    | ScanFailedParams
)

PARAMS: dict[AlertRuleType, type[RuleParams]] = {
    AlertRuleType.NEW_SELLER: NewSellerParams,
    AlertRuleType.SELLER_GONE: SellerGoneParams,
    AlertRuleType.BUY_BOX_CHANGED: BuyBoxChangedParams,
    AlertRuleType.OFFER_COUNT_CHANGE: OfferCountChangeParams,
    AlertRuleType.SELLER_COUNT_ABOVE: SellerCountAboveParams,
    AlertRuleType.PRICE_BELOW: PriceBelowParams,
    AlertRuleType.SCAN_FAILED: ScanFailedParams,
}

DEFAULT_SEVERITY: dict[AlertRuleType, AlertSeverity] = {
    AlertRuleType.NEW_SELLER: AlertSeverity.WARNING,
    AlertRuleType.SELLER_GONE: AlertSeverity.INFO,
    AlertRuleType.BUY_BOX_CHANGED: AlertSeverity.WARNING,
    AlertRuleType.OFFER_COUNT_CHANGE: AlertSeverity.INFO,
    AlertRuleType.SELLER_COUNT_ABOVE: AlertSeverity.WARNING,
    AlertRuleType.PRICE_BELOW: AlertSeverity.CRITICAL,
    AlertRuleType.SCAN_FAILED: AlertSeverity.WARNING,
}


class RuleScope(_Params):
    """Which products a rule watches. Empty = all monitored products."""

    product_ids: Annotated[list[uuid.UUID], Field(max_length=1000)] = []
    brands: Annotated[list[Brand], Field(max_length=50)] = []


class ParamsError(ValueError):
    def __init__(self, errors: list[dict[str, object]]) -> None:
        super().__init__("invalid rule parameters")
        self.errors = errors


def parse_params(rule_type: AlertRuleType | str, raw: dict[str, object] | None) -> RuleParams:
    try:
        return PARAMS[AlertRuleType(rule_type)].model_validate(raw or {})
    except ValidationError as exc:
        raise ParamsError(
            [
                {"field": ".".join(str(p) for p in e["loc"]) or "params", "message": e["msg"]}
                for e in exc.errors()
            ]
        ) from exc
