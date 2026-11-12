"""M5 acceptance tests: upload → parse → preview → commit/discard, history, exports."""

from __future__ import annotations

import csv
import io
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sellerscope.core.ids import uuid7
from sellerscope.main import create_app
from tests.integration.conftest import AppUser, InlineDispatcher, RecordingMailer, api_settings
from tests.integration.test_api_accounts import join, make_org
from tests.integration.test_api_products import create
from tests.upload_fixtures import MIXED_ROWS, csv_bytes, with_macro, xlsx

pytestmark = pytest.mark.integration

Api = tuple[AsyncClient, RecordingMailer]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def upload(
    client: AsyncClient, user: AppUser, org: str, name: str, data: bytes, content_type: str = XLSX
) -> Any:
    return await client.post(
        "/api/v1/uploads", files={"file": (name, data, content_type)}, headers=user.headers(org)
    )


async def uploaded(
    client: AsyncClient, user: AppUser, org: str, name: str, data: bytes
) -> dict[str, Any]:
    r = await upload(client, user, org, name, data)
    assert r.status_code == 202, r.text
    detail = await client.get(f"/api/v1/uploads/{r.json()['id']}", headers=user.headers(org))
    return dict(detail.json())


async def rows(client: AsyncClient, user: AppUser, org: str, batch: str, **params: Any) -> Any:
    r = await client.get(f"/api/v1/uploads/{batch}/rows", params=params, headers=user.headers(org))
    assert r.status_code == 200, r.text
    return r.json()


