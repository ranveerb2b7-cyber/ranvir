"""Report files: blanks for unknown values, formula-injection safety, filter validation."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from sellerscope.reports.filters import FiltersError, parse_filters
from sellerscope.reports.writers import Column, Report, csv_safe, write_csv, write_xlsx

COLUMNS = (
    Column("Name"),
    Column("Count", "int"),
    Column("Price", "money"),
    Column("When (UTC)", "datetime"),
    Column("Complete", "bool"),
)
IST = timezone(timedelta(hours=5, minutes=30))
EVIL = ['=HYPERLINK("http://x","click")', "+cmd|' /C calc'!A0", "-2+3", "@SUM(A1)", "\tx"]


def report(*rows: list[object]) -> Report:
    return Report("Test", COLUMNS, [list(r) for r in rows], ["About line"], False)  # type: ignore[misc]


@pytest.mark.parametrize("value", EVIL)
def test_csv_safe_prefixes_formula_triggers(value: str) -> None:
    assert csv_safe(value) == "'" + value
    assert csv_safe("Plain = fine") == "Plain = fine"


def test_csv_blanks_unknowns_and_formats_values() -> None:
    when = datetime(2026, 11, 12, 15, 30, tzinfo=IST)
    data = write_csv(
        report(
            ["Steel", 0, Decimal("1299.5"), when, False],
            [None, None, None, None, None],
            *[[e, 1, None, None, True] for e in EVIL],
        )
    )
    assert data.startswith("﻿".encode())
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert rows[0] == ["Name", "Count", "Price", "When (UTC)", "Complete"]
    # A known zero stays 0; unknowns are empty, never 0.
    assert rows[1] == ["Steel", "0", "1299.50", "2026-11-12 10:00:00", "No"]
    assert rows[2] == ["", "", "", "", ""]
    for row, evil in zip(rows[3:], EVIL, strict=True):
        assert row[0] == "'" + evil


def test_xlsx_never_writes_formulas_and_keeps_types() -> None:
    when = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    data = write_xlsx(
        report(
            ["Steel", 3, Decimal("1299.50"), when, True],
            [None, None, None, None, None],
            *[[e, 1, None, None, None] for e in EVIL],
        )
    )
    book = load_workbook(io.BytesIO(data))
    sheet = book["Test"]
    assert [c.value for c in sheet[1]] == ["Name", "Count", "Price", "When (UTC)", "Complete"]
    name, count, price, at, complete = sheet[2]
    assert (name.value, count.value, complete.value) == ("Steel", 3, "Yes")
    assert price.value == pytest.approx(1299.5) and price.number_format == "#,##0.00"
    assert at.value == datetime(2026, 11, 12, 10, 0)
    assert all(c.value is None for c in sheet[3])
    for row, evil in zip(sheet.iter_rows(min_row=4), EVIL, strict=True):
        assert row[0].value == evil
        assert row[0].data_type == "s"  # text, not a formula
    assert book["About"]["A1"].value == "About line"


def test_filters_are_validated_per_type() -> None:
    assert parse_filters("product", {"brand": " Acme ", "monitoring": True}).model_dump() == {
        "brand": "Acme",
        "monitoring": True,
    }
    with pytest.raises(FiltersError) as exc:
        parse_filters("product", {"bogus": 1})
    assert exc.value.errors[0]["loc"] == ["body", "filters", "bogus"]
    with pytest.raises(FiltersError):
        parse_filters("errors", {"date_from": "2026-11-10", "date_to": "2026-11-01"})
    with pytest.raises(FiltersError):
        parse_filters("errors", {"date_from": "2025-01-01", "date_to": "2026-11-01"})
    with pytest.raises(FiltersError):
        parse_filters("marketplace", {"brand": "x"})
    with pytest.raises(FiltersError):
        parse_filters("alerts", {"status": "nope"})
    default = parse_filters("scan_summary", {})
    start, end = default.resolved(date(2026, 11, 12))  # type: ignore[attr-defined]
    assert (start, end) == (date(2026, 10, 14), date(2026, 11, 12))  # last 30 days inclusive
