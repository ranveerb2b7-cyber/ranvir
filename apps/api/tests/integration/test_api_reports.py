"""M11 acceptance tests: report contents match the database, unknowns are blank with a reason,
formula injection is neutralised, lifecycle (permissions, audit, failures, expiry, recovery)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sellerscope.connectors.base import PermanentError
from sellerscope.reports import builders
from sellerscope.reports.service import expire_reports, recover_stale_reports
from tests.integration.conftest import AppUser, FakeClock, RecordingMailer
from tests.integration.test_api_accounts import join, make_org
from tests.integration.test_api_intel import gone, scan_once, snap
from tests.integration.test_api_products import create
from tests.integration.test_api_scans import FakeConnector, scan_api

pytestmark = pytest.mark.integration

EVIL_NAME = '=HYPERLINK("http://evil.example","Click")'


async def request_report(
    client: AsyncClient, user: AppUser, org: str, report_type: str, fmt: str = "csv", **filters: Any
) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/reports",
        json={"report_type": report_type, "format": fmt, "filters": filters},
        headers=user.headers(org),
    )
    assert r.status_code == 202, r.text
    report = (
        await client.get(f"/api/v1/reports/{r.json()['id']}", headers=user.headers(org))
    ).json()
    assert report["status"] == "completed", report
    return dict(report)


async def download(client: AsyncClient, user: AppUser, org: str, report_id: str) -> bytes:
    r = await client.get(f"/api/v1/reports/{report_id}/download", headers=user.headers(org))
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.content


async def csv_rows(
    client: AsyncClient, user: AppUser, org: str, report_type: str, **f: Any
) -> list[dict[str, str]]:
    report = await request_report(client, user, org, report_type, "csv", **f)
    data = await download(client, user, org, report["id"])
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    assert report["row_count"] == len(rows)
    return rows


async def org_with_scans(
    client: AsyncClient, fake: FakeConnector, clock: FakeClock
) -> tuple[AppUser, str, dict[str, str]]:
    owner = AppUser("rep")
    org = await make_org(client, owner)
    ids = {
        "OK": (
            await create(client, owner, org, "B0REPORT01", product_name="Bottle", brand_name="Acme")
        )["id"],
        "GONE": (
            await create(client, owner, org, "B0REPORT02", product_name="Flask", brand_name="Acme")
        )["id"],
        "NEW": (await create(client, owner, org, "B0REPORT03", brand_name="Globex"))["id"],
        "FAIL": (
            await create(
                client, owner, org, "B0REPORT04", product_name=EVIL_NAME, brand_name="+cmd"
            )
        )["id"],
        "CUT": (await create(client, owner, org, "B0REPORT05"))["id"],
    }
    fake.script["B0REPORT01"].append(
        snap("B0REPORT01", "S1", "S2", prices={"S1": "499.00", "S2": "520.50"}, buy_box="S1")
    )
    fake.script["B0REPORT02"].append(gone("B0REPORT02", "not_found"))
    fake.script["B0REPORT04"] += [
        snap("B0REPORT04", "S1"),
        PermanentError("asin_rejected", "Rejected by source."),
    ]
    fake.script["B0REPORT05"].append(snap("B0REPORT05", "S3", "S4", total=30, truncated=True))
    for key in ("OK", "GONE", "FAIL", "CUT"):
        await scan_once(client, owner, org, ids[key])
    clock.now = datetime.now(UTC)  # failures are stamped by the runner's clock
    await scan_once(client, owner, org, ids["FAIL"])  # the second scan fails
    return owner, org, ids


async def test_product_report_matches_data_with_blanks_and_reasons() -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        owner, org, _ = await org_with_scans(client, fake, dispatcher.clock)
        rows = {r["ASIN"]: r for r in await csv_rows(client, owner, org, "product")}
        assert list(rows) == [f"B0REPORT0{i}" for i in range(1, 6)]  # sorted by ASIN

        ok = rows["B0REPORT01"]
        assert ok["Data status"] == "OK" and ok["Data source"] == "fake-source"
        assert (
            ok["Total offers (reported by Amazon)"],
            ok["Offers observed"],
            ok["Unique sellers"],
        ) == ("2", "2", "2")
        assert (ok["Lowest price"], ok["Highest price"], ok["Currency"]) == (
            "499.00",
            "520.50",
            "INR",
        )
        assert ok["Offer list complete"] == "Yes" and ok["Monitoring"] == "Yes"

        missing = rows["B0REPORT02"]  # not found: blanks, never 0, with the reason
        assert missing["Data status"] == "Not found"
        for col in (
            "Total offers (reported by Amazon)",
            "Offers observed",
            "Unique sellers",
            "Lowest price",
        ):
            assert missing[col] == "", col
        assert "not found" in missing["Notes"]

        never = rows["B0REPORT03"]
        assert never["Data as of (UTC)"] == "" and never["Offers observed"] == ""
        assert never["Notes"] == "Not scanned yet."

        failed = rows["B0REPORT04"]  # failure after a good scan: old data kept, failure noted
        assert failed["Offers observed"] == "1" and failed["Last attempt result"] == "Failed"
        assert "latest scan failed (asin_rejected)" in failed["Notes"]
        assert failed["Product name"] == "'" + EVIL_NAME and failed["Brand"] == "'+cmd"

        cut = rows["B0REPORT05"]
        assert (cut["Total offers (reported by Amazon)"], cut["Offers observed"]) == ("30", "2")
        assert cut["Offer list complete"] == "No" and "lower bound" in cut["Notes"]

        acme = await csv_rows(client, owner, org, "product", brand="Acme")
        assert [r["ASIN"] for r in acme] == ["B0REPORT01", "B0REPORT02"]
        nobrand = await csv_rows(client, owner, org, "product", brand="__none__")
        assert [r["ASIN"] for r in nobrand] == ["B0REPORT05"]

        # XLSX: same data; the hostile name is a text cell, not a formula.
        report = await request_report(client, owner, org, "product", "xlsx")
        assert report["file_name"].endswith(".xlsx") and report["contains_mock"] is False
        book = load_workbook(io.BytesIO(await download(client, owner, org, report["id"])))
        sheet = book["Products"]
        header = [c.value for c in sheet[1]]
        evil = next(r for r in sheet.iter_rows(min_row=2) if r[0].value == "B0REPORT04")
        name = evil[header.index("Product name")]
        assert name.value == EVIL_NAME and name.data_type == "s"
        missing_row = next(r for r in sheet.iter_rows(min_row=2) if r[0].value == "B0REPORT02")
        assert missing_row[header.index("Offers observed")].value is None
        about = [c.value for c in book["About"]["A"]]
        assert any("never zero" in (line or "") for line in about)


async def test_summary_reports_match_the_database() -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        owner, org, _ = await org_with_scans(client, fake, dispatcher.clock)

        [market] = await csv_rows(client, owner, org, "marketplace")
        assert (market["Products"], market["Scanned"], market["With usable data"]) == (
            "5",
            "4",
            "3",
        )
        assert (
            market["With multiple sellers"],
            market["Offers observed"],
            market["Unavailable or not found"],
        ) == ("2", "5", "1")

        brands = {r["Brand"]: r for r in await csv_rows(client, owner, org, "brand")}
        assert list(brands) == ["'+cmd", "Acme", "Globex", "(no brand)"]
        acme = brands["Acme"]
        assert (acme["Products"], acme["With usable data"], acme["Distinct sellers observed"]) == (
            "2",
            "1",
            "2",
        )
        assert (acme["Lowest price"], acme["Highest price"], acme["Unavailable or not found"]) == (
            "499.00",
            "520.50",
            "1",
        )
        globex = brands["Globex"]
        assert globex["Distinct sellers observed"] == "" and "No product" in globex["Notes"]
        assert "lower bound" in brands["(no brand)"]["Notes"]

        sellers = {r["Seller ID"]: r for r in await csv_rows(client, owner, org, "seller")}
        assert sellers["S1"]["Products offering now"] == "2"  # B0REPORT01 and B0REPORT04
        assert (
            sellers["S1"]["Buy Box held now"] == "1"
            and sellers["S1"]["Lowest current price"] == "100.00"
        )
        assert sellers["S1"]["ASINs offering now"] == "B0REPORT01; B0REPORT04"
        offering = await csv_rows(client, owner, org, "seller", currently_offering=True)
        assert {r["Seller ID"] for r in offering} == {"S1", "S2", "S3", "S4"}

        jobs = await csv_rows(client, owner, org, "scan_summary")
        assert len(jobs) == 5 and {j["Requested by"] for j in jobs} == {owner.email}
        assert sorted(j["Failed"] for j in jobs) == ["0", "0", "0", "0", "1"]

        errors = await csv_rows(client, owner, org, "errors")
        assert [(e["ASIN"], e["Result"], e["Error code"]) for e in errors] == [
            ("B0REPORT04", "Failed", "asin_rejected"),
            ("B0REPORT02", "Not found", ""),
        ]
        assert errors[0]["Message"] == "Rejected by source."
        # Outside the period: nothing.
        assert (
            await csv_rows(
                client, owner, org, "errors", date_from="2020-01-01", date_to="2020-01-31"
            )
            == []
        )


async def test_alert_history_report() -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        dispatcher.app.state.mailer = RecordingMailer()
        owner = AppUser("rep")
        org = await make_org(client, owner)
        pid = (await create(client, owner, org, "B0REPORT09"))["id"]
        r = await client.post(
            "/api/v1/alert-rules",
            json={"name": "Failures", "rule_type": "scan_failed", "channels": ["email"],
                  "recipient_user_ids": [str(owner.id)]},
            headers=owner.headers(org),
        )  # fmt: skip
        assert r.status_code == 201
        fake.script["B0REPORT09"].append(PermanentError("asin_rejected", "x"))
        await scan_once(client, owner, org, pid)
        [row] = await csv_rows(client, owner, org, "alerts")
        assert (row["Rule"], row["Status"], row["ASIN"], row["Email"]) == (
            "Failures",
            "open",
            "B0REPORT09",
            "1 sent",
        )
        assert row["Resolved automatically"] == "" and row["Severity"] == "warning"
        assert await csv_rows(client, owner, org, "alerts", status="resolved") == []


async def test_mock_data_is_labelled_in_reports(api: tuple[AsyncClient, RecordingMailer]) -> None:
    client, _ = api
    owner = AppUser("mock")
    org = await make_org(client, owner)
    pid = (await create(client, owner, org, "B0VICTIM01"))["id"]
    await scan_once(client, owner, org, pid)
    report = await request_report(client, owner, org, "product", "xlsx")
    assert report["contains_mock"] is True
    book = load_workbook(io.BytesIO(await download(client, owner, org, report["id"])))
    assert any("MOCK data" in (c.value or "") for c in book["About"]["A"])
    sheet = book["Products"]
    header = [c.value for c in sheet[1]]
    assert sheet[2][header.index("Data source")].value == "MOCK"
    assert "MOCK data" in sheet[2][header.index("Notes")].value


async def test_lifecycle_permissions_audit_and_errors(owner_engine: AsyncEngine) -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        mailer = RecordingMailer()
        dispatcher.app.state.mailer = mailer
        owner = AppUser("own")
        org = await make_org(client, owner)
        viewer, analyst = AppUser("view"), AppUser("ana")
        await join(client, mailer, org, owner, viewer, "viewer")
        await join(client, mailer, org, owner, analyst, "analyst")

        # Every member may export; downloads are audited.
        report = await request_report(client, viewer, org, "seller")
        assert report["requested_by_email"] == viewer.email
        await download(client, viewer, org, report["id"])

        # Only the requester or an admin may delete.
        r = await client.delete(f"/api/v1/reports/{report['id']}", headers=analyst.headers(org))
        assert r.status_code == 403
        r = await client.delete(f"/api/v1/reports/{report['id']}", headers=owner.headers(org))
        assert r.status_code == 204
        r = await client.get(f"/api/v1/reports/{report['id']}", headers=owner.headers(org))
        assert r.status_code == 404

        r = await client.post(
            "/api/v1/reports",
            json={
                "report_type": "errors",
                "filters": {"date_from": "2026-12-01", "date_to": "2026-11-01"},
            },
            headers=owner.headers(org),
        )
        assert r.status_code == 422 and r.json()["errors"][0]["loc"][:2] == ["body", "filters"]
        r = await client.post(
            "/api/v1/reports", json={"report_type": "everything"}, headers=owner.headers(org)
        )
        assert r.status_code == 422

        # Not ready yet; and at most N in progress per organization.
        dispatcher.defer_reports = True
        queued = []
        for _ in range(3):
            r = await client.post(
                "/api/v1/reports", json={"report_type": "brand"}, headers=owner.headers(org)
            )
            assert r.status_code == 202
            queued.append(r.json()["id"])
        r = await client.get(f"/api/v1/reports/{queued[0]}/download", headers=owner.headers(org))
        assert r.status_code == 409
        r = await client.post(
            "/api/v1/reports", json={"report_type": "brand"}, headers=owner.headers(org)
        )
        assert r.status_code == 409 and r.json()["code"] == "too_many_reports_running"

        # A lost queue message: the reaper re-dispatches stale queued exports.
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE report_exports SET created_at = now() - interval '1 hour' "
                    "WHERE organization_id = :o"
                ),
                {"o": org},
            )
        dispatcher.defer_reports = False
        state = dispatcher.app.state
        assert (
            await recover_stale_reports(state.session_factory, dispatcher, stale_after_s=600) >= 3
        )
        page = (await client.get("/api/v1/reports", headers=owner.headers(org))).json()
        assert {i["status"] for i in page["items"] if i["id"] in queued} == {"completed"}
        assert page["retention_days"] == 7

        # Expiry: past retention the file is deleted and the download says so.
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE report_exports SET expires_at = now() - interval '1 minute' "
                    "WHERE id = :i"
                ),
                {"i": queued[0]},
            )
        r = await client.get(f"/api/v1/reports/{queued[0]}/download", headers=owner.headers(org))
        assert r.status_code == 410
        assert await expire_reports(state.session_factory, state.storage) >= 1
        expired = (
            await client.get(f"/api/v1/reports/{queued[0]}", headers=owner.headers(org))
        ).json()
        assert expired["status"] == "expired" and expired["file_name"] is None
        with pytest.raises(FileNotFoundError):
            await state.storage.get(f"org/{org}/reports/{queued[0]}.xlsx")

    async with owner_engine.connect() as conn:
        actions = (
            (
                await conn.execute(
                    text(
                        "SELECT action FROM audit_logs WHERE organization_id = :o "
                        "AND action LIKE 'report.%' ORDER BY created_at, id"
                    ),
                    {"o": org},
                )
            )
            .scalars()
            .all()
        )
    assert actions[:3] == ["report.create", "report.download", "report.delete"]


async def test_failures_are_recorded_on_the_export(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args: Any) -> Any:
        raise RuntimeError("builder bug")

    async with scan_api(FakeConnector(), report_max_rows=2) as (client, _):
        owner = AppUser("f")
        org = await make_org(client, owner)
        for i in range(3):
            await create(client, owner, org, f"B0ROWCAP0{i}")
        r = await client.post(
            "/api/v1/reports", json={"report_type": "product"}, headers=owner.headers(org)
        )
        failed = (
            await client.get(f"/api/v1/reports/{r.json()['id']}", headers=owner.headers(org))
        ).json()
        assert failed["status"] == "failed"
        assert "more than 2 rows" in failed["error_message"]

        monkeypatch.setitem(builders.BUILDERS, builders.ReportType.SELLER, boom)
        r = await client.post(
            "/api/v1/reports", json={"report_type": "seller"}, headers=owner.headers(org)
        )
        failed = (
            await client.get(f"/api/v1/reports/{r.json()['id']}", headers=owner.headers(org))
        ).json()
        assert failed["status"] == "failed"
        assert failed["error_message"] == "The report could not be generated (RuntimeError)."
        r = await client.get(f"/api/v1/reports/{failed['id']}/download", headers=owner.headers(org))
        assert r.status_code == 409


async def test_report_functions_are_not_public(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT p.proname, p.prosecdef, "
                    "has_function_privilege('public', p.oid, 'EXECUTE') FROM pg_proc p "
                    "WHERE p.proname IN ('reset_stale_reports', 'expire_report_exports')"
                )
            )
        ).all()
    assert len(rows) == 2 and all(r[1] and not r[2] for r in rows)
