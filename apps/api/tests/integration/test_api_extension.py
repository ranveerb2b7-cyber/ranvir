"""M12 acceptance tests: PKCE pairing, extension tokens, lookup, Check now, revocation,
and isolation between organizations for token-authenticated routes."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sellerscope.connectors.base import PermanentError
from tests.integration.conftest import AppUser, RecordingMailer
from tests.integration.test_api_accounts import join, make_org
from tests.integration.test_api_intel import gone, scan_once, snap
from tests.integration.test_api_products import create
from tests.integration.test_api_scans import FakeConnector, scan_api

pytestmark = pytest.mark.integration


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


async def start(client: AsyncClient, user: AppUser, org: str, challenge: str) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/extension/pair/start",
        json={"code_challenge": challenge, "device_name": "Chrome on test"},
        headers=user.headers(org),
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def complete(client: AsyncClient, code: str, verifier: str) -> Any:
    return await client.post(
        "/api/v1/extension/pair/complete",
        json={"pairing_code": code, "code_verifier": verifier},
    )


async def pair(client: AsyncClient, user: AppUser, org: str) -> str:
    verifier, challenge = pkce()
    code = (await start(client, user, org, challenge))["pairing_code"]
    r = await complete(client, code, verifier)
    assert r.status_code == 200, r.text
    return str(r.json()["token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def lookup(client: AsyncClient, token: str, ident: str) -> Any:
    return await client.get("/api/v1/extension/lookup", params={"id": ident}, headers=bearer(token))


async def test_pairing_is_one_time_and_bound_to_the_verifier(owner_engine: AsyncEngine) -> None:
    async with scan_api(FakeConnector()) as (client, _):
        owner = AppUser("ext")
        org = await make_org(client, owner, "Ext Co")
        verifier, challenge = pkce()
        started = await start(client, owner, org, challenge)
        code = started["pairing_code"]
        assert len(code) == 9 and code[4] == "-" and started["organization_name"] == "Ext Co"

        # Seeing the code is not enough: the wrong verifier is refused (and doesn't burn it).
        other_verifier, _ = pkce()
        r = await complete(client, code, other_verifier)
        assert r.status_code == 400 and r.json()["code"] == "invalid_pairing_code"

        # Case, spaces and the dash don't matter.
        r = await complete(client, code.replace("-", " ").lower(), verifier)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token"].startswith("sse_") and len(body["token"]) > 40
        assert body["organization"]["name"] == "Ext Co" and body["user_email"] == owner.email
        assert body["scopes"] == ["extension:read", "extension:check"]

        # Used once only.
        r = await complete(client, code, verifier)
        assert r.status_code == 400

        # Expired codes are refused.
        verifier2, challenge2 = pkce()
        code2 = (await start(client, owner, org, challenge2))["pairing_code"]
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE extension_pairings SET expires_at = now() - interval '1 second'")
            )
        r = await complete(client, code2, verifier2)
        assert r.status_code == 400

        # Only hashes are stored.
        async with owner_engine.connect() as conn:
            stored = (
                await conn.execute(
                    text("SELECT token_hash FROM extension_tokens WHERE organization_id = :o"),
                    {"o": org},
                )
            ).scalar_one()
        assert stored == hashlib.sha256(body["token"].encode()).digest()

        r = await client.post(
            "/api/v1/extension/pair/start",
            json={"code_challenge": "too-short"},
            headers=owner.headers(org),
        )
        assert r.status_code == 422


async def test_tokens_authenticate_only_extension_routes() -> None:
    async with scan_api(FakeConnector()) as (client, _):
        owner = AppUser("ext")
        org = await make_org(client, owner, "Ext Co")
        token = await pair(client, owner, org)
        r = await client.get("/api/v1/extension/me", headers=bearer(token))
        assert r.status_code == 200
        assert r.json()["organization"]["name"] == "Ext Co" and r.json()["can_check"] is True

        for headers in ({}, bearer("sse_forged"), owner.headers(org)):
            r = await client.get("/api/v1/extension/me", headers=headers)
            assert r.status_code == 401, headers
            assert r.json()["code"] == "extension_token_invalid"
        # An extension token is not a web session.
        r = await client.get(
            "/api/v1/products", headers={**bearer(token), "X-Organization-Id": org}
        )
        assert r.status_code == 401


async def test_lookup_returns_stored_data_and_never_invents_values() -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, _):
        owner = AppUser("ext")
        org = await make_org(client, owner)
        token = await pair(client, owner, org)
        a = await create(client, owner, org, "B0EXTENS01", product_name="Bottle")
        b = await create(client, owner, org, "B0EXTENS02")
        await create(client, owner, org, "B0EXTENS03")
        fake.script["B0EXTENS01"].append(
            snap("B0EXTENS01", "S1", "S2", prices={"S1": "499", "S2": "520"})
        )
        fake.script["B0EXTENS02"].append(gone("B0EXTENS02", "not_found"))
        await scan_once(client, owner, org, a["id"])
        await scan_once(client, owner, org, b["id"])

        r = await lookup(
            client, token, "https://www.amazon.in/Steel-Bottle/dp/b0extens01/ref=sr_1_1?th=1"
        )
        assert r.status_code == 200, r.text
        found = r.json()
        assert found["tracked"] and found["identifier"] == "B0EXTENS01"
        assert found["product"]["product_name"] == "Bottle"
        latest = found["latest"]
        assert (latest["observed_offer_count"], latest["unique_seller_count"]) == (2, 2)
        assert latest["lowest_observed_price"] == "499.00" and latest["is_mock"] is False
        assert found["dashboard_url"] == f"http://web.test/products/{a['id']}"
        assert found["active_scan"] is None and found["can_check"] is True

        missing = (await lookup(client, token, "B0EXTENS02")).json()
        assert missing["latest"]["status"] == "not_found"
        for key in ("total_offer_count", "observed_offer_count", "unique_seller_count",
                    "lowest_observed_price"):  # fmt: skip
            assert missing["latest"][key] is None, key

        never = (await lookup(client, token, "B0EXTENS03")).json()
        assert never["tracked"] and never["latest"] is None and never["last_attempt"] is None

        other = (await lookup(client, token, "B0NOTMINE1")).json()
        assert other["tracked"] is False and other["product"] is None
        assert other["dashboard_url"] == "http://web.test/products?q=B0NOTMINE1"

        r = await lookup(client, token, "https://www.amazon.in/s?k=bottle")
        assert r.status_code == 422 and r.json()["reason"] == "url_without_asin"
        r = await lookup(client, token, "https://amzn.in/d/abc")
        assert r.status_code == 422 and r.json()["reason"] == "short_link_not_supported"


async def test_check_now_queues_a_normal_scan(owner_engine: AsyncEngine) -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        mailer = RecordingMailer()
        dispatcher.app.state.mailer = mailer
        owner, viewer = AppUser("own"), AppUser("view")
        org = await make_org(client, owner)
        await join(client, mailer, org, owner, viewer, "viewer")
        await create(client, owner, org, "B0EXTENS05")
        token = await pair(client, owner, org)

        dispatcher.defer_scans = True
        r = await client.post(
            "/api/v1/extension/check", json={"id": "B0EXTENS05"}, headers=bearer(token)
        )
        assert r.status_code == 202, r.text
        job = r.json()["job_id"]
        active = (await lookup(client, token, "B0EXTENS05")).json()["active_scan"]
        assert active == {"job_id": job, "status": "queued"}
        r = await client.post(
            "/api/v1/extension/check", json={"id": "B0EXTENS05"}, headers=bearer(token)
        )
        assert r.status_code == 409

        dispatcher.defer_scans = False
        fake.script["B0EXTENS05"].append(PermanentError("asin_rejected", "Rejected."))
        await dispatcher.run_scan_job(uuid.UUID(org), uuid.UUID(job))
        result = (await lookup(client, token, "B0EXTENS05")).json()
        assert result["active_scan"] is None and result["latest"] is None
        assert result["last_attempt"]["status"] == "error"
        jobs = (await client.get("/api/v1/scan-jobs", headers=owner.headers(org))).json()["items"]
        assert jobs[0]["trigger"] == "extension"

        r = await client.post(
            "/api/v1/extension/check", json={"id": "B0NOTMINE1"}, headers=bearer(token)
        )
        assert r.status_code == 404 and r.json()["code"] == "product_not_tracked"

        # A viewer can look up but not start scans.
        viewer_token = await pair(client, viewer, org)
        me = (await client.get("/api/v1/extension/me", headers=bearer(viewer_token))).json()
        assert me["can_check"] is False
        assert (await lookup(client, viewer_token, "B0EXTENS05")).json()["can_check"] is False
        r = await client.post(
            "/api/v1/extension/check", json={"id": "B0EXTENS05"}, headers=bearer(viewer_token)
        )
        assert r.status_code == 403

    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT action, actor_type FROM audit_logs WHERE organization_id = :o "
                    "AND (action LIKE 'extension.%' OR action = 'scan.start') ORDER BY created_at"
                ),
                {"o": org},
            )
        ).all()
    assert ("scan.start", "extension") in rows
    assert ("extension.connect", "user") in rows and ("extension.pair_start", "user") in rows


async def test_revocation_membership_and_expiry(owner_engine: AsyncEngine) -> None:
    async with scan_api(FakeConnector()) as (client, dispatcher):
        mailer = RecordingMailer()
        dispatcher.app.state.mailer = mailer
        owner, analyst = AppUser("own"), AppUser("ana")
        org = await make_org(client, owner)
        await join(client, mailer, org, owner, analyst, "analyst")
        mine = await pair(client, owner, org)
        theirs = await pair(client, analyst, org)

        # Members see their own connections; admins see all.
        own_list = (
            await client.get("/api/v1/extension/tokens", headers=analyst.headers(org))
        ).json()
        assert [t["user_email"] for t in own_list] == [analyst.email]
        all_list = (await client.get("/api/v1/extension/tokens", headers=owner.headers(org))).json()
        assert {t["user_email"] for t in all_list} == {owner.email, analyst.email}
        owner_token = next(t for t in all_list if t["user_email"] == owner.email)
        assert owner_token["last_used_at"] is None  # not used yet
        r = await client.delete(
            f"/api/v1/extension/tokens/{owner_token['id']}", headers=analyst.headers(org)
        )
        assert r.status_code == 404  # can't revoke someone else's

        await client.get("/api/v1/extension/me", headers=bearer(mine))
        used = (await client.get("/api/v1/extension/tokens", headers=owner.headers(org))).json()
        assert next(t for t in used if t["id"] == owner_token["id"])["last_used_at"] is not None

        # Revoked from the web: the extension is disconnected at once.
        r = await client.delete(
            f"/api/v1/extension/tokens/{owner_token['id']}", headers=owner.headers(org)
        )
        assert r.status_code == 204
        assert (await client.get("/api/v1/extension/me", headers=bearer(mine))).status_code == 401

        # Removed from the organization: the token stops working.
        r = await client.delete(f"/api/v1/members/{analyst.id}", headers=owner.headers(org))
        assert r.status_code == 204
        assert (await client.get("/api/v1/extension/me", headers=bearer(theirs))).status_code == 401

        # The extension's own Disconnect, and expiry.
        again = await pair(client, owner, org)
        r = await client.delete("/api/v1/extension/session", headers=bearer(again))
        assert r.status_code == 204
        assert (await client.get("/api/v1/extension/me", headers=bearer(again))).status_code == 401
        later = await pair(client, owner, org)
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE extension_tokens SET expires_at = now() - interval '1 second' "
                     "WHERE organization_id = :o AND revoked_at IS NULL"),
                {"o": org},
            )  # fmt: skip
        assert (await client.get("/api/v1/extension/me", headers=bearer(later))).status_code == 401


async def test_a_token_only_sees_its_own_organization() -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, _):
        alice, bob = AppUser("alice"), AppUser("bob")
        org_a = await make_org(client, alice, "Org A")
        org_b = await make_org(client, bob, "Org B")
        await create(client, bob, org_b, "B0VICTIMEX")
        alice_token = await pair(client, alice, org_a)
        found = (await lookup(client, alice_token, "B0VICTIMEX")).json()
        assert found["tracked"] is False and found["product"] is None
        r = await client.post(
            "/api/v1/extension/check", json={"id": "B0VICTIMEX"}, headers=bearer(alice_token)
        )
        assert r.status_code == 404
        # A pairing code issued in org B can't connect to anything else, and the token it
        # yields belongs to B.
        bob_token = await pair(client, bob, org_b)
        me = (await client.get("/api/v1/extension/me", headers=bearer(bob_token))).json()
        assert me["organization"]["name"] == "Org B"
        # The X-Organization-Id header is ignored for extension tokens.
        r = await client.get(
            "/api/v1/extension/lookup",
            params={"id": "B0VICTIMEX"},
            headers={**bearer(alice_token), "X-Organization-Id": org_b},
        )
        assert r.json()["tracked"] is False


async def test_extension_functions_are_not_public(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT p.proname, p.prosecdef, "
                    "has_function_privilege('public', p.oid, 'EXECUTE') FROM pg_proc p "
                    "WHERE p.proname IN ('redeem_extension_pairing', 'extension_token_principal')"
                )
            )
        ).all()
    assert len(rows) == 2 and all(r[1] and not r[2] for r in rows)


async def test_redeeming_codes_is_rate_limited_per_ip() -> None:
    async with scan_api(FakeConnector(), extension_pair_ip_per_minute=2) as (client, _):
        statuses = [(await complete(client, "AAAA-AAAA", pkce()[0])).status_code for _ in range(4)]
    assert statuses[-1] == 429 and set(statuses) <= {400, 429}
