"""Upload file safety checks: type by extension AND content, size, macros, zip bombs.

Only `.csv` (text) and `.xlsx` (Office Open XML workbook) are accepted. Macro-enabled
workbooks, legacy/encrypted Office files and anything whose content doesn't match its
extension are rejected before parsing.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath

ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .xls and password-protected Office files
MAX_ZIP_ENTRIES = 2_000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_CONTENT_TYPE = "text/csv"


class FileKind(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


class RejectCode(StrEnum):
    EMPTY = "empty_file"
    TOO_LARGE = "file_too_large"
    UNSUPPORTED_TYPE = "unsupported_file_type"
    MACRO_ENABLED = "macro_enabled_workbook"
    LEGACY_OR_ENCRYPTED = "legacy_or_encrypted_workbook"
    CONTENT_MISMATCH = "content_does_not_match_extension"
    CORRUPT = "corrupt_file"
    TOO_MANY_ROWS = "too_many_rows"
    NO_HEADER = "no_header_row"
    NO_IDENTIFIER_COLUMN = "no_asin_column"
    FLIPKART_ONLY = "flipkart_only_file"
    ENCODING = "unreadable_text_encoding"


REJECT_MESSAGES: dict[RejectCode, str] = {
    RejectCode.EMPTY: "The file is empty.",
    RejectCode.TOO_LARGE: "The file is larger than the {limit_mb} MB limit.",
    RejectCode.UNSUPPORTED_TYPE: "Upload a .csv or .xlsx file.",
    RejectCode.MACRO_ENABLED: (
        "Macro-enabled workbooks are not accepted. Save the file as .xlsx (Excel Workbook) "
        "and upload it again."
    ),
    RejectCode.LEGACY_OR_ENCRYPTED: (
        "This looks like an old .xls file or a password-protected workbook. "
        "Save it as an unprotected .xlsx file and upload it again."
    ),
    RejectCode.CONTENT_MISMATCH: "The file's contents don't match its extension.",
    RejectCode.CORRUPT: "The file could not be read. It may be damaged.",
    RejectCode.TOO_MANY_ROWS: (
        "The file has more than {limit_rows} rows. Split it into smaller files."
    ),
    RejectCode.NO_HEADER: "No header row found. The first non-empty row must contain column names.",
    RejectCode.NO_IDENTIFIER_COLUMN: (
        "No ASIN column found. Add a column named 'ASIN' (ASINs or Amazon.in product links)."
    ),
    RejectCode.FLIPKART_ONLY: (
        "This file only has Flipkart FSNs. Flipkart is not supported yet; "
        "SellerScope currently monitors Amazon.in."
    ),
    RejectCode.ENCODING: "The CSV file's text encoding couldn't be read. Save it as UTF-8 CSV.",
}


class FileRejectedError(Exception):
    def __init__(self, code: RejectCode, **fmt: object) -> None:
        self.code = code
        self.message = REJECT_MESSAGES[code].format(**fmt)
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class InspectedFile:
    kind: FileKind
    content_type: str


def _check_xlsx(data: bytes) -> None:
    if data.startswith(OLE_MAGIC):
        raise FileRejectedError(RejectCode.LEGACY_OR_ENCRYPTED)
    if not data.startswith(ZIP_MAGIC):
        raise FileRejectedError(RejectCode.CONTENT_MISMATCH)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise FileRejectedError(RejectCode.CORRUPT)
            if sum(e.file_size for e in entries) > MAX_UNCOMPRESSED_BYTES:
                raise FileRejectedError(RejectCode.CORRUPT)  # decompression bomb
            names = {e.filename for e in entries}
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise FileRejectedError(RejectCode.CONTENT_MISMATCH)
            content_types = archive.read("[Content_Types].xml").decode("utf-8", "replace")
    except zipfile.BadZipFile as exc:
        raise FileRejectedError(RejectCode.CORRUPT) from exc
    if any(n.lower().endswith("vbaproject.bin") for n in names) or "macroEnabled" in content_types:
        raise FileRejectedError(RejectCode.MACRO_ENABLED)


def _check_csv(data: bytes) -> None:
    head = data[:65536]
    if head.startswith(ZIP_MAGIC) or head.startswith(OLE_MAGIC) or b"\x00" in head:
        raise FileRejectedError(RejectCode.CONTENT_MISMATCH)


def inspect_upload(filename: str, data: bytes, *, max_bytes: int) -> InspectedFile:
    """Raises FileRejectedError unless the file is a safe, supported spreadsheet."""
    if not data:
        raise FileRejectedError(RejectCode.EMPTY)
    if len(data) > max_bytes:
        raise FileRejectedError(RejectCode.TOO_LARGE, limit_mb=max_bytes // (1024 * 1024))
    suffix = PurePath(filename or "").suffix.lower()
    if suffix in {".xlsm", ".xltm", ".xlam"}:
        raise FileRejectedError(RejectCode.MACRO_ENABLED)
    if suffix in {".xls", ".xlsb"}:
        raise FileRejectedError(RejectCode.LEGACY_OR_ENCRYPTED)
    if suffix == ".xlsx":
        _check_xlsx(data)
        return InspectedFile(FileKind.XLSX, XLSX_CONTENT_TYPE)
    if suffix == ".csv":
        _check_csv(data)
        return InspectedFile(FileKind.CSV, CSV_CONTENT_TYPE)
    raise FileRejectedError(RejectCode.UNSUPPORTED_TYPE)
