"""Read spreadsheet rows and classify them. Pure functions: no database access.

Row outcomes:
- valid               first occurrence of a well-formed ASIN not yet in the organization
- invalid             missing/malformed identifier, unsupported marketplace, ...
- duplicate_in_file   same ASIN as an earlier row of this file
- duplicate_existing  ASIN already among the organization's products
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime

from openpyxl import load_workbook

from sellerscope.connectors.identifiers import MarketplaceCode, parse_asin
from sellerscope.models.enums import BatchRowStatus
from sellerscope.uploads.files import FileKind, FileRejectedError, RejectCode

MAX_CELL_CHARS = 2_000
MAX_NAME_CHARS = 300
MAX_BRAND_CHARS = 120

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "identifier": (
        "asin",
        "amazon asin",
        "asin or url",
        "asin url",
        "asin link",
        "amazon url",
        "amazon link",
        "product url",
        "product link",
        "url",
        "link",
        "identifier",
    ),
    "product_name": ("product name", "name", "title", "product title", "product", "item name"),
    "brand_name": ("brand", "brand name", "manufacturer"),
    "marketplace": ("marketplace", "channel", "platform"),
    "fsn": ("fsn", "flipkart fsn", "flipkart id"),
}
_ALIAS_TO_FIELD = {alias: fld for fld, aliases in FIELD_ALIASES.items() for alias in aliases}

AMAZON_MARKETPLACE_VALUES = {"", "amazon", "amazon in", "amazon.in", "amazon_in", "amazon india"}
FLIPKART_VALUES = {"flipkart", "flipkart.com"}


class RowError:
    MISSING_IDENTIFIER = "missing_identifier"
    FLIPKART_NOT_SUPPORTED = "flipkart_not_supported"
    UNKNOWN_MARKETPLACE = "unknown_marketplace"
    DUPLICATE_IN_FILE = "duplicate_in_file"
    ALREADY_EXISTS = "already_exists"


class RowWarning:
    NAME_TRUNCATED = "name_truncated"
    BRAND_TRUNCATED = "brand_truncated"


# ------------------------------------------------------------------------------ reading


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # numeric ISBN-style ASINs typed into Excel
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value).strip()[:MAX_CELL_CHARS]


def _decode_csv(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise FileRejectedError(RejectCode.ENCODING)


def read_rows(kind: FileKind, data: bytes) -> Iterator[tuple[int, list[str]]]:
    """Yields (1-based sheet row number, cell texts). Blank rows are skipped."""
    if kind == FileKind.CSV:
        text, _ = _decode_csv(data)
        sample = text[:4096]
        try:
            dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, ",;\t")
        except csv.Error:
            dialect = csv.excel
        for number, cells in enumerate(csv.reader(io.StringIO(text), dialect), start=1):
            values = [_cell_text(c) for c in cells]
            if any(values):
                yield number, values
        return
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many exception types for damaged files
        raise FileRejectedError(RejectCode.CORRUPT) from exc
    try:
        sheet = workbook.worksheets[0]  # the first sheet holds the product list
        for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            values = [_cell_text(c) for c in row]
            if any(values):
                yield number, values
    finally:
        workbook.close()


def _normalize_header(value: str) -> str:
    value = re.sub(r"\(.*?\)", " ", value.lower())  # drop "(optional)", "(required)"
    value = re.sub(r"[^a-z0-9.]+", " ", value)
    return " ".join(value.split())


# ------------------------------------------------------------------------------ parsing


@dataclass(slots=True)
class SourceRow:
    row_number: int
    raw: dict[str, str]
    identifier: str = ""
    product_name: str = ""
    brand_name: str = ""
    marketplace: str = ""
    fsn: str = ""


@dataclass(slots=True)
class ParsedTable:
    mapping: dict[str, str]  # field -> header text as written in the file
    rows: list[SourceRow]


def parse_table(rows: Iterable[tuple[int, list[str]]], *, max_rows: int) -> ParsedTable:
    iterator = iter(rows)
    first = next(iterator, None)
    if first is None:
        raise FileRejectedError(RejectCode.NO_HEADER)
    _, header = first
    columns: dict[str, int] = {}
    mapping: dict[str, str] = {}
    for index, title in enumerate(header):
        fld = _ALIAS_TO_FIELD.get(_normalize_header(title))
        if fld and fld not in columns:
            columns[fld] = index
            mapping[fld] = title
    if "identifier" not in columns:
        if "fsn" in columns:
            raise FileRejectedError(RejectCode.FLIPKART_ONLY)
        if not any(header):
            raise FileRejectedError(RejectCode.NO_HEADER)
        raise FileRejectedError(RejectCode.NO_IDENTIFIER_COLUMN)

    headers = [h or f"Column {i + 1}" for i, h in enumerate(header)]
    parsed: list[SourceRow] = []
    for number, values in iterator:
        if len(parsed) >= max_rows:
            raise FileRejectedError(RejectCode.TOO_MANY_ROWS, limit_rows=f"{max_rows:,}")
        row = SourceRow(
            row_number=number,
            raw={headers[i]: v for i, v in enumerate(values[: len(headers)]) if v},
        )
        for fld, index in columns.items():
            setattr(row, fld, values[index] if index < len(values) else "")
        parsed.append(row)
    return ParsedTable(mapping=mapping, rows=parsed)


# ------------------------------------------------------------------------------ classifying


@dataclass(slots=True)
class RowOutcome:
    source: SourceRow
    status: BatchRowStatus
    marketplace_code: str | None
    normalized: str | None
    product_name: str | None
    brand_name: str | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _clip(value: str, limit: int, warning: str, warnings: list[str]) -> str | None:
    value = value.strip()
    if len(value) > limit:
        warnings.append(warning)
        value = value[:limit].rstrip()
    return value or None


def classify(rows: list[SourceRow], existing: set[str]) -> list[RowOutcome]:
    """`existing` = normalized ASINs already among the organization's active products."""
    first_seen: dict[str, int] = {}
    outcomes: list[RowOutcome] = []
    for row in rows:
        warnings: list[str] = []
        name = _clip(row.product_name, MAX_NAME_CHARS, RowWarning.NAME_TRUNCATED, warnings)
        brand = _clip(row.brand_name, MAX_BRAND_CHARS, RowWarning.BRAND_TRUNCATED, warnings)

        def outcome(
            status: BatchRowStatus,
            *,
            normalized: str | None = None,
            errors: list[str] | None = None,
            code: str | None = None,
            _row: SourceRow = row,
            _w: list[str] = warnings,
            _n: str | None = name,
            _b: str | None = brand,
        ) -> RowOutcome:
            return RowOutcome(_row, status, code, normalized, _n, _b, errors or [], _w)

        market = _normalize_header(row.marketplace)
        if market in FLIPKART_VALUES or (not row.identifier and row.fsn):
            outcomes.append(
                outcome(BatchRowStatus.INVALID, errors=[RowError.FLIPKART_NOT_SUPPORTED])
            )
            continue
        if market not in AMAZON_MARKETPLACE_VALUES:
            outcomes.append(outcome(BatchRowStatus.INVALID, errors=[RowError.UNKNOWN_MARKETPLACE]))
            continue
        if not row.identifier.strip():
            outcomes.append(outcome(BatchRowStatus.INVALID, errors=[RowError.MISSING_IDENTIFIER]))
            continue

        parsed = parse_asin(row.identifier)
        warnings.extend(parsed.warnings)
        if not parsed.valid or parsed.normalized is None:
            assert parsed.error is not None
            outcomes.append(
                outcome(
                    BatchRowStatus.INVALID, errors=[parsed.error], code=MarketplaceCode.AMAZON_IN
                )
            )
            continue
        asin = parsed.normalized
        if asin in first_seen:
            outcomes.append(
                outcome(
                    BatchRowStatus.DUPLICATE_IN_FILE,
                    normalized=asin,
                    errors=[f"{RowError.DUPLICATE_IN_FILE}:{first_seen[asin]}"],
                    code=MarketplaceCode.AMAZON_IN,
                )
            )
            continue
        first_seen[asin] = row.row_number
        if asin in existing:
            outcomes.append(
                outcome(
                    BatchRowStatus.DUPLICATE_EXISTING,
                    normalized=asin,
                    errors=[RowError.ALREADY_EXISTS],
                    code=MarketplaceCode.AMAZON_IN,
                )
            )
            continue
        outcomes.append(
            outcome(BatchRowStatus.VALID, normalized=asin, code=MarketplaceCode.AMAZON_IN)
        )
    return outcomes