async def test_upload_preview_and_commit(api: Api, owner_engine: AsyncEngine) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    await create(client, owner, org, "B0UPLOAD05")  # already exists before the upload

    r = await upload(client, owner, org, "../../etc/catalog.xlsx", xlsx(MIXED_ROWS))
    assert r.status_code == 202
    assert r.json()["status"] == "uploaded"
    assert r.json()["original_filename"] == "catalog.xlsx"  # path parts stripped
    batch = (
        await client.get(f"/api/v1/uploads/{r.json()['id']}", headers=owner.headers(org))
    ).json()
    assert batch["status"] == "preview_ready"
    assert (
        batch["total_rows"],
        batch["valid_rows"],
        batch["invalid_rows"],
        batch["duplicate_in_file_rows"],
        batch["duplicate_existing_rows"],
    ) == (9, 2, 5, 1, 1)
    assert batch["column_mapping"]["identifier"] == "ASIN (required)"
    assert batch["plan"] == {"limit": 100, "current": 1, "remaining": 99}

    invalid = await rows(client, owner, org, batch["id"], status="invalid")
    assert invalid["total"] == 5
    by_row = {r["row_number"]: r for r in invalid["items"]}
    assert by_row[8]["errors"][0]["code"] == "short_link_not_supported"
    assert "Short links" in by_row[8]["errors"][0]["message"]
    assert by_row[9]["errors"][0]["message"].startswith("Flipkart is not supported")
    dup = (await rows(client, owner, org, batch["id"], status="duplicate_in_file"))["items"][0]
    assert dup["errors"][0] == {
        "code": "duplicate_in_file",
        "message": "Same ASIN as row 2; only the first occurrence is added.",
    }
    assert dup["original"]["Product Title"] == "Steel Bottle again"

    r = await client.post(f"/api/v1/uploads/{batch['id']}/commit", headers=owner.headers(org))
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["committed_rows"]) == ("committed", 2)
    assert r.json()["plan"]["current"] == 3

    products = (
        await client.get(
            "/api/v1/products",
            params={"sort": "external_id", "order": "asc"},
            headers=owner.headers(org),
        )
    ).json()["items"]
    assert [(p["external_id"], p["product_name"], p["brand_name"]) for p in products] == [
        ("B0UPLOAD01", "Steel Bottle", "Hydra"),
        ("B0UPLOAD02", "Yoga Mat", "Zen"),
        ("B0UPLOAD05", None, None),
    ]
    valid = await rows(client, owner, org, batch["id"], status="valid")
    assert all(item["product_id"] for item in valid["items"])

    r = await client.post(f"/api/v1/uploads/{batch['id']}/commit", headers=owner.headers(org))
    assert r.status_code == 409  # cannot commit twice

    async with owner_engine.connect() as conn:
        actions = (
            (
                await conn.execute(
                    text(
                        "SELECT action FROM audit_logs "
                        "WHERE organization_id = :o AND action LIKE 'upload.%' "
                        "ORDER BY created_at"
                    ),
                    {"o": org},
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["upload.create", "upload.commit"]


async def test_products_added_after_preview_are_not_duplicated(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    batch = await uploaded(
        client, owner, org, "p.csv", csv_bytes([["ASIN"], ["B0RACE0001"], ["B0RACE0002"]])
    )
    await create(client, owner, org, "B0RACE0002")  # added manually while previewing
    r = await client.post(f"/api/v1/uploads/{batch['id']}/commit", headers=owner.headers(org))
    assert r.status_code == 200
    assert (r.json()["committed_rows"], r.json()["duplicate_existing_rows"]) == (1, 1)


async def test_commit_is_all_or_nothing_against_plan_limit(
    api: Api, owner_engine: AsyncEngine
) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    async with owner_engine.begin() as conn:
        code = f"small-{uuid7().hex[:8]}"
        await conn.execute(
            text(
                "INSERT INTO plans (id, code, name, max_products, max_scans_per_month, "
                "max_members, min_scan_interval_minutes) "
                "VALUES (:i, :c, 'Small', 2, 10, 1, 60)"
            ),
            {"i": uuid7(), "c": code},
        )
        await conn.execute(
            text(
                "UPDATE subscriptions SET plan_id = (SELECT id FROM plans WHERE code = :c) "
                "WHERE organization_id = :o"
            ),
            {"c": code, "o": org},
        )
    batch = await uploaded(
        client, owner, org, "p.csv", csv_bytes([["ASIN"], *[[f"B0LIMIT{i:03d}"] for i in range(3)]])
    )
    assert batch["plan"]["remaining"] == 2
    r = await client.post(f"/api/v1/uploads/{batch['id']}/commit", headers=owner.headers(org))
    assert r.status_code == 402 and r.json()["code"] == "plan_limit_reached"
    assert (await client.get("/api/v1/products", headers=owner.headers(org))).json()["total"] == 0
    detail = (await client.get(f"/api/v1/uploads/{batch['id']}", headers=owner.headers(org))).json()
    assert detail["status"] == "preview_ready"  # still committable after removing products


@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("p.txt", b"ASIN\nB0CHX1W1XY", 422, "unsupported_file_type"),
        ("p.xlsm", xlsx([["ASIN"]]), 422, "macro_enabled_workbook"),
        ("p.xlsx", with_macro(xlsx([["ASIN"]])), 422, "macro_enabled_workbook"),
        ("p.xlsx", b"ASIN\nB0CHX1W1XY", 422, "content_does_not_match_extension"),
        ("p.csv", b"", 422, "empty_file"),
    ],
)
async def test_unsafe_files_rejected_before_storage(
    api: Api, owner_engine: AsyncEngine, name: str, data: bytes, status: int, code: str
) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    r = await upload(client, owner, org, name, data)
    assert r.status_code == status
    assert r.json()["code"] == code
    assert (await client.get("/api/v1/uploads", headers=owner.headers(org))).json()["total"] == 0


async def test_oversized_upload_rejected(owner_engine: AsyncEngine) -> None:
    app = create_app(api_settings(upload_max_bytes=1024))
    app.state.task_dispatcher = InlineDispatcher(app)
    owner = AppUser("o")
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        org = await make_org(client, owner)
        r = await upload(client, owner, org, "big.csv", b"ASIN\n" + b"B0CHX1W1XY\n" * 200)
        assert r.status_code == 413
        assert r.json()["code"] == "file_too_large"


async def test_unreadable_structure_marks_batch_failed(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    batch = await uploaded(client, owner, org, "p.csv", csv_bytes([["Name", "Brand"], ["a", "b"]]))
    assert batch["status"] == "failed"
    assert batch["error_code"] == "no_asin_column"
    assert "ASIN column" in batch["error_message"]
    r = await client.post(f"/api/v1/uploads/{batch['id']}/commit", headers=owner.headers(org))
    assert r.status_code == 409


async def test_discard(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    batch = await uploaded(client, owner, org, "p.csv", csv_bytes([["ASIN"], ["B0DISCARD1"]]))
    r = await client.post(f"/api/v1/uploads/{batch['id']}/discard", headers=owner.headers(org))
    assert r.json()["status"] == "discarded"
    assert (
        await client.post(f"/api/v1/uploads/{batch['id']}/commit", headers=owner.headers(org))
    ).status_code == 409
    assert (
        await client.post(f"/api/v1/uploads/{batch['id']}/discard", headers=owner.headers(org))
    ).status_code == 409


async def test_rejected_rows_csv_is_injection_safe(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    # CSV keeps the formula as literal text (an .xlsx written by openpyxl has no cached value).
    batch = await uploaded(client, owner, org, "Q3 catalog.csv", csv_bytes(MIXED_ROWS))
    r = await client.get(f"/api/v1/uploads/{batch['id']}/rejected.csv", headers=owner.headers(org))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="Q3 catalog-rejected.csv"' in r.headers["content-disposition"]
    table = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert table[0][:3] == ["Row", "Status", "Reason"]
    assert [row[0] for row in table[1:]] == ["5", "6", "7", "8", "9", "10"]
    flipkart = next(row for row in table if row[0] == "9")
    assert "'=HYPERLINK" in ",".join(flipkart)  # formula neutralised
    assert not any(cell.startswith("=") for row in table for cell in row)


async def test_template_round_trip(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    x = await client.get(
        "/api/v1/uploads/template", params={"format": "xlsx"}, headers=owner.headers()
    )
    workbook = load_workbook(io.BytesIO(x.content), read_only=True)
    assert workbook.sheetnames == ["Products", "Instructions"]
    c = await client.get(
        "/api/v1/uploads/template", params={"format": "csv"}, headers=owner.headers()
    )
    assert c.text.lstrip("﻿").strip() == "ASIN,Product name,Brand"
    # The unmodified template parses (zero rows) instead of failing.
    batch = await uploaded(client, owner, org, "sellerscope-products.xlsx", x.content)
    assert (batch["status"], batch["total_rows"]) == ("preview_ready", 0)


async def test_history_and_same_file_detection(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    data = csv_bytes([["ASIN"], ["B0SAMEFILE"]])
    first = await uploaded(client, owner, org, "a.csv", data)
    await client.post(f"/api/v1/uploads/{first['id']}/commit", headers=owner.headers(org))
    second = await uploaded(client, owner, org, "a-copy.csv", data)
    assert second["same_file_as"] == first["id"]
    assert second["duplicate_existing_rows"] == 1
    history = (
        await client.get("/api/v1/uploads", params={"page_size": 1}, headers=owner.headers(org))
    ).json()
    assert history["total"] == 2
    assert history["items"][0]["id"] == second["id"]  # newest first


async def test_viewer_cannot_upload_but_can_review(api: Api) -> None:
    client, mailer = api
    owner, viewer = AppUser("o"), AppUser("v")
    org = await make_org(client, owner)
    await join(client, mailer, org, owner, viewer, "viewer")
    batch = await uploaded(client, owner, org, "p.csv", csv_bytes([["ASIN"], ["B0VIEWER01"]]))
    assert (await upload(client, viewer, org, "p.csv", csv_bytes([["ASIN"]]))).status_code == 403
    assert (
        await client.get(f"/api/v1/uploads/{batch['id']}", headers=viewer.headers(org))
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/uploads/{batch['id']}/commit", headers=viewer.headers(org))
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/uploads/{batch['id']}/discard", headers=viewer.headers(org))
    ).status_code == 403


async def test_large_file_end_to_end(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    data = xlsx(
        [["ASIN", "Name"], *[[f"B0BIG{i:05d}", f"Item {i}"] for i in range(5_000)]], write_only=True
    )
    batch = await uploaded(client, owner, org, "big.xlsx", data)
    assert (batch["status"], batch["valid_rows"]) == ("preview_ready", 5_000)
    page = await rows(client, owner, org, batch["id"], page=50, page_size=100)
    assert (page["total"], page["items"][0]["row_number"]) == (5_000, 4_902)
