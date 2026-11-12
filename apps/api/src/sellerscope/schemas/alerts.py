"""Alert rules and alerts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from sellerscope.alerts.rules import RuleScope
from sellerscope.schemas.common import ApiModel
from sellerscope.schemas.intel import ProductRef, SellerRef

RuleType = Literal[
    "new_seller",
    "seller_gone",
    "buy_box_changed",
    "offer_count_change",
    "seller_count_above",
    "price_below",
    "scan_failed",
]
Severity = Literal["info", "warning", "critical"]
Channel = Literal["in_app", "email"]
AlertStatusLit = Literal["open", "acknowledged", "resolved"]
DeliveryStatusLit = Literal["pending", "sending", "sent", "failed", "skipped"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Recipients = Annotated[list[uuid.UUID], Field(max_length=20)]


def _channels(value: list[Channel]) -> list[Channel]:
    # In-app is always on: every alert is listed in the app.
    return ["in_app", "email"] if "email" in value else ["in_app"]


def _in_app_only() -> list[Channel]:
    return ["in_app"]


class AlertRuleCreate(ApiModel):
    name: Name
    rule_type: RuleType
    params: dict[str, Any] = Field(default_factory=dict)
    scope: RuleScope = Field(default_factory=RuleScope)
    severity: Severity | None = None  # default depends on the rule type
    channels: list[Channel] = Field(default_factory=_in_app_only)
    recipient_user_ids: Recipients = Field(default_factory=list)
    is_enabled: bool = True

    _norm_channels = field_validator("channels")(_channels)

    @model_validator(mode="after")
    def _email_needs_recipients(self) -> AlertRuleCreate:
        if "email" in self.channels and not self.recipient_user_ids:
            raise ValueError("Choose at least one email recipient, or turn email off")
        return self


class AlertRuleUpdate(ApiModel):
    """Partial update. The rule type can't change (create a new rule instead)."""

    name: Name | None = None
    params: dict[str, Any] | None = None
    scope: RuleScope | None = None
    severity: Severity | None = None
    channels: list[Channel] | None = None
    recipient_user_ids: Recipients | None = None
    is_enabled: bool | None = None

    @field_validator("channels")
    @classmethod
    def _norm(cls, value: list[Channel] | None) -> list[Channel] | None:
        return None if value is None else _channels(value)


class AlertRuleOut(ApiModel):
    id: uuid.UUID
    name: str
    rule_type: RuleType
    severity: Severity
    params: dict[str, Any]
    scope: dict[str, Any]
    channels: list[Channel]
    recipient_user_ids: list[uuid.UUID]
    is_enabled: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    open_alerts: int = 0


class AlertRuleList(ApiModel):
    items: list[AlertRuleOut]
    limit: int


class DeliveryOut(ApiModel):
    channel: Channel
    recipient_user_id: uuid.UUID | None
    recipient_email: str | None
    status: DeliveryStatusLit
    attempt_count: int
    last_error: str | None
    next_attempt_at: datetime | None
    sent_at: datetime | None


class AlertOut(ApiModel):
    id: uuid.UUID
    alert_rule_id: uuid.UUID | None
    rule_name: str | None
    rule_type: RuleType | None
    severity: Severity
    status: AlertStatusLit
    title: str
    body: str | None
    details: dict[str, Any]
    product: ProductRef | None
    seller: SellerRef | None
    scan_result_id: uuid.UUID | None
    scan_history_id: uuid.UUID | None
    created_at: datetime
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    # True when the condition cleared on a later scan (no person resolved it).
    resolved_automatically: bool
    delivered_channels: list[Channel]
    deliveries: list[DeliveryOut]


class AlertPage(ApiModel):
    items: list[AlertOut]
    total: int
    page: int
    page_size: int


class AlertSummary(ApiModel):
    open: int
    acknowledged: int
    open_by_severity: dict[Severity, int]
    # Emails that gave up after all retries (needs attention: check SMTP settings).
    failed_deliveries: int


class AlertBulkAction(ApiModel):
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=200)]
    action: Literal["acknowledge", "resolve"]


class AlertBulkResult(ApiModel):
    updated: int
