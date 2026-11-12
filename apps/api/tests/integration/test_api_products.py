"""M4 acceptance tests: product management, listing, dashboard KPIs.

Scan results are inserted directly as labelled test fixtures (data_source="test-fixture");
real scanning arrives in M6/M7.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sellerscope.core.ids import uuid7
from sellerscope.models import ScanHistory, ScanJob, ScanJobItem, ScanResult, SellerProfile
from tests.integration.conftest import AppUser, RecordingMailer, add
from tests.integration.test_api_accounts import join, make_org

pytestmark = pytest.mark.integration

Api = tuple[AsyncClient, RecordingMailer]


async def create(
    client: AsyncClient, user: AppUser, org: str, identifier: str, **fields: Any
) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/products", json={"identifier": identifier, **fields}, headers=user.headers(org)
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def seed_scan(engine: AsyncEngine, org: str, product_id: str, **values: Any) -> str:
    """Inserts a labelled fixture scan result and points the product at it."""
    async with engine.begin() as conn:
        job = await add(
            conn, ScanJob.__table__, organization_id=org, trigger="manual", status="completed"
        )
        item = await add(
            conn,
            ScanJobItem.__table__,
            organization_id=org,
            scan_job_id=job,
            product_id=product_id,
            status="completed",
        )
        result = {
            "organization_id": org,
            "scan_job_item_id": item,
            "product_id": product_id,
            "status": "ok",
            "data_source": "test-fixture",
            "retrieved_at": datetime.now(UTC),
            "observed_offer_count": 0,
        }
        result.update(values)
        rid = await add(conn, ScanResult.__table__, **result)
        await conn.execute(
            text(
                "UPDATE products SET latest_scan_result_id = :r, last_scanned_at = now() "
                "WHERE id = :p"
            ),
            {"r": rid, "p": product_id},
        )
    return str(rid)


# ------------------------------------------------------------------------------ create


async def test_create_by_asin_and_by_url(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    a = await create(
        client, owner, org, " b0chx1w1xy ", product_name=" iPhone 15 ", brand_name="Apple"
    )
    assert a["external_id"] == "B0CHX1W1XY"
    assert a["product_name"] == "iPhone 15"
    assert a["marketplace"] == "amazon_in"
    assert a["identifier_status"] == "format_valid"  # not "verified": no marketplace lookup yet
    assert a["scan_status"] == "not_scanned"
    assert a["latest_scan"] is None
    assert a["monitoring_enabled"] is True

    b = await create(
        client,
        owner,
        org,
        "https://www.amazon.in/Some-Product/dp/B0D1234567/ref=sr_1_1",
        brand_name="",
    )
    assert b["external_id"] == "B0D1234567"
    assert b["brand_name"] is None  # empty brand stored as NULL


@pytest.mark.parametrize(
    ("identifier", "reason"),
    [
        ("B0SHORT", "invalid_format"),
        ("https://amzn.in/d/xyz", "short_link_not_supported"),
        ("https://www.amazon.in/s?k=shoes", "url_without_asin"),
        ("https://example.com/dp/B0CHX1W1XY", "not_an_amazon_url"),
    ],
)
async def test_invalid_identifiers_rejected(api: Api, identifier: str, reason: str) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    r = await client.post(
        "/api/v1/products", json={"identifier": identifier}, headers=owner.headers(org)
    )
    assert r.status_code == 422
    assert r.json()["code"] == "identifier_invalid"
    assert r.json()["reason"] == reason


async def test_duplicates_rejected_per_org_and_readd_after_delete(api: Api) -> None:
    client, _ = api
    alice, bob = AppUser("a"), AppUser("b")
    org_a, org_b = await make_org(client, alice), await make_org(client, bob)
    first = await create(client, alice, org_a, "B0DUPLICAT")
    r = await client.post(
        "/api/v1/products",
        json={"identifier": "https://www.amazon.in/dp/b0duplicat"},
        headers=alice.headers(org_a),
    )
    assert r.status_code == 409
    assert r.json()["code"] == "product_exists"
    assert r.json()["existing_product_id"] == first["id"]

    await create(client, bob, org_b, "B0DUPLICAT")  # other organization: allowed

    assert (
        await client.delete(f"/api/v1/products/{first['id']}", headers=alice.headers(org_a))
    ).status_code == 204
    again = await create(client, alice, org_a, "B0DUPLICAT")
    assert again["id"] != first["id"]


async def test_validate_batch(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    existing = await create(client, owner, org, "B0EXISTING")
    r = await client.post(
        "/api/v1/products/validate",
        json={
            "items": [
                {"identifier": "b0existing"},
                {"identifier": "https://www.amazon.in/dp/B0NEWNEW12"},
                {"identifier": "nope"},
                {"identifier": "https://www.amazon.com/dp/B0USASITE1"},
            ]
        },
        headers=owner.headers(org),
    )
    assert r.status_code == 200
    out = r.json()
    assert out[0]["existing_product_id"] == existing["id"]
    assert (out[1]["valid"], out[1]["normalized"], out[1]["existing_product_id"]) == (
        True,
        "B0NEWNEW12",
        None,
    )
    assert (out[2]["valid"], out[2]["error"]) == (False, "invalid_format")
    assert out[2]["message"]
    assert out[3]["warnings"] == ["non_india_amazon_url"]
    assert out[3]["warning_messages"]


async def test_plan_product_limit_and_missing_subscription(
    api: Api, owner_engine: AsyncEngine
) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    async with owner_engine.begin() as conn:
        code = f"tiny-{uuid7().hex[:8]}"
        await conn.execute(
            text(
                "INSERT INTO plans (id, code, name, max_products, max_scans_per_month, "
                "max_members, min_scan_interval_minutes) VALUES (:i, :c, 'Tiny', 2, 10, 1, 60)"
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
    await create(client, owner, org, "B0LIMIT001")
    await create(client, owner, org, "B0LIMIT002")
    r = await client.post(
        "/api/v1/products", json={"identifier": "B0LIMIT003"}, headers=owner.headers(org)
    )
    assert r.status_code == 402
    assert (r.json()["code"], r.json()["limit"], r.json()["current"]) == (
        "plan_limit_reached",
        2,
        2,
    )

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE subscriptions SET status = 'cancelled' WHERE organization_id = :o"),
            {"o": org},
        )
    r = await client.post(
        "/api/v1/products", json={"identifier": "B0LIMIT004"}, headers=owner.headers(org)
    )
    assert r.status_code == 402 and r.json()["code"] == "subscription_required"


async def test_viewer_is_read_only(api: Api) -> None:
    client, mailer = api
    owner, viewer = AppUser("o"), AppUser("v")
    org = await make_org(client, owner)
    await join(client, mailer, org, owner, viewer, "viewer")
    p = await create(client, owner, org, "B0VIEWONLY")
    h = viewer.headers(org)
    assert (await client.get("/api/v1/products", headers=h)).status_code == 200
    assert (await client.get(f"/api/v1/products/{p['id']}", headers=h)).status_code == 200
    assert (
        await client.post("/api/v1/products", json={"identifier": "B0VIEWNOPE"}, headers=h)
    ).status_code == 403
    assert (
        await client.patch(f"/api/v1/products/{p['id']}", json={"brand_name": "x"}, headers=h)
    ).status_code == 403
    assert (await client.delete(f"/api/v1/products/{p['id']}", headers=h)).status_code == 403
    assert (
        await client.post(
            "/api/v1/products/bulk", json={"ids": [p["id"]], "action": "delete"}, headers=h
        )
    ).status_code == 403


# ------------------------------------------------------------------------------ listing


async def _catalogue(
    client: AsyncClient, engine: AsyncEngine
) -> tuple[AppUser, str, dict[str, str]]:
    owner = AppUser("o")
    org = await make_org(client, owner)
    specs = [
        ("B0AAAAAAA1", "Steel Bottle 1L", "Hydra"),
        ("B0AAAAAAA2", "Steel Bottle 500ml", "Hydra"),
        ("B0BBBBBBB1", "Yoga Mat", "Zen"),
        ("B0CCCCCCC1", "Water 100% pure_test", None),
        ("B0DDDDDDD1", "Lunch Box", "Zen"),
    ]
    ids = {}
    for asin, name, brand in specs:
        ids[asin] = (await create(client, owner, org, asin, product_name=name, brand_name=brand))[
            "id"
        ]
    # A1: 3 sellers, 4 offers. A2: 1 seller. B1: seller ids unknown (count null). C1: unavailable.
    await seed_scan(
        engine,
        org,
        ids["B0AAAAAAA1"],
        total_offer_count=4,
        observed_offer_count=4,
        unique_seller_count=3,
        lowest_observed_price=Decimal("199.00"),
        highest_observed_price=Decimal("349.00"),
        currency="INR",
    )
    await seed_scan(
        engine,
        org,
        ids["B0AAAAAAA2"],
        total_offer_count=1,
        observed_offer_count=1,
        unique_seller_count=1,
        lowest_observed_price=Decimal("150.00"),
        highest_observed_price=Decimal("150.00"),
        currency="INR",
    )
    await seed_scan(
        engine,
        org,
        ids["B0BBBBBBB1"],
        status="partial",
        total_offer_count=7,
        observed_offer_count=2,
        unique_seller_count=None,
        lowest_observed_price=Decimal("999.00"),
        highest_observed_price=Decimal("1099.00"),
        currency="INR",
        limitations=["SELLER_ID_NOT_PROVIDED"],
    )
    await seed_scan(
        engine, org, ids["B0CCCCCCC1"], status="unavailable", limitations=["SOURCE_UNAVAILABLE"]
    )
    return owner, org, ids


async def _list(client: AsyncClient, user: AppUser, org: str, **params: Any) -> dict[str, Any]:
    r = await client.get("/api/v1/products", params=params, headers=user.headers(org))
    assert r.status_code == 200, r.text
    return dict(r.json())


def _asins(page: dict[str, Any]) -> list[str]:
    return [p["external_id"] for p in page["items"]]


async def test_list_filters(api: Api, owner_engine: AsyncEngine) -> None:
    client, _ = api
    owner, org, _ = await _catalogue(client, owner_engine)

    async def listed(**params: Any) -> list[str]:
        page = await _list(client, owner, org, sort="external_id", order="asc", **params)
        return _asins(page)

    assert await listed() == [
        "B0AAAAAAA1",
        "B0AAAAAAA2",
        "B0BBBBBBB1",
        "B0CCCCCCC1",
        "B0DDDDDDD1",
    ]
    assert await listed(q="b0aaa") == ["B0AAAAAAA1", "B0AAAAAAA2"]  # ASIN prefix
    assert await listed(q="bottle") == ["B0AAAAAAA1", "B0AAAAAAA2"]  # name
    assert await listed(q="zen") == ["B0BBBBBBB1", "B0DDDDDDD1"]  # brand
    assert await listed(q="100%") == ["B0CCCCCCC1"]  # LIKE wildcards are literal
    assert await listed(q="_test") == ["B0CCCCCCC1"]
    assert await listed(q="%") == ["B0CCCCCCC1"]
    assert await listed(brand="Zen") == ["B0BBBBBBB1", "B0DDDDDDD1"]
    assert await listed(brand="__none__") == ["B0CCCCCCC1"]
    assert await listed(scan_status="not_scanned") == ["B0DDDDDDD1"]
    assert await listed(scan_status="unavailable") == ["B0CCCCCCC1"]
    # Unknown seller counts (B1) and unscanned/unavailable products match neither side.
    assert await listed(multiple_sellers="true") == ["B0AAAAAAA1"]
    assert await listed(multiple_sellers="false") == ["B0AAAAAAA2"]


async def test_list_sort_puts_unknown_last_and_paginates(
    api: Api, owner_engine: AsyncEngine
) -> None:
    client, _ = api
    owner, org, _ = await _catalogue(client, owner_engine)
    asc = await _list(client, owner, org, sort="lowest_observed_price", order="asc")
    assert _asins(asc)[:3] == ["B0AAAAAAA2", "B0AAAAAAA1", "B0BBBBBBB1"]
    desc = await _list(client, owner, org, sort="lowest_observed_price", order="desc")
    assert _asins(desc)[:3] == ["B0BBBBBBB1", "B0AAAAAAA1", "B0AAAAAAA2"]
    # Unknown prices sort last in both directions.
    assert set(_asins(asc)[3:]) == set(_asins(desc)[3:]) == {"B0CCCCCCC1", "B0DDDDDDD1"}

    p1 = await _list(client, owner, org, sort="external_id", order="asc", page=1, page_size=2)
    p3 = await _list(client, owner, org, sort="external_id", order="asc", page=3, page_size=2)
    assert (p1["total"], p1["page_size"], _asins(p1)) == (5, 2, ["B0AAAAAAA1", "B0AAAAAAA2"])
    assert _asins(p3) == ["B0DDDDDDD1"]
    assert (
        await client.get("/api/v1/products", params={"page_size": 101}, headers=owner.headers(org))
    ).status_code == 422
    assert (
        await client.get(
            "/api/v1/products", params={"sort": "evil; drop"}, headers=owner.headers(org)
        )
    ).status_code == 422


async def test_unknown_metrics_stay_null(api: Api, owner_engine: AsyncEngine) -> None:
    client, _ = api
    owner, org, _ = await _catalogue(client, owner_engine)
    by_asin = {p["external_id"]: p for p in (await _list(client, owner, org))["items"]}
    partial = by_asin["B0BBBBBBB1"]["latest_scan"]
    assert partial["total_offer_count"] == 7
    assert partial["observed_offer_count"] == 2
    assert partial["unique_seller_count"] is None  # not derived from offers
    assert partial["data_source"] == "test-fixture"
    unavailable = by_asin["B0CCCCCCC1"]["latest_scan"]
    assert unavailable["total_offer_count"] is None
    assert unavailable["lowest_observed_price"] is None
    assert unavailable["limitations"] == ["SOURCE_UNAVAILABLE"]
    assert by_asin["B0DDDDDDD1"]["latest_scan"] is None
    assert by_asin["B0DDDDDDD1"]["scan_status"] == "not_scanned"


# ------------------------------------------------------------------------------ edit / bulk


async def test_update_and_delete(api: Api, owner_engine: AsyncEngine) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    p = await create(client, owner, org, "B0EDITME01", product_name="Old", brand_name="Brand")
    url, h = f"/api/v1/products/{p['id']}", owner.headers(org)
    r = await client.patch(
        url,
        json={"product_name": "New", "brand_name": "  ", "monitoring_enabled": False},
        headers=h,
    )
    assert r.status_code == 200
    assert (r.json()["product_name"], r.json()["brand_name"], r.json()["monitoring_enabled"]) == (
        "New",
        None,
        False,
    )
    r = await client.patch(url, json={"external_id": "B0OTHER001"}, headers=h)
    assert r.status_code == 422  # identifiers are immutable
    assert (await client.delete(url, headers=h)).status_code == 204
    assert (await client.get(url, headers=h)).status_code == 404
    assert (await client.delete(url, headers=h)).status_code == 404
    assert (await _list(client, owner, org))["total"] == 0
    async with owner_engine.connect() as conn:
        actions = (
            (
                await conn.execute(
                    text(
                        "SELECT action FROM audit_logs "
                        "WHERE organization_id = :o ORDER BY created_at"
                    ),
                    {"o": org},
                )
            )
            .scalars()
            .all()
        )
    assert actions[-3:] == ["product.create", "product.update", "product.delete"]


async def test_bulk_actions(api: Api) -> None:
    client, _ = api
    alice, bob = AppUser("a"), AppUser("b")
    org, other_org = await make_org(client, alice), await make_org(client, bob)
    ids = [(await create(client, alice, org, f"B0BULK{n:04d}"))["id"] for n in range(3)]
    foreign = (await create(client, bob, other_org, "B0FOREIGN1"))["id"]
    h = alice.headers(org)

    r = await client.post(
        "/api/v1/products/bulk",
        json={
            "ids": [*ids, foreign, str(uuid.uuid4())],
            "action": "set_brand",
            "brand_name": "Acme",
        },
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["affected"] == 3
    assert len(r.json()["not_found"]) == 2 and foreign in r.json()["not_found"]

    r = await client.post(
        "/api/v1/products/bulk", json={"ids": ids[:2], "action": "disable_monitoring"}, headers=h
    )
    assert r.json()["affected"] == 2
    assert _asins(await _list(client, alice, org, monitoring="false")) == [
        "B0BULK0001",
        "B0BULK0000",
    ]

    r = await client.post(
        "/api/v1/products/bulk", json={"ids": ids, "action": "set_brand"}, headers=h
    )
    assert r.status_code == 422

    r = await client.post(
        "/api/v1/products/bulk", json={"ids": [ids[0]], "action": "delete"}, headers=h
    )
    assert r.json()["affected"] == 1
    brands = (await client.get("/api/v1/brands", headers=h)).json()
    assert brands == [{"brand_name": "Acme", "products": 2}]
    # Bob's product untouched.
    assert (await client.get(f"/api/v1/products/{foreign}", headers=bob.headers(other_org))).json()[
        "brand_name"
    ] is None


async def test_brands_include_unbranded(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    await create(client, owner, org, "B0BRAND001", brand_name="Zeta")
    await create(client, owner, org, "B0BRAND002", brand_name="Alpha")
    await create(client, owner, org, "B0BRAND003", brand_name="Alpha")
    await create(client, owner, org, "B0BRAND004")
    r = await client.get("/api/v1/brands", headers=owner.headers(org))
    assert r.json() == [
        {"brand_name": "Alpha", "products": 2},
        {"brand_name": "Zeta", "products": 1},
        {"brand_name": None, "products": 1},
    ]


# ------------------------------------------------------------------------------ dashboard


async def _summary(client: AsyncClient, user: AppUser, org: str) -> dict[str, Any]:
    r = await client.get("/api/v1/dashboard/summary", headers=user.headers(org))
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_dashboard_without_scans_is_not_available_not_zero(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    s = await _summary(client, owner, org)
    assert s["total_products_monitored"] == {"value": 0, "reason": None}  # a real, known zero
    for key in (
        "products_successfully_scanned",
        "products_with_multiple_sellers",
        "total_offers_observed",
        "new_sellers_detected_7d",
        "products_with_unavailable_data",
    ):
        assert s[key] == {"value": None, "reason": "no_scans_yet"}, key
    assert s["last_scan_at"] is None
    assert s["marketplaces"] == [
        {
            "marketplace": "amazon_in",
            "name": "Amazon.in",
            "products": 0,
            "scanned": 0,
            "with_multiple_sellers": {"value": None, "reason": "no_scans_yet"},
            "total_offers_observed": {"value": None, "reason": "no_scans_yet"},
        }
    ]

    await create(client, owner, org, "B0DASH0001")
    s = await _summary(client, owner, org)
    assert s["total_products_monitored"]["value"] == 1
    assert s["products_successfully_scanned"]["value"] is None


async def test_dashboard_with_scans(api: Api, owner_engine: AsyncEngine) -> None:
    client, _ = api
    owner, org, ids = await _catalogue(client, owner_engine)
    async with owner_engine.begin() as conn:
        mkt = (
            await conn.execute(text("SELECT id FROM marketplaces WHERE code='amazon_in'"))
        ).scalar_one()
        seller = await add(
            conn,
            SellerProfile.__table__,
            organization_id=org,
            marketplace_id=mkt,
            external_seller_id="A1FIXTURE",
            first_observed_at=datetime.now(UTC),
            last_observed_at=datetime.now(UTC),
        )
        rid = (
            await conn.execute(
                text("SELECT latest_scan_result_id FROM products WHERE id=:p"),
                {"p": ids["B0AAAAAAA1"]},
            )
        ).scalar_one()
        for when in (datetime.now(UTC), datetime.now(UTC) - timedelta(days=30)):
            await add(
                conn,
                ScanHistory.__table__,
                organization_id=org,
                product_id=ids["B0AAAAAAA1"],
                scan_result_id=rid,
                event_type="seller_newly_observed",
                seller_profile_id=seller,
                confidence="high",
                created_at=when,
            )

    s = await _summary(client, owner, org)
    assert s["total_products_monitored"]["value"] == 5
    assert s["products_successfully_scanned"]["value"] == 3  # ok, ok, partial
    assert s["products_with_multiple_sellers"]["value"] == 1
    # B1 (partial, no seller ids) and C1 (unavailable) have no seller data.
    assert "excludes 2 product" in s["products_with_multiple_sellers"]["reason"]
    assert s["total_offers_observed"]["value"] == 7  # observed: 4 + 1 + 2 (not total 4+1+7)
    assert s["new_sellers_detected_7d"]["value"] == 1  # the 30-day-old event is excluded
    assert s["products_with_unavailable_data"]["value"] == 1
    assert s["last_scan_at"] is not None
    assert s["marketplaces"][0]["scanned"] == 4

    # Disabling monitoring changes "monitored" but not the product count.
    await client.patch(
        f"/api/v1/products/{ids['B0DDDDDDD1']}",
        json={"monitoring_enabled": False},
        headers=owner.headers(org),
    )
    s = await _summary(client, owner, org)
    assert s["total_products_monitored"]["value"] == 4
    assert s["marketplaces"][0]["products"] == 5
