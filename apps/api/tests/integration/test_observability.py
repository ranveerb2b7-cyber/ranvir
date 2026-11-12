"""M14: /metrics (HTTP metrics with bounded labels, scrape-time backlog gauges, auth)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sellerscope.core.observability import init_sentry
from tests.integration.conftest import AppUser, api_settings
from tests.integration.test_api_accounts import make_org
from tests.integration.test_api_products import create
from tests.integration.test_api_scans import FakeConnector, scan_api

pytestmark = pytest.mark.integration


def value(body: str, metric: str) -> float:
    for line in body.splitlines():
        if line.startswith(metric + " ") or line.startswith(metric + "{"):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"{metric} not found")


async def test_metrics_report_requests_and_backlogs(owner_engine: AsyncEngine) -> None:
    async with scan_api(FakeConnector()) as (client, dispatcher):
        owner = AppUser("obs")
        org = await make_org(client, owner)
        product = await create(client, owner, org, "B0METRICS1")
        await client.get(f"/api/v1/products/{product['id']}", headers=owner.headers(org))
        dispatcher.defer_scans = True  # leaves a pending scan item behind
        r = await client.post(
            "/api/v1/scan-jobs", json={"product_ids": [product["id"]]}, headers=owner.headers(org)
        )
        assert r.status_code == 202

        r = await client.get("/metrics")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
        body = r.text
        # Route TEMPLATES, never ids, keep label cardinality bounded.
        assert (
            'sellerscope_http_requests_total{method="GET",'
            'route="/api/v1/products/{product_id}",status="200"}' in body
        )
        assert product["id"] not in body
        assert "/metrics" not in body.split("sellerscope_http_requests_total")[1].split("\n#")[0]
        assert value(body, "sellerscope_scan_items_pending") >= 1
        assert 'sellerscope_queue_length{queue="scans.amazon"}' in body
        assert "sellerscope_metrics_scrape_errors_total{" not in body  # no failed collection


async def test_metrics_require_the_token_when_configured() -> None:
    token = "t" * 40
    async with scan_api(FakeConnector(), metrics_token=token) as (client, _):
        assert (await client.get("/metrics")).status_code == 401
        wrong = {"Authorization": "Bearer " + "x" * 40}
        assert (await client.get("/metrics", headers=wrong)).status_code == 401
        ok = await client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200 and "sellerscope_http_requests_total" in ok.text


async def test_ops_metrics_function_is_counts_only_and_not_public(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        definer, public = (
            await conn.execute(
                text(
                    "SELECT p.prosecdef, has_function_privilege('public', p.oid, 'EXECUTE') "
                    "FROM pg_proc p WHERE p.proname = 'ops_metrics'"
                )
            )
        ).one()
        columns = (await conn.execute(text("SELECT * FROM ops_metrics()"))).keys()
    assert definer and not public
    assert not any("id" in c.split("_") or "name" in c for c in columns)


def test_sentry_is_off_without_a_dsn() -> None:
    assert init_sentry(api_settings(), component="api") is False


async def test_metrics_endpoint_is_not_in_the_public_api_schema(
    api: tuple[AsyncClient, object],
) -> None:
    client, _ = api
    schema = (await client.get("/api/v1/openapi.json")).json()
    assert "/metrics" not in schema["paths"]
