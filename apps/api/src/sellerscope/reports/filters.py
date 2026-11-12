"""Per-report-type filters (validated on request, stored on the export)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    model_validator,
)

from sellerscope.models.enums import ReportType

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30


class _Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductFilters(_Filters):
    # Exact brand; "__none__" = products without a brand.
    brand: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
        | None
    ) = None
    monitoring: bool | None = None


class NoFilters(_Filters):
    pass


class SellerFilters(_Filters):
    tag: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] | None
    ) = None
    currently_offering: bool | None = None


class DateRange(_Filters):
    """Inclusive UTC dates. Defaults to the last 30 days."""

    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _range(self) -> DateRange:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        if (
            self.date_from
            and self.date_to
            and (self.date_to - self.date_from).days >= MAX_RANGE_DAYS
        ):
            raise ValueError(f"The date range can be at most {MAX_RANGE_DAYS} days")
        return self

    def resolved(self, today: date) -> tuple[date, date]:
        end = self.date_to or today
        start = self.date_from or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        return start, end


class AlertFilters(DateRange):
    status: Literal["open", "acknowledged", "resolved"] | None = None


FILTERS: dict[ReportType, type[_Filters]] = {
    ReportType.PRODUCT: ProductFilters,
    ReportType.MARKETPLACE: NoFilters,
    ReportType.BRAND: NoFilters,
    ReportType.SELLER: SellerFilters,
    ReportType.SCAN_SUMMARY: DateRange,
    ReportType.ERRORS: DateRange,
    ReportType.ALERTS: AlertFilters,
}


class FiltersError(ValueError):
    def __init__(self, errors: list[dict[str, object]]) -> None:
        super().__init__("invalid report filters")
        self.errors = errors


def parse_filters(report_type: str, raw: dict[str, object] | None) -> _Filters:
    try:
        return FILTERS[ReportType(report_type)].model_validate(raw or {})
    except ValidationError as exc:
        raise FiltersError(
            [
                {
                    "loc": ["body", "filters", *[str(p) for p in e["loc"]]],
                    "msg": e["msg"],
                    "type": e["type"],
                }
                for e in exc.errors()
            ]
        ) from exc
