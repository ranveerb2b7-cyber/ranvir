"""File safety checks, parsing and row classification (no database)."""

from __future__ import annotations

import time

import boto3
import pytest
from moto import mock_aws

from sellerscope.api.v1.uploads import csv_safe
from sellerscope.core.config import AppEnv, Settings
from sellerscope.models.enums import BatchRowStatus
from sellerscope.storage import S3Storage
from sellerscope.uploads.files import FileKind, FileRejectedError, RejectCode, inspect_upload
from sellerscope.uploads.parse import classify, parse_table, read_rows
from tests.upload_fixtures import MIXED_ROWS, csv_bytes, with_macro, xlsx, zip_bomb

MB = 1024 * 1024
OK = [["ASIN"], ["B0CHX1W1XY"]]


# ------------------------------------------------------------------------------ inspection


def test_accepts_xlsx_and_csv() -> None:
    assert inspect_upload("p.xlsx", xlsx(OK), max_bytes=MB).kind == FileKind.XLSX
    assert inspect_upload("P.CSV", csv_bytes(OK), max_bytes=MB).kind == FileKind.CSV


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("p.csv", b"", RejectCode.EMPTY),
        ("p.csv", b"A" * (MB + 1), RejectCode.TOO_LARGE),
        ("p.txt", b"ASIN\nB0CHX1W1XY", RejectCode.UNSUPPORTED_TYPE),
        ("p.pdf", b"%PDF-1.7", RejectCode.UNSUPPORTED_TYPE),
        ("macro.xlsm", xlsx(OK), RejectCode.MACRO_ENABLED),
        ("renamed.xlsx", with_macro(xlsx(OK)), RejectCode.MACRO_ENABLED),
        (
            "old.xls",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100,
            RejectCode.LEGACY_OR_ENCRYPTED,
        ),
        (
            "locked.xlsx",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100,
            RejectCode.LEGACY_OR_ENCRYPTED,
        ),
        ("fake.xlsx", b"ASIN\nB0CHX1W1XY", RejectCode.CONTENT_MISMATCH),
        ("fake.csv", xlsx(OK), RejectCode.CONTENT_MISMATCH),
        ("binary.csv", b"ASIN\x00\x01\x02", RejectCode.CONTENT_MISMATCH),
        ("bomb.xlsx", zip_bomb(), RejectCode.CORRUPT),
        ("broken.xlsx", b"PK\x03\x04garbage", RejectCode.CORRUPT),
    ],
)
def test_rejects_unsafe_or_unsupported_files(name: str, data: bytes, code: RejectCode) -> None:
    with pytest.raises(FileRejectedError) as err:
        inspect_upload(name, data, max_bytes=MB)
    assert err.value.code == code
    assert err.value.message


# ------------------------------------------------------------------------------ parsing


def test_parses_mixed_file_with_aliases_and_blank_rows() -> None:
    table = parse_table(read_rows(FileKind.XLSX, xlsx(MIXED_ROWS)), max_rows=100)
    assert table.mapping == {
        "identifier": "ASIN (required)",
        "product_name": "Product Title",
        "brand_name": "Brand Name",
        "marketplace": "Marketplace",
    }
    numbers = [r.row_number for r in table.rows]
    assert numbers == [2, 3, 5, 6, 7, 8, 9, 10, 11]  # row 4 was blank
    assert table.rows[0].raw == {
        "ASIN (required)": "B0UPLOAD01",
        "Product Title": "Steel Bottle",
        "Brand Name": "Hydra",
        "Marketplace": "Amazon.in",
    }


def test_csv_encodings_and_delimiters() -> None:
    rows = [["asin", "brand"], ["B0CHX1W1XY", "Café Ltd"]]
    for data in (
        csv_bytes(rows, encoding="utf-8"),
        b"\xef\xbb\xbf" + csv_bytes(rows),
        csv_bytes(rows, encoding="cp1252"),
        csv_bytes(rows, delimiter=";"),
    ):
        table = parse_table(read_rows(FileKind.CSV, data), max_rows=10)
        assert table.rows[0].identifier == "B0CHX1W1XY"
        assert table.rows[0].brand_name == "Café Ltd"


def test_numeric_cells_keep_integer_form() -> None:
    table = parse_table(read_rows(FileKind.XLSX, xlsx([["ASIN"], [8172234988]])), max_rows=10)
    assert table.rows[0].identifier == "8172234988"


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        ([], RejectCode.NO_HEADER),
        ([["Name", "Brand"], ["x", "y"]], RejectCode.NO_IDENTIFIER_COLUMN),
        ([["FSN", "Name"], ["ABCDEFGHIJKLMNOP", "x"]], RejectCode.FLIPKART_ONLY),
    ],
)
def test_structural_problems(rows: list[list[object]], code: RejectCode) -> None:
    with pytest.raises(FileRejectedError) as err:
        parse_table(read_rows(FileKind.CSV, csv_bytes(rows) or b"\n"), max_rows=10)
    assert err.value.code == code


