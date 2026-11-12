"""M6 acceptance tests: scan jobs, duplicate guard, retries/backoff, failures, cancellation,
quota, stale-work recovery, scheduling."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sellerscope.connectors.base import (
    ConnectorCapabilities,
    ConnectorContext,
    ConnectorError,
    ObservedOffer,
    OfferSnapshot,
    PermanentError,
    RateLimitedError,
    TransientError,
)
from sellerscope.core.ids import uuid7
from sellerscope.main import create_app
from sellerscope.scanning.maintenance import recover_stale_work, schedule_due_scans
from tests.integration.conftest import AppUser, InlineDispatcher, RecordingMailer, api_settings
from tests.integration.test_api_accounts import make_org
from tests.integration.test_api_products import create

pytestmark = pytest.mark.integration

Api = tuple[AsyncClient, RecordingMailer]


# ------------------------------------------------------------------------------ test doubles


class FakeConnector:
    """Scripted connector: per ASIN, a queue of responses (snapshot or error)."""

    code = "fake"
    capabilities = ConnectorCapabilities(
        total_offer_count=True,
        offer_list=True,
        offer_list_max=20,
        seller_id=True,
        seller_name=False,
        price=True,
        fulfilment=True,
        batch_size=10,
        requests_per_second=1000,
        burst=1000,
    )

    def __init__(self) -> None:
        self.script: dict[str, deque[OfferSnapshot | ConnectorError]] = defaultdict(deque)
        self.calls: list[list[str]] = []

    def rate_limit_key(self, ctx: ConnectorContext) -> str:
        return f"fake:{ctx.organization_id}:{uuid.uuid4()}"  # effectively unlimited

    async def fetch_offers(
        self, ctx: ConnectorContext, external_ids: list[str]
    ) -> dict[str, OfferSnapshot | ConnectorError]:
        self.calls.append(external_ids)
        out: dict[str, OfferSnapshot | ConnectorError] = {}
        for a in external_ids:
            item = self.script[a].popleft() if self.script[a] else ok(a)
            if isinstance(item, OfferSnapshot):
                item.retrieved_at = datetime.now(UTC)  # stamped at fetch time, like a real source
            out[a] = item
        return out


def ok(
    asin: str, sellers: tuple[str, ...] = ("S1", "S2"), total: int | None = None
) -> OfferSnapshot:
    offers = [
        ObservedOffer(
            seller_id=s,
            seller_name=None,
            listing_price=Decimal(100 + i * 10),
            shipping_price=Decimal(0),
            currency="INR",
        )
        for i, s in enumerate(sellers)
    ]
    return OfferSnapshot(
        asin,
        "ok",
        "fake-source",
        datetime.now(UTC),
        total if total is not None else len(offers),
        offers,
        False,
        currency="INR",
    )


class FakeRegistry:
    def __init__(self, connector: FakeConnector) -> None:
        self.connector = connector
        self.mock_enabled = False

    async def resolve(
        self, session: Any, organization_id: uuid.UUID, marketplace_code: str
    ) -> tuple[FakeConnector, ConnectorContext]:
        return self.connector, ConnectorContext(organization_id, marketplace_code, None, None)


@asynccontextmanager
async def scan_api(
    fake: FakeConnector | None = None, **settings: Any
) -> AsyncIterator[tuple[AsyncClient, InlineDispatcher]]:
    app = create_app(api_settings(**settings))
    dispatcher = InlineDispatcher(app)
    app.state.task_dispatcher = dispatcher
    if fake is not None:
        app.state.connector_registry = FakeRegistry(fake)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        yield client, dispatcher


async def setup_org(client: AsyncClient, *asins: str) -> tuple[AppUser, str, dict[str, str]]:
    owner = AppUser("scan")
    org = await make_org(client, owner)
    ids = {a: (await create(client, owner, org, a))["id"] for a in asins}
    return owner, org, ids


async def start(client: AsyncClient, user: AppUser, org: str, ids: list[str]) -> Any:
    return await client.post(
        "/api/v1/scan-jobs", json={"product_ids": ids}, headers=user.headers(org)
    )


async def job_state(client: AsyncClient, user: AppUser, org: str, job: str) -> dict[str, Any]:
    j = (await client.get(f"/api/v1/scan-jobs/{job}", headers=user.headers(org))).json()
    items = (await client.get(f"/api/v1/scan-jobs/{job}/items", headers=user.headers(org))).json()
    j["items"] = {i["external_id"]: i for i in items["items"]}
    return dict(j)


def mock_asin(scenario: int, prefix: str) -> str:
    for i in range(100_000):
        asin = f"{prefix}{i:05d}"[:10]
        if hashlib.sha256(asin.encode()).digest()[0] % 10 == scenario:
            return asin
    raise AssertionError


# ------------------------------------------------------------------------------ happy path (MOCK)


async def test_mock_scan_writes_labelled_snapshots(owner_engine: AsyncEngine) -> None:
    a, truncated, missing = mock_asin(4, "B0MOKA"), mock_asin(3, "B0MOKB"), mock_asin(0, "B0MOKC")
    async with scan_api() as (client, _):
        owner, org, ids = await setup_org(client, a, truncated, missing)
        r = await start(client, owner, org, list(ids.values()))
        assert r.status_code == 202, r.text
        job = await job_state(client, owner, org, r.json()["id"])
        assert job["status"] == "completed_with_errors"  # the not-found product is unavailable
        assert (job["completed_items"], job["unavailable_items"], job["failed_items"]) == (2, 1, 0)
        assert job["items"][truncated]["status"] == "partial"
        assert job["items"][missing]["status"] == "unavailable"

        products = {
            p["external_id"]: p
            for p in (await client.get("/api/v1/products", headers=owner.headers(org))).json()[
                "items"
            ]
        }
        scan = products[truncated]["latest_scan"]
        assert scan["data_source"] == "MOCK"
        assert "MOCK_DATA" in scan["limitations"]
        assert "OFFER_LIST_TRUNCATED" in scan["limitations"]
        assert scan["total_offer_count"] > scan["observed_offer_count"] == 20
        assert products[missing]["scan_status"] == "not_found"
        assert products[missing]["latest_scan"]["total_offer_count"] is None

    async with owner_engine.connect() as conn:
        offers = (
            await conn.execute(
                text("SELECT count(*) FROM product_offers WHERE organization_id = :o"), {"o": org}
            )
        ).scalar_one()
        sellers = (
            await conn.execute(
                text(
                    "SELECT count(*), bool_and(external_seller_id LIKE 'MOCK%'), "
                    "bool_and(display_name IS NULL) "
                    "FROM seller_profiles WHERE organization_id = :o"
                ),
                {"o": org},
            )
        ).one()
    assert offers >= 21
    assert sellers[0] > 0 and sellers[1] is True and sellers[2] is True


async def test_scan_all_monitored_skips_unmonitored() -> None:
    async with scan_api(FakeConnector()) as (client, _):
        owner, org, ids = await setup_org(client, "B0ALLMON01", "B0ALLMON02")
        await client.patch(
            f"/api/v1/products/{ids['B0ALLMON02']}",
            json={"monitoring_enabled": False},
            headers=owner.headers(org),
        )
        r = await client.post(
            "/api/v1/scan-jobs", json={"all_monitored": True}, headers=owner.headers(org)
        )
        assert r.json()["total_items"] == 1
        bad = await client.post("/api/v1/scan-jobs", json={}, headers=owner.headers(org))
        assert bad.status_code == 422


# ------------------------------------------------------------------------------ duplicate guard


async def test_products_already_scanning_are_skipped_or_rejected() -> None:
    async with scan_api(FakeConnector()) as (client, dispatcher):
        dispatcher.defer_scans = True  # leave items pending, like a busy worker queue
        owner, org, ids = await setup_org(client, "B0DUPSCAN1", "B0DUPSCAN2")
        p, q = ids["B0DUPSCAN1"], ids["B0DUPSCAN2"]
        assert (await start(client, owner, org, [p])).status_code == 202
        second = await start(client, owner, org, [p, q])
        assert second.status_code == 202
        assert (second.json()["total_items"], second.json()["already_running"]) == (1, [p])
        third = await start(client, owner, org, [p, q])
        assert third.status_code == 409
        assert third.json()["code"] == "scan_already_running"


async def test_concurrent_requests_never_scan_a_product_twice(owner_engine: AsyncEngine) -> None:
    async with scan_api(FakeConnector()) as (client, dispatcher):
        dispatcher.defer_scans = True
        owner, org, ids = await setup_org(client, "B0RACESCN1")
        results = await asyncio.gather(
            *(start(client, owner, org, [ids["B0RACESCN1"]]) for _ in range(5))
        )
        assert sorted(r.status_code for r in results) == [202, 409, 409, 409, 409]
    async with owner_engine.connect() as conn:
        active = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM scan_job_items "
                    "WHERE product_id = :p AND status = 'pending'"
                ),
                {"p": ids["B0RACESCN1"]},
            )
        ).scalar_one()
    assert active == 1


# ------------------------------------------------------------------------------ retries/backoff


async def test_rate_limited_items_back_off_and_eventually_succeed() -> None:
    fake = FakeConnector()
    fake.script["B0RETRY001"] += [
        RateLimitedError(retry_after_s=30),
        TransientError("timeout", "Timed out"),
    ]
    async with scan_api(fake) as (client, dispatcher):
        owner, org, ids = await setup_org(client, "B0RETRY001")
        job_id = (await start(client, owner, org, [ids["B0RETRY001"]])).json()["id"]

        state = await job_state(client, owner, org, job_id)
        item = state["items"]["B0RETRY001"]
        assert (state["status"], item["status"], item["attempt_count"]) == ("running", "pending", 1)
        assert item["last_error_code"] == "rate_limited"
        wait = dispatcher.scan_delays[-1]
        assert wait is not None and wait >= 30  # Retry-After honoured

        dispatcher.clock.advance(5)  # too early: nothing to do yet
        await dispatcher.run_scan_job(uuid.UUID(org), uuid.UUID(job_id))
        assert len(fake.calls) == 1

        dispatcher.clock.advance(wait)
        await dispatcher.run_scan_job(uuid.UUID(org), uuid.UUID(job_id))
        item = (await job_state(client, owner, org, job_id))["items"]["B0RETRY001"]
        assert (item["status"], item["attempt_count"], item["last_error_code"]) == (
            "pending",
            2,
            "timeout",
        )

        dispatcher.clock.advance(dispatcher.scan_delays[-1] or 0)
        await dispatcher.run_scan_job(uuid.UUID(org), uuid.UUID(job_id))
        state = await job_state(client, owner, org, job_id)
        assert state["status"] == "completed"
        item = state["items"]["B0RETRY001"]
        assert (item["status"], item["attempt_count"], item["last_error_code"]) == (
            "completed",
            3,
            None,
        )
        assert item["result"]["unique_seller_count"] == 2
        assert len(fake.calls) == 3


async def test_gives_up_after_max_attempts_and_keeps_previous_data() -> None:
    fake = FakeConnector()
    async with scan_api(fake, scan_max_attempts=3) as (client, dispatcher):
        owner, org, ids = await setup_org(client, "B0GIVEUP01")
        pid = ids["B0GIVEUP01"]
        await start(client, owner, org, [pid])  # first scan succeeds
        before = (await client.get(f"/api/v1/products/{pid}", headers=owner.headers(org))).json()
        assert before["scan_status"] == "ok"

        fake.script["B0GIVEUP01"] += [TransientError("timeout", "Timed out")] * 3
        job_id = (await start(client, owner, org, [pid])).json()["id"]
        for _ in range(3):
            dispatcher.clock.advance(400)
            await dispatcher.run_scan_job(uuid.UUID(org), uuid.UUID(job_id))
        state = await job_state(client, owner, org, job_id)
        item = state["items"]["B0GIVEUP01"]
        assert (state["status"], item["status"], item["attempt_count"]) == ("failed", "failed", 3)
        assert "gave up after 3 attempts" in item["last_error_message"]
        assert item["result"]["status"] == "error"  # failure kept in history

        after = (await client.get(f"/api/v1/products/{pid}", headers=owner.headers(org))).json()
        assert after["latest_scan"] == before["latest_scan"]  # failure doesn't overwrite data


async def test_permanent_errors_fail_immediately_without_retry() -> None:
    fake = FakeConnector()
    fake.script["B0PERM0001"].append(PermanentError("access_denied", "Authorization revoked."))
    async with scan_api(fake) as (client, _):
        owner, org, ids = await setup_org(client, "B0PERM0001", "B0PERMOK01")
        job_id = (await start(client, owner, org, list(ids.values()))).json()["id"]
        state = await job_state(client, owner, org, job_id)
        assert state["status"] == "completed_with_errors"
        failed = state["items"]["B0PERM0001"]
        assert (failed["status"], failed["attempt_count"], failed["last_error_code"]) == (
            "failed",
            1,
            "access_denied",
        )
        assert failed["last_error_message"] == "Authorization revoked."
        assert state["items"]["B0PERMOK01"]["status"] == "completed"

        retry = await client.post(
            f"/api/v1/scan-jobs/{job_id}/retry-failed", headers=owner.headers(org)
        )
        assert retry.status_code == 202
        assert retry.json()["total_items"] == 1
        new_state = await job_state(client, owner, org, retry.json()["id"])
        assert list(new_state["items"]) == ["B0PERM0001"]
        assert new_state["status"] == "completed"
        again = await client.post(
            f"/api/v1/scan-jobs/{retry.json()['id']}/retry-failed", headers=owner.headers(org)
        )
        assert again.status_code == 409 and again.json()["code"] == "nothing_to_retry"


async def test_whole_request_errors_and_connector_crashes_are_recorded() -> None:
    class Exploding(FakeConnector):
        async def fetch_offers(self, ctx: ConnectorContext, ids: list[str]) -> Any:
            raise RuntimeError("boom")

    async with scan_api(Exploding(), scan_max_attempts=1) as (client, _):
        owner, org, ids = await setup_org(client, "B0BOOM0001")
        job_id = (await start(client, owner, org, list(ids.values()))).json()["id"]
        item = (await job_state(client, owner, org, job_id))["items"]["B0BOOM0001"]
        assert (item["status"], item["last_error_code"]) == ("failed", "unexpected_error")


# ------------------------------------------------------------------------------ cancellation


async def test_cancel_stops_pending_items_but_lets_in_flight_finish(
    owner_engine: AsyncEngine,
) -> None:
    async with scan_api(FakeConnector()) as (client, dispatcher):
        dispatcher.defer_scans = True
        owner, org, ids = await setup_org(client, "B0CANCEL01", "B0CANCEL02", "B0CANCEL03")
        job_id = (await start(client, owner, org, list(ids.values()))).json()["id"]
        async with owner_engine.begin() as conn:  # one item is being fetched by a worker
            await conn.execute(
                text(
                    "UPDATE scan_job_items SET status='processing', started_at=now() "
                    "WHERE scan_job_id = :j AND product_id = :p"
                ),
                {"j": job_id, "p": ids["B0CANCEL01"]},
            )

        r = await client.post(f"/api/v1/scan-jobs/{job_id}/cancel", headers=owner.headers(org))
        assert r.status_code == 200
        state = await job_state(client, owner, org, job_id)
        assert state["status"] == "queued"  # still waiting for the in-flight item
        assert state["cancelled_items"] == 2
        assert state["items"]["B0CANCEL01"]["status"] == "processing"

        async with owner_engine.begin() as conn:  # the worker finishes that item
            await conn.execute(
                text(
                    "UPDATE scan_job_items SET status='completed', finished_at=now() "
                    "WHERE scan_job_id = :j AND product_id = :p"
                ),
                {"j": job_id, "p": ids["B0CANCEL01"]},
            )
        dispatcher.defer_scans = False
        await dispatcher.run_scan_job(uuid.UUID(org), uuid.UUID(job_id))
        state = await job_state(client, owner, org, job_id)
        assert (state["status"], state["completed_items"], state["cancelled_items"]) == (
            "cancelled",
            1,
            2,
        )
        assert (
            await client.post(f"/api/v1/scan-jobs/{job_id}/cancel", headers=owner.headers(org))
        ).status_code == 409


# ------------------------------------------------------------------------------ quota & access


async def test_monthly_scan_quota(owner_engine: AsyncEngine) -> None:
    async with scan_api(FakeConnector()) as (client, _):
        owner, org, ids = await setup_org(client, "B0QUOTA001", "B0QUOTA002", "B0QUOTA003")
        async with owner_engine.begin() as conn:
            code = f"q-{uuid7().hex[:8]}"
            await conn.execute(
                text(
                    "INSERT INTO plans (id, code, name, max_products, max_scans_per_month, "
                    "max_members, min_scan_interval_minutes) VALUES (:i, :c, 'Q', 10, 2, 1, 60)"
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
        quota = (await client.get("/api/v1/scan-jobs/quota", headers=owner.headers(org))).json()
        assert (quota["limit"], quota["used"], quota["remaining"]) == (2, 0, 2)
        r = await start(client, owner, org, list(ids.values()))
        assert r.status_code == 402
        assert (r.json()["code"], r.json()["limit"], r.json()["requested"]) == (
            "scan_quota_exceeded",
            2,
            3,
        )
        assert (await start(client, owner, org, list(ids.values())[:2])).status_code == 202
        assert (await start(client, owner, org, list(ids.values())[2:])).status_code == 402


async def test_without_a_data_connection_scans_are_refused() -> None:
    async with scan_api(enable_mock_connector=False) as (client, _):
        owner, org, ids = await setup_org(client, "B0NOCONN01")
        r = await start(client, owner, org, list(ids.values()))
        assert r.status_code == 409
        assert r.json()["code"] == "connector_unavailable"
        assert "Amazon seller account" in r.json()["detail"]
        assert (await client.get("/api/v1/meta")).json()["mock_connector_enabled"] is False


async def test_meta_reports_mock_mode(api: Api) -> None:
    client, _ = api
    meta = (await client.get("/api/v1/meta")).json()
    assert meta["mock_connector_enabled"] is True
    assert meta["environment"] == "test"


async def test_viewer_cannot_start_or_cancel_scans(api: Api) -> None:
    from tests.integration.test_api_accounts import join

    client, mailer = api
    owner, viewer = AppUser("o"), AppUser("v")
    org = await make_org(client, owner)
    await join(client, mailer, org, owner, viewer, "viewer")
    pid = (await create(client, owner, org, "B0VIEWSCAN"))["id"]
    assert (await start(client, viewer, org, [pid])).status_code == 403
    job = (await start(client, owner, org, [pid])).json()["id"]
    assert (
        await client.get(f"/api/v1/scan-jobs/{job}", headers=viewer.headers(org))
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/scan-jobs/{job}/cancel", headers=viewer.headers(org))
    ).status_code == 403


# ------------------------------------------------------------------------------ maintenance


class RecordingDispatcher:
    def __init__(self) -> None:
        self.scans: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.parses: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def run_scan_job(self, org: uuid.UUID, job: uuid.UUID, countdown_s: float = 0) -> None:
        self.scans.append((org, job))

    async def parse_upload(self, org: uuid.UUID, batch: uuid.UUID) -> None:
        self.parses.append((org, batch))


async def test_stale_work_is_recovered(owner_engine: AsyncEngine) -> None:
    async with scan_api(FakeConnector()) as (client, dispatcher):
        dispatcher.defer_scans = True
        owner, org, ids = await setup_org(client, "B0STALE001")
        job_id = (await start(client, owner, org, list(ids.values()))).json()["id"]
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE scan_job_items SET status='processing', attempt_count=1, "
                    "started_at = now() - interval '1 hour' WHERE scan_job_id = :j"
                ),
                {"j": job_id},
            )
        batch = (
            await client.post(
                "/api/v1/uploads",
                files={"file": ("s.csv", b"ASIN\n", "text/csv")},
                headers=owner.headers(org),
            )
        ).json()["id"]
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE product_batches SET status='parsing' WHERE id=:b"), {"b": batch}
            )

        recorder = RecordingDispatcher()
        # -1s: everything counts as stale (updated_at can't be back-dated past the trigger).
        await recover_stale_work(
            client._transport.app.state.session_factory,  # type: ignore[attr-defined]
            recorder,
            stale_after_s=-1,
        )
        assert (uuid.UUID(org), uuid.UUID(job_id)) in recorder.scans
        assert (uuid.UUID(org), uuid.UUID(batch)) in recorder.parses
        item = (await job_state(client, owner, org, job_id))["items"]["B0STALE001"]
        assert (item["status"], item["attempt_count"], item["last_error_code"]) == (
            "pending",
            0,
            "worker_lost",
        )
        status = (await client.get(f"/api/v1/uploads/{batch}", headers=owner.headers(org))).json()
        assert status["status"] == "uploaded"


async def test_scheduler_picks_only_due_products(owner_engine: AsyncEngine) -> None:
    async with scan_api(FakeConnector()) as (client, _):
        owner, org, ids = await setup_org(client, "B0SCHED001", "B0SCHED002", "B0SCHED003")
        await client.patch(
            f"/api/v1/products/{ids['B0SCHED002']}",
            json={"monitoring_enabled": False},
            headers=owner.headers(org),
        )
        await start(client, owner, org, [ids["B0SCHED003"]])  # scanned just now: not due

        app = client._transport.app  # type: ignore[attr-defined]
        recorder = RecordingDispatcher()
        await schedule_due_scans(
            app.state.session_factory,
            app.state.connector_registry,
            recorder,
            now=datetime.now(UTC),
            batch=10_000,
        )
        ours = [job for o, job in recorder.scans if o == uuid.UUID(org)]
        assert len(ours) == 1
        state = await job_state(client, owner, org, str(ours[0]))
        assert state["trigger"] == "scheduled"
        assert list(state["items"]) == ["B0SCHED001"]

        recorder2 = RecordingDispatcher()  # already pending: not scheduled twice
        await schedule_due_scans(
            app.state.session_factory,
            app.state.connector_registry,
            recorder2,
            now=datetime.now(UTC),
            batch=10_000,
        )
        assert not [job for o, job in recorder2.scans if o == uuid.UUID(org)]


async def test_maintenance_functions_are_not_public(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT p.proname, p.prosecdef, "
                    "has_function_privilege('public', p.oid, 'EXECUTE') "
                    "FROM pg_proc p WHERE p.proname IN "
                    "('due_scan_products', 'reset_stale_scan_items', 'reset_stale_uploads', "
                    "'alert_delivery_orgs')"
                )
            )
        ).all()
    assert {r[0] for r in rows} == {
        "due_scan_products",
        "reset_stale_scan_items",
        "reset_stale_uploads",
        "alert_delivery_orgs",
    }
    assert all(r[1] and not r[2] for r in rows)  # SECURITY DEFINER, not executable by PUBLIC


async def test_token_bucket_enforces_rate_across_callers(api: Api) -> None:
    client, _ = api
    bucket = client._transport.app.state.token_bucket  # type: ignore[attr-defined]
    key, now = f"test:{uuid.uuid4()}", 1_000.0
    waits = [await bucket.acquire(key, rate=2, burst=3, now_s=now) for _ in range(4)]
    assert waits[:3] == [0, 0, 0]  # burst
    assert waits[3] == pytest.approx(0.5)  # then 2 per second
    assert await bucket.acquire(key, rate=2, burst=3, now_s=now + 0.5) == 0
