"""Browser extension pairing, lookup and device management."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from sellerscope.schemas.common import ApiModel

Pkce = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43,128}$")]
DeviceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class PairStart(ApiModel):
    code_challenge: Pkce
    device_name: DeviceName | None = None


class PairStarted(ApiModel):
    pairing_code: str
    expires_at: datetime
    organization_name: str


class PairComplete(ApiModel):
    pairing_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]
    code_verifier: Pkce


class OrgRef(ApiModel):
    id: uuid.UUID
    name: str


class PairCompleted(ApiModel):
    token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  # OAuth token type name
    expires_at: datetime
    scopes: list[str]
    organization: OrgRef
    user_email: str


class ExtensionMe(ApiModel):
    organization: OrgRef
    user_email: str
    role: str
    scopes: list[str]
    can_check: bool


class LookupProduct(ApiModel):
    id: uuid.UUID
    external_id: str
    product_name: str | None
    brand_name: str | None
    monitoring_enabled: bool


class LookupSnapshot(ApiModel):
    """Figures are null when unknown (never 0); `limitations` says why."""

    status: str
    data_source: str
    is_mock: bool
    retrieved_at: datetime
    total_offer_count: int | None
    observed_offer_count: int | None
    unique_seller_count: int | None
    is_offer_list_truncated: bool | None
    lowest_observed_price: Decimal | None
    highest_observed_price: Decimal | None
    buy_box_price: Decimal | None
    currency: str | None
    limitations: list[str]


class LookupAttempt(ApiModel):
    status: str
    error_code: str | None
    at: datetime


class ActiveScan(ApiModel):
    job_id: uuid.UUID
    status: str


class LookupResult(ApiModel):
    marketplace: str
    identifier: str
    tracked: bool
    product: LookupProduct | None
    latest: LookupSnapshot | None
    last_attempt: LookupAttempt | None
    active_scan: ActiveScan | None
    can_check: bool
    dashboard_url: str


class CheckRequest(ApiModel):
    marketplace: Literal["amazon_in"] = "amazon_in"
    id: Annotated[str, Field(min_length=1, max_length=2000)]


class CheckStarted(ApiModel):
    job_id: uuid.UUID
    status: str


class ExtensionTokenOut(ApiModel):
    id: uuid.UUID
    name: str | None
    user_id: uuid.UUID
    user_email: str | None
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None
    is_current_user: bool