def test_row_limit() -> None:
    rows = [["ASIN"], *[[f"B0{i:08d}"] for i in range(11)]]
    with pytest.raises(FileRejectedError) as err:
        parse_table(read_rows(FileKind.CSV, csv_bytes(rows)), max_rows=10)
    assert err.value.code == RejectCode.TOO_MANY_ROWS
    assert "10" in err.value.message


# ------------------------------------------------------------------------------ classification


def test_classification_of_mixed_file() -> None:
    table = parse_table(read_rows(FileKind.XLSX, xlsx(MIXED_ROWS)), max_rows=100)
    outcomes = classify(table.rows, existing={"B0UPLOAD05"})
    got = [(o.source.row_number, o.status, o.normalized, o.errors) for o in outcomes]
    assert got == [
        (2, BatchRowStatus.VALID, "B0UPLOAD01", []),
        (3, BatchRowStatus.VALID, "B0UPLOAD02", []),
        (5, BatchRowStatus.DUPLICATE_IN_FILE, "B0UPLOAD01", ["duplicate_in_file:2"]),
        (6, BatchRowStatus.INVALID, None, ["invalid_format"]),
        (7, BatchRowStatus.INVALID, None, ["missing_identifier"]),
        (8, BatchRowStatus.INVALID, None, ["short_link_not_supported"]),
        (9, BatchRowStatus.INVALID, None, ["flipkart_not_supported"]),
        (10, BatchRowStatus.INVALID, None, ["unknown_marketplace"]),
        (11, BatchRowStatus.DUPLICATE_EXISTING, "B0UPLOAD05", ["already_exists"]),
    ]
    assert outcomes[0].product_name == "Steel Bottle"
    assert outcomes[1].brand_name == "Zen"


def test_fsn_only_rows_are_reported_not_dropped() -> None:
    table = parse_table(
        read_rows(
            FileKind.CSV, csv_bytes([["ASIN", "FSN"], ["B0CHX1W1XY", ""], ["", "ABCDEFGHIJKLMNOP"]])
        ),
        max_rows=10,
    )
    outcomes = classify(table.rows, existing=set())
    assert [o.status for o in outcomes] == [BatchRowStatus.VALID, BatchRowStatus.INVALID]
    assert outcomes[1].errors == ["flipkart_not_supported"]


def test_long_text_is_truncated_with_warning() -> None:
    table = parse_table(
        read_rows(
            FileKind.CSV,
            csv_bytes([["ASIN", "Name", "Brand"], ["B0CHX1W1XY", "n" * 400, "b" * 200]]),
        ),
        max_rows=10,
    )
    outcome = classify(table.rows, existing=set())[0]
    assert outcome.status == BatchRowStatus.VALID
    assert len(outcome.product_name or "") == 300
    assert outcome.warnings == ["name_truncated", "brand_truncated"]


def test_fifty_thousand_rows_within_budget() -> None:
    rows: list[list[object]] = [["ASIN", "Product name", "Brand"]]
    rows += [[f"B0{i:08d}", f"Product {i}", f"Brand {i % 50}"] for i in range(50_000)]
    data = xlsx(rows, write_only=True)
    start = time.perf_counter()
    table = parse_table(read_rows(FileKind.XLSX, data), max_rows=50_000)
    outcomes = classify(table.rows, existing=set())
    elapsed = time.perf_counter() - start
    assert len(outcomes) == 50_000
    assert all(o.status == BatchRowStatus.VALID for o in outcomes)
    assert elapsed < 30, f"parsing 50k rows took {elapsed:.1f}s"


# ------------------------------------------------------------------------------ export safety


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+91", "'+91"),
        ("-2", "'-2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("B0CHX1W1XY", "B0CHX1W1XY"),
        ("", ""),
    ],
)
def test_csv_injection_is_neutralised(value: str, expected: str) -> None:
    assert csv_safe(value) == expected


# ------------------------------------------------------------------------------ S3 storage


async def test_s3_storage_round_trip() -> None:
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket="ss-test", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        storage = S3Storage(
            Settings(
                app_env=AppEnv.TEST,
                storage_backend="s3",
                s3_bucket="ss-test",
                s3_access_key_id="test",
                s3_secret_access_key="test",
            )  # type: ignore[arg-type]
        )
        key = "org/x/uploads/y/original.csv"
        await storage.put(key, b"ASIN\n", "text/csv")
        assert await storage.get(key) == b"ASIN\n"
        assert s3.head_object(Bucket="ss-test", Key=key)["ServerSideEncryption"] == "AES256"
        await storage.delete(key)
        assert s3.list_objects_v2(Bucket="ss-test").get("KeyCount") == 0
