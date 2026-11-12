"""Builders for upload test files (generated in code, so no binary fixtures in git)."""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Sequence

from openpyxl import Workbook


def xlsx(rows: Sequence[Sequence[object]], *, write_only: bool = False) -> bytes:
    workbook = Workbook(write_only=write_only)
    sheet = workbook.create_sheet() if write_only else workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def csv_bytes(
    rows: Sequence[Sequence[object]], *, encoding: str = "utf-8", delimiter: str = ","
) -> bytes:
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter).writerows(rows)
    return buffer.getvalue().encode(encoding)


def with_macro(data: bytes) -> bytes:
    """Adds a VBA project to an .xlsx archive (what a macro-enabled workbook contains)."""
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr("xl/vbaProject.bin", b"\x00fake-vba")
    return out.getvalue()


def zip_bomb() -> bytes:
    """A small .xlsx-shaped archive that expands to > 200 MB."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", b"\x00" * (210 * 1024 * 1024))
    return out.getvalue()


MIXED_ROWS: list[list[object]] = [
    ["ASIN (required)", "Product Title", "Brand Name", "Marketplace"],
    ["B0UPLOAD01", "Steel Bottle", "Hydra", "Amazon.in"],
    ["https://www.amazon.in/Mat/dp/b0upload02/ref=x", "Yoga Mat", "Zen", ""],
    [],  # blank row: skipped, row numbers keep counting
    ["B0UPLOAD01", "Steel Bottle again", "Hydra", ""],  # duplicate of row 2
    ["not-an-asin", "Broken", "", ""],
    ["", "No identifier", "Hydra", ""],
    ["https://amzn.in/d/xyz", "Short link", "", ""],
    ["B0UPLOAD03", '=HYPERLINK("http://evil","x")', "", "Flipkart"],
    ["B0UPLOAD04", "Lunch Box", "Zen", "eBay"],
    ["B0UPLOAD05", "Pan", "Chef", ""],
]
