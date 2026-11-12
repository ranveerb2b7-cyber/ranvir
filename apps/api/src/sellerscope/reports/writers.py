"""CSV and XLSX writers for report exports.

- Unknown values are written as EMPTY cells, never 0 (each report has a notes column that says
  why a value is missing).
- Text is protected against spreadsheet formula injection: in CSV a leading = + - @ tab or CR
  is prefixed with an apostrophe; in XLSX text cells are written explicitly as strings, so
  they are never evaluated as formulas.
- Times are UTC (column headers say so).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

Kind = Literal["text", "int", "money", "datetime", "bool"]
Cell = str | int | Decimal | datetime | bool | None

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"


def csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection (CSV injection) in exported text."""
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


@dataclass(frozen=True, slots=True)
class Column:
    header: str
    kind: Kind = "text"
    width: int = 16


@dataclass(slots=True)
class Report:
    title: str
    columns: Sequence[Column]
    rows: list[Sequence[Cell]]
    # Lines for the XLSX "About" sheet (filters, generated time, how to read blanks).
    about: list[str] = field(default_factory=list)
    contains_mock: bool = False


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def csv_text(value: Cell, kind: Kind) -> str:
    if value is None:
        return ""
    if kind == "bool" or isinstance(value, bool):
        return "Yes" if value else "No"
    if kind == "datetime" and isinstance(value, datetime):
        return _naive_utc(value).strftime("%Y-%m-%d %H:%M:%S")
    if kind == "money" and isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, int | Decimal):
        return str(value)
    return csv_safe(str(value))


def write_csv(report: Report) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([csv_safe(c.header) for c in report.columns])
    for row in report.rows:
        writer.writerow([csv_text(v, c.kind) for v, c in zip(row, report.columns, strict=True)])
    return ("﻿" + buffer.getvalue()).encode("utf-8")  # BOM: Excel opens it as UTF-8


def _xlsx_cell(sheet: WriteOnlyWorksheet, value: Cell, kind: Kind) -> Any:
    if value is None:
        return None
    if kind == "bool" or isinstance(value, bool):
        cell = WriteOnlyCell(sheet, value="Yes" if value else "No")
        cell.data_type = "s"
        return cell
    if kind == "datetime" and isinstance(value, datetime):
        cell = WriteOnlyCell(sheet, value=_naive_utc(value))
        cell.number_format = "yyyy-mm-dd hh:mm:ss"
        return cell
    if kind == "money" and isinstance(value, Decimal):
        cell = WriteOnlyCell(sheet, value=value)  # type: ignore[arg-type]  # exact decimal
        cell.number_format = "#,##0.00"
        return cell
    if kind == "int" and isinstance(value, int):
        return WriteOnlyCell(sheet, value=value)
    cell = WriteOnlyCell(sheet, value=str(value))
    cell.data_type = "s"  # never a formula, whatever the text starts with
    return cell


def write_xlsx(report: Report) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(report.title[:31])
    for i, column in enumerate(report.columns):
        sheet.column_dimensions[_letter(i)].width = column.width
    sheet.freeze_panes = "A2"
    bold = Font(bold=True)
    header = []
    for column in report.columns:
        cell = WriteOnlyCell(sheet, value=column.header)
        cell.data_type = "s"
        cell.font = bold
        header.append(cell)
    sheet.append(header)
    for row in report.rows:
        sheet.append(
            [_xlsx_cell(sheet, v, c.kind) for v, c in zip(row, report.columns, strict=True)]
        )
    about = workbook.create_sheet("About")
    about.column_dimensions["A"].width = 120
    for line in report.about:
        cell = WriteOnlyCell(about, value=line)
        cell.data_type = "s"
        about.append([cell])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _letter(index: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(index + 1)


def render(report: Report, fmt: str) -> tuple[bytes, str]:
    if fmt == "csv":
        return write_csv(report), CSV_CONTENT_TYPE
    return write_xlsx(report), XLSX_CONTENT_TYPE
