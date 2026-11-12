"""M8 acceptance tests: change history through real scans, seller intelligence, product views."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

from sellerscope.connectors.base import (
    ObservedOffer,
    OfferSnapshot,
    PermanentError,
)
from tests.integration.conftest import AppUser
from tests.integration.test_api_accounts import join
from tests.integration.test_api_scans import FakeConnector, scan_api, setup_org, start

pytestmark = pytest.mark.integration


def offers(
    *sellers: str, prices: dict[str, str] | None = None, buy_box: str | None = None
) -> list[ObservedOffer]:
    prices = prices or {}
    return [
        ObservedOffer(
            seller_id=s,
            seller_name=None,
            listing_price=Decimal(prices.get(s, "100")),
            shipping_price=Decimal(0),
            currency="INR",
            is_buy_box_winner=s == buy_box,
        )
        for s in sellers
    ]


def snap(
    asin: str,
    *sellers: str,
    total: int | None = None,
    truncated: bool = False,
    status: str = "ok",
    **kw: Any,
) -> OfferSnapshot:
    found = offers(*sellers, **kw)
    return OfferSnapshot(
        asin,
        status,
        "fake-source",
        datetime.now(UTC),  # type: ignore[arg-type]
        len(found) if total is None else total,
        found,
        truncated,
        currency="INR",
    )


def gone(asin: str, status: str = "unavailable") -> OfferSnapshot:
    return OfferSnapshot(asin, status, "fake-source", datetime.now(UTC), None, [], None)  # type: ignore[arg-type]


async def scan_once(client: AsyncClient, user: AppUser, org: str, pid: str) -> Any:
    r = await start(client, user, org, [pid])
    assert r.status_code == 202, r.text
    return r.json()


def events(page: dict[str, Any]) -> list[tuple[str, str | None, str | None]]:
    return [
        (e["event_type"], (e["seller"] or {}).get("external_seller_id"), e["confidence"])
        for e in reversed(page["items"])
    ]  # oldest first


async def test_change_history_follows_the_rules_through_real_scans() -> None:
    fake = FakeConnector()
    a = "B0HISTORY1"
    fake.script[a] += [
        snap(a, "S1", "S2", prices={"S1": "100"}),  # 1 baseline
        snap(a, "S1", "S3", prices={"S1": "90"}),  # 2 S3 new, S2 gone, S1 price
        snap(a, "S1", total=30, truncated=True),  # 3 truncated: S3 inconclusive
        PermanentError("access_denied", "Revoked"),  # 4 failed: no events
        gone(a),  # 5 unavailable: one event
        gone(a, "not_found"),  # 6 still no data: no event
        snap(a, "S1", "S3"),  # 7 back: vs last usable (3)
    ]
    async with scan_api(fake) as (client, dispatcher):
        owner, org, ids = await setup_org(client, a)
        pid = ids[a]
        for _ in range(7):
            dispatcher.clock.now = datetime.now(UTC)  # failures are stamped by the worker clock
            await scan_once(client, owner, org, pid)

        history = (
            await client.get(f"/api/v1/products/{pid}/history", headers=owner.headers(org))
        ).json()
        assert events(history) == [
            ("seller_newly_observed", "S3", "high"),
            ("seller_no_longer_observed", "S2", "high"),
            ("price_changed", "S1", "high"),
            ("offer_count_changed", None, "high"),
            ("seller_not_observed_inconclusive", "S3", "low"),
            ("price_changed", "S1", "high"),  # 90 -> 100 in scan 3
            ("scan_unavailable", None, None),
            ("offer_count_changed", None, "high"),
            ("seller_newly_observed", "S3", "medium"),
        ]
        price = [e for e in history["items"] if e["event_type"] == "price_changed"][-1]  # first
        assert (price["old_value"]["price"], price["new_value"]["price"]) == ("100.00", "90.00")

        feed = (
            await client.get(
                "/api/v1/changes",
                params={"event_type": "seller_newly_observed"},
                headers=owner.headers(org),
            )
        ).json()
        assert feed["total"] == 2
        no_inconclusive = (
            await client.get(
                "/api/v1/changes",
                params={"include_inconclusive": "false"},
                headers=owner.headers(org),
            )
        ).json()
        assert all(
            e["event_type"] != "seller_not_observed_inconclusive" for e in no_inconclusive["items"]
        )

        summary = (await client.get("/api/v1/dashboard/summary", headers=owner.headers(org))).json()
        assert summary["new_sellers_detected_7d"] == {"value": 2, "reason": None}

        scans = (
            await client.get(f"/api/v1/products/{pid}/scans", headers=owner.headers(org))
        ).json()
        assert [s["status"] for s in scans["items"]] == [
            "ok",
            "not_found",
            "unavailable",
            "error",
            "ok",
            "ok",
            "ok",
        ]
        trends = (
            await client.get(f"/api/v1/products/{pid}/trends", headers=owner.headers(org))
        ).json()
        assert [t["status"] for t in trends] == ["ok", "ok", "ok", "ok"]  # usable only
        assert [t["total_offer_count"] for t in trends] == [2, 2, 30, 2]
        assert trends[2]["observed_offer_count"] == 1  # metrics stay distinct


async def test_seller_intelligence_presence_and_labels() -> None:
    fake = FakeConnector()
    complete, truncated, current = "B0SELLER01", "B0SELLER02", "B0SELLER03"
    fake.script[complete] += [snap(complete, "X", "Y"), snap(complete, "Y")]
    fake.script[truncated] += [
        snap(truncated, "X", "Y"),
        snap(truncated, "Y", total=40, truncated=True),
    ]
    fake.script[current] += [snap(current, "X", "Z", prices={"X": "250"}, buy_box="X")]
    async with scan_api(fake) as (client, _):
        owner, org, ids = await setup_org(client, complete, truncated, current)
        h = owner.headers(org)
        await scan_once(client, owner, org, ids[complete])
        await scan_once(client, owner, org, ids[truncated])
        await scan_once(client, owner, org, ids[current])
        await scan_once(client, owner, org, ids[complete])
        await scan_once(client, owner, org, ids[truncated])

        sellers = (await client.get("/api/v1/sellers", headers=h)).json()
        by_ext = {s["external_seller_id"]: s for s in sellers["items"]}
        assert set(by_ext) == {"X", "Y", "Z"}
        assert by_ext["Y"]["products_currently_offering"] == 2
        assert by_ext["X"]["products_currently_offering"] == 1
        assert (by_ext["X"]["buy_box_count"], by_ext["X"]["lowest_current_price"]) == (1, "250.00")
        assert by_ext["X"]["display_name"] is None  # never invented

        x = by_ext["X"]["id"]
        detail = (await client.get(f"/api/v1/sellers/{x}", headers=h)).json()
        presence = {p["product"]["external_id"]: p["presence"] for p in detail["products"]}
        assert presence == {
            current: "observed",
            complete: "no_longer_observed",
            truncated: "not_observed_inconclusive",
        }
        observed = next(p for p in detail["products"] if p["presence"] == "observed")
        assert observed["current_offer"]["is_buy_box_winner"] is True
        assert {e["event_type"] for e in detail["recent_changes"]} == {
            "seller_no_longer_observed",
            "seller_not_observed_inconclusive",
        }

        r = await client.patch(
            f"/api/v1/sellers/{x}",
            json={
                "display_name": "  Blue Traders ",
                "tags": ["unauthorized", "unauthorized", "watch"],
                "notes": "Reported to brand registry",
            },
            headers=h,
        )
        assert r.status_code == 200
        assert (r.json()["display_name"], r.json()["display_name_source"], r.json()["tags"]) == (
            "Blue Traders",
            "user",
            ["unauthorized", "watch"],
        )
        tagged = (
            await client.get("/api/v1/sellers", params={"tag": "unauthorized"}, headers=h)
        ).json()
        assert [s["external_seller_id"] for s in tagged["items"]] == ["X"]
        found = (await client.get("/api/v1/sellers", params={"q": "blue"}, headers=h)).json()
        assert found["total"] == 1
        offering = (
            await client.get("/api/v1/sellers", params={"currently_offering": "false"}, headers=h)
        ).json()
        assert offering["total"] == 0  # all three still offer something

        cleared = await client.patch(f"/api/v1/sellers/{x}", json={"display_name": ""}, headers=h)
        assert (cleared.json()["display_name"], cleared.json()["display_name_source"]) == (
            None,
            None,
        )

        cmp = (
            await client.get(
                "/api/v1/sellers/compare",
                params=[("ids", x), ("ids", by_ext["Y"]["id"])],
                headers=h,
            )
        ).json()
        rows = {r["product"]["external_id"]: r["cells"] for r in cmp["rows"]}
        assert set(rows) == {complete, truncated, current}
        assert rows[current][0]["offer"]["landed_price"] == "250.00"
        assert rows[current][1]["offer"] is None  # Y doesn't sell it
        bad = await client.get("/api/v1/sellers/compare", params=[("ids", x)], headers=h)
        assert bad.status_code == 422


async def test_product_offers_snapshot_views() -> None:
    fake = FakeConnector()
    a = "B0OFFERS01"
    fake.script[a] += [
        snap(a, "S1", "S2", prices={"S1": "120", "S2": "99"}, buy_box="S2"),
        snap(a, "S1"),
    ]
    async with scan_api(fake) as (client, _):
        owner, org, ids = await setup_org(client, a)
        h = owner.headers(org)
        empty = (await client.get(f"/api/v1/products/{ids[a]}/offers", headers=h)).json()
        assert empty == {"snapshot": None, "offers": []}
        await scan_once(client, owner, org, ids[a])
        await scan_once(client, owner, org, ids[a])
        latest = (await client.get(f"/api/v1/products/{ids[a]}/offers", headers=h)).json()
        assert [o["seller"]["external_seller_id"] for o in latest["offers"]] == ["S1"]
        scans = (await client.get(f"/api/v1/products/{ids[a]}/scans", headers=h)).json()["items"]
        older = (
            await client.get(
                f"/api/v1/products/{ids[a]}/offers",
                params={"scan_result_id": scans[1]["id"]},
                headers=h,
            )
        ).json()
        assert [o["seller"]["external_seller_id"] for o in older["offers"]] == ["S1", "S2"]
        assert older["offers"][1]["is_buy_box_winner"] is True
        r = await client.get(
            f"/api/v1/products/{ids[a]}/offers",
            params={"scan_result_id": str(uuid.uuid4())},
            headers=h,
        )
        assert r.status_code == 404


async def test_viewer_can_read_but_not_label_sellers() -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, _):
        owner, org, ids = await setup_org(client, "B0LABEL001")
        await scan_once(client, owner, org, ids["B0LABEL001"])
        app = client._transport.app  # type: ignore[attr-defined]
        viewer = AppUser("v")
        from tests.integration.conftest import RecordingMailer

        mailer = RecordingMailer()
        app.state.mailer = mailer
        await join(client, mailer, org, owner, viewer, "viewer")
        sellers = (await client.get("/api/v1/sellers", headers=viewer.headers(org))).json()
        sid = sellers["items"][0]["id"]
        assert (
            await client.get(f"/api/v1/sellers/{sid}", headers=viewer.headers(org))
        ).status_code == 200
        assert (
            await client.patch(
                f"/api/v1/sellers/{sid}", json={"tags": ["x"]}, headers=viewer.headers(org)
            )
        ).status_code == 403
