"""M10 acceptance tests: alert rules through real scans, email digests, failures, API."""

from __future__ import annotations

import uuid
from email.message import EmailMessage
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sellerscope.alerts.delivery import deliver_all_due
from sellerscope.connectors.base import PermanentError
from tests.integration.conftest import AppUser, InlineDispatcher, RecordingMailer
from tests.integration.test_api_accounts import join
from tests.integration.test_api_intel import scan_once, snap
from tests.integration.test_api_scans import FakeConnector, scan_api, setup_org

pytestmark = pytest.mark.integration

A = "B0ALERT001"


class FailingMailer(RecordingMailer):
    def __init__(self) -> None:
        super().__init__()
        self.failing = True

    async def send(self, message: EmailMessage) -> None:
        if self.failing:
            raise ConnectionRefusedError("SMTP server refused the connection")
        await super().send(message)


def mailer_of(
    dispatcher: InlineDispatcher, mailer: RecordingMailer | None = None
) -> RecordingMailer:
    dispatcher.app.state.mailer = mailer or RecordingMailer()
    return dispatcher.app.state.mailer  # type: ignore[no-any-return]


async def add_rule(client: AsyncClient, user: AppUser, org: str, **body: Any) -> dict[str, Any]:
    r = await client.post("/api/v1/alert-rules", json=body, headers=user.headers(org))
    assert r.status_code == 201, r.text
    return dict(r.json())


async def alerts(client: AsyncClient, user: AppUser, org: str, **params: Any) -> list[Any]:
    r = await client.get("/api/v1/alerts", params=params, headers=user.headers(org))
    assert r.status_code == 200, r.text
    return list(r.json()["items"])


def by_rule(items: list[Any]) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for a in reversed(items):  # oldest first
        out.setdefault(a["rule_name"], []).append((a["status"], a["title"]))
    return out


async def test_alerts_follow_the_rules_through_real_scans() -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        mailer = mailer_of(dispatcher)
        owner, org, ids = await setup_org(client, A)
        analyst = AppUser("analyst")
        await join(client, mailer, org, owner, analyst, "analyst")
        mailer.sent.clear()
        pid = ids[A]
        await add_rule(
            client, owner, org, name="New seller", rule_type="new_seller",
            channels=["email"], recipient_user_ids=[str(owner.id), str(analyst.id)],
        )  # fmt: skip
        await add_rule(client, owner, org, name="Gone", rule_type="seller_gone")
        await add_rule(
            client, owner, org, name="Gone maybe", rule_type="seller_gone",
            params={"include_inconclusive": True},
        )  # fmt: skip
        await add_rule(
            client, owner, org, name="Crowded", rule_type="seller_count_above",
            params={"threshold": 2},
        )  # fmt: skip
        await add_rule(
            client, owner, org, name="Cheap", rule_type="price_below",
            params={"threshold": "90", "exclude_seller_tags": ["authorized"]},
        )  # fmt: skip
        await add_rule(client, owner, org, name="Failed", rule_type="scan_failed")
        await add_rule(
            client, owner, org, name="Other product only", rule_type="new_seller",
            scope={"product_ids": [str((await setup_extra(client, owner, org))["id"])]},
        )  # fmt: skip

        # 1. Baseline: no change events; 2 sellers is not above the limit of 2.
        fake.script[A].append(snap(A, "S1", "S2"))
        await scan_once(client, owner, org, pid)
        assert await alerts(client, owner, org) == []

        # 2. A new, cheap seller appears.
        fake.script[A].append(snap(A, "S1", "S2", "S3", prices={"S3": "80"}))
        await scan_once(client, owner, org, pid)
        assert by_rule(await alerts(client, owner, org)) == {
            "New seller": [("open", "New seller on B0ALERT001: S3")],
            "Crowded": [("open", "B0ALERT001 has 3 sellers (limit 2)")],
            "Cheap": [("open", "B0ALERT001 offered at ₹80.00, below ₹90.00")],
        }
        # One email per recipient, only for the rule that has email turned on.
        assert sorted(m["To"] for m in mailer.sent) == sorted([owner.email, analyst.email])
        assert all(
            m["Subject"] == "[SellerScope] New seller on B0ALERT001: S3" for m in mailer.sent
        )
        body = mailer.sent[0].get_content()
        assert "http://web.test/alerts?alert=" in body and "alerts?tab=rules" in body
        new_seller = await alerts(client, owner, org, severity="warning")
        emailed = next(a for a in new_seller if a["rule_name"] == "New seller")
        assert emailed["delivered_channels"] == ["in_app", "email"]
        assert {d["status"] for d in emailed["deliveries"]} == {"sent"}

        # 3. Cut-off list without S3: only the opted-in rule alerts; nothing resolves.
        fake.script[A].append(snap(A, "S1", "S2", total=5, truncated=True))
        await scan_once(client, owner, org, pid)
        current = by_rule(await alerts(client, owner, org))
        assert "Gone" not in current
        assert current["Gone maybe"] == [("open", "S3 not seen on B0ALERT001 (inconclusive)")]
        assert current["Crowded"] == [("open", "B0ALERT001 has 3 sellers (limit 2)")]
        assert current["Cheap"][0][0] == "open"

        # 4. A failed scan: alerts only that it failed; open alerts stay as they are.
        fake.script[A].append(PermanentError("asin_rejected", "The source rejected the product."))
        await scan_once(client, owner, org, pid)
        current = by_rule(await alerts(client, owner, org))
        assert current["Failed"] == [("open", "Scan failed for B0ALERT001")]
        assert current["Crowded"][0][0] == "open"

        # 5. Complete list with only S1: S2 is gone (proven); conditions cleared -> resolved.
        fake.script[A].append(snap(A, "S1"))
        await scan_once(client, owner, org, pid)
        items = await alerts(client, owner, org)
        current = by_rule(items)
        assert current["Gone"] == [("open", "S2 no longer offering B0ALERT001")]
        # The opted-in rule alerts on proven departures too.
        assert current["Gone maybe"][1] == ("open", "S2 no longer offering B0ALERT001")
        for name in ("Crowded", "Cheap", "Failed"):
            assert current[name][0][0] == "resolved", name
            alert = next(a for a in items if a["rule_name"] == name)
            assert alert["resolved_automatically"] is True and alert["resolved_by"] is None
        assert "Other product only" not in current
        # Only the "New seller" rule emails, and it raised exactly one alert.
        assert len(mailer.sent) == 2

        summary = (await client.get("/api/v1/alerts/summary", headers=owner.headers(org))).json()
        assert summary["open"] == 4  # New seller, Gone maybe x2, Gone
        assert summary["acknowledged"] == 0 and summary["failed_deliveries"] == 0


async def setup_extra(client: AsyncClient, owner: AppUser, org: str) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/products", json={"identifier": "B0OTHER001"}, headers=owner.headers(org)
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def test_a_still_true_condition_raises_one_alert_until_resolved() -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        mailer_of(dispatcher)
        owner, org, ids = await setup_org(client, A)
        rule = await add_rule(
            client, owner, org, name="Crowded", rule_type="seller_count_above",
            params={"threshold": 1},
        )  # fmt: skip
        for _ in range(3):
            fake.script[A].append(snap(A, "S1", "S2"))
            await scan_once(client, owner, org, ids[A])
        items = await alerts(client, owner, org)
        assert len(items) == 1
        rules = (await client.get("/api/v1/alert-rules", headers=owner.headers(org))).json()
        assert rules["items"][0]["open_alerts"] == 1

        # Acknowledged still counts as unresolved: no duplicate.
        r = await client.post(
            f"/api/v1/alerts/{items[0]['id']}/acknowledge", headers=owner.headers(org)
        )
        assert r.json()["status"] == "acknowledged"
        await scan_once(client, owner, org, ids[A])
        assert len(await alerts(client, owner, org)) == 1

        # Resolved by hand while still true: the next scan raises a fresh alert.
        r = await client.post(
            f"/api/v1/alerts/{items[0]['id']}/resolve", headers=owner.headers(org)
        )
        assert r.json()["resolved_automatically"] is False
        assert r.json()["resolved_by"] == str(owner.id)
        await scan_once(client, owner, org, ids[A])
        items = await alerts(client, owner, org, active=True)
        assert len(items) == 1 and items[0]["alert_rule_id"] == rule["id"]

        # A disabled rule raises nothing.
        r = await client.patch(
            f"/api/v1/alert-rules/{rule['id']}",
            json={"is_enabled": False},
            headers=owner.headers(org),
        )
        assert r.status_code == 200 and r.json()["is_enabled"] is False
        await client.post(f"/api/v1/alerts/{items[0]['id']}/resolve", headers=owner.headers(org))
        await scan_once(client, owner, org, ids[A])
        assert await alerts(client, owner, org, active=True) == []


async def test_email_failures_are_recorded_retried_and_reported(owner_engine: AsyncEngine) -> None:
    fake = FakeConnector()
    async with scan_api(fake, alert_delivery_max_attempts=2) as (client, dispatcher):
        mailer = mailer_of(dispatcher)
        owner, org, ids = await setup_org(client, A)
        gone_member = AppUser("leaver")
        await join(client, mailer, org, owner, gone_member, "viewer")
        failing = mailer_of(dispatcher, FailingMailer())
        assert isinstance(failing, FailingMailer)
        await add_rule(
            client, owner, org, name="Failed", rule_type="scan_failed", severity="critical",
            channels=["email"], recipient_user_ids=[str(owner.id), str(gone_member.id)],
        )  # fmt: skip
        # The member leaves before the email goes out.
        r = await client.delete(f"/api/v1/members/{gone_member.id}", headers=owner.headers(org))
        assert r.status_code == 204, r.text

        fake.script[A].append(PermanentError("asin_rejected", "Rejected."))
        await scan_once(client, owner, org, ids[A])
        [alert] = await alerts(client, owner, org)
        deliveries = {d["recipient_user_id"]: d for d in alert["deliveries"]}
        assert deliveries[str(gone_member.id)]["status"] == "skipped"
        assert "no longer an active member" in deliveries[str(gone_member.id)]["last_error"]
        first = deliveries[str(owner.id)]
        assert first["status"] == "pending" and first["attempt_count"] == 1
        assert "ConnectionRefusedError" in first["last_error"]
        assert first["next_attempt_at"] is not None
        assert alert["delivered_channels"] == ["in_app"]

        # Not due yet: nothing happens. After the backoff: second attempt fails -> gives up.
        await dispatcher.deliver_alerts(uuid.UUID(org))
        dispatcher.clock.advance(61)
        await dispatcher.deliver_alerts(uuid.UUID(org))
        [alert] = await alerts(client, owner, org)
        mine = next(d for d in alert["deliveries"] if d["recipient_user_id"] == str(owner.id))
        assert (mine["status"], mine["attempt_count"]) == ("failed", 2)
        summary = (await client.get("/api/v1/alerts/summary", headers=owner.headers(org))).json()
        assert summary["failed_deliveries"] == 1
        assert summary["open_by_severity"] == {"info": 0, "warning": 0, "critical": 1}

        # Fixed SMTP: a manager retries; the email goes out.
        failing.failing = False
        r = await client.post(
            f"/api/v1/alerts/{alert['id']}/retry-delivery", headers=owner.headers(org)
        )
        assert r.status_code == 200, r.text
        [alert] = await alerts(client, owner, org)
        mine = next(d for d in alert["deliveries"] if d["recipient_user_id"] == str(owner.id))
        assert mine["status"] == "sent" and mine["last_error"] is None
        assert alert["delivered_channels"] == ["in_app", "email"]
        assert [m["To"] for m in failing.sent] == [owner.email]
        r = await client.post(
            f"/api/v1/alerts/{alert['id']}/retry-delivery", headers=owner.headers(org)
        )
        assert r.status_code == 409


async def test_beat_delivers_for_every_organization_and_recovers_stale_sends(
    owner_engine: AsyncEngine,
) -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        mailer = mailer_of(dispatcher)
        dispatcher.defer_alerts = True  # as if the post-scan task message was lost
        orgs = []
        for asin in ("B0BEAT0001", "B0BEAT0002"):
            owner, org, ids = await setup_org(client, asin)
            await add_rule(
                client, owner, org, name="Failed", rule_type="scan_failed",
                channels=["email"], recipient_user_ids=[str(owner.id)],
            )  # fmt: skip
            fake.script[asin].append(PermanentError("asin_rejected", "Rejected."))
            await scan_once(client, owner, org, ids[asin])
            orgs.append((owner, org))
        assert mailer.sent == []
        # A worker died mid-send long ago in the first org.
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE alert_deliveries SET status = 'sending', "
                    "claimed_at = now() - interval '1 hour' WHERE organization_id = :o"
                ),
                {"o": orgs[0][1]},
            )
        state = dispatcher.app.state
        processed = await deliver_all_due(
            state.session_factory, mailer, state.settings, now=dispatcher.clock() + _minute()
        )
        assert processed >= 2
        assert sorted(m["To"] for m in mailer.sent) == sorted(o.email for o, _ in orgs)


def _minute() -> Any:
    from datetime import timedelta

    return timedelta(minutes=1)


async def test_rule_validation_permissions_and_deletion() -> None:
    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        mailer = mailer_of(dispatcher)
        owner, org, ids = await setup_org(client, A)
        viewer = AppUser("viewer")
        await join(client, mailer, org, owner, viewer, "viewer")
        outsider = AppUser("outsider")
        h = owner.headers(org)

        async def bad(body: dict[str, Any]) -> list[Any]:
            r = await client.post("/api/v1/alert-rules", json=body, headers=h)
            assert r.status_code == 422, r.text
            return list(r.json()["errors"])

        errors = await bad({"name": "x", "rule_type": "price_below", "params": {}})
        assert errors[0]["loc"] == ["body", "params", "threshold"]
        await bad({"name": "x", "rule_type": "price_below", "params": {"threshold": 0}})
        await bad({"name": "x", "rule_type": "new_seller", "params": {"nope": True}})
        await bad({"name": "x", "rule_type": "made_up"})
        await bad({"name": "x", "rule_type": "new_seller", "channels": ["email"]})
        await bad({"name": "x", "rule_type": "new_seller", "channels": ["sms"]})
        await bad(
            {"name": "x", "rule_type": "new_seller", "channels": ["email"],
             "recipient_user_ids": [str(outsider.id)]}
        )  # fmt: skip
        errors = await bad(
            {"name": "x", "rule_type": "new_seller", "scope": {"product_ids": [str(uuid.uuid4())]}}
        )
        assert errors[0]["loc"] == ["body", "scope", "product_ids"]

        rule = await add_rule(
            client, owner, org, name="  Crowded  ", rule_type="seller_count_above",
            params={"threshold": 1}, scope={"brands": ["Acme"]},
        )  # fmt: skip
        assert rule["name"] == "Crowded"
        assert rule["severity"] == "warning"  # default for the type
        assert rule["channels"] == ["in_app"]
        assert rule["scope"] == {"product_ids": [], "brands": ["Acme"]}

        # Viewers can read and triage alerts, but not manage rules.
        r = await client.post(
            "/api/v1/alert-rules",
            json={"name": "v", "rule_type": "new_seller"},
            headers=viewer.headers(org),
        )
        assert r.status_code == 403
        r = await client.patch(
            f"/api/v1/alert-rules/{rule['id']}", json={"name": "v"}, headers=viewer.headers(org)
        )
        assert r.status_code == 403
        r = await client.get("/api/v1/alert-rules", headers=viewer.headers(org))
        assert r.status_code == 200 and len(r.json()["items"]) == 1

        r = await client.patch(
            f"/api/v1/alert-rules/{rule['id']}",
            json={"params": {"threshold": -5}},
            headers=h,
        )
        assert r.status_code == 422
        r = await client.patch(
            f"/api/v1/alert-rules/{rule['id']}", json={"channels": ["email"]}, headers=h
        )
        assert r.status_code == 422  # email needs recipients
        r = await client.patch(f"/api/v1/alert-rules/{rule['id']}", json={"scope": {}}, headers=h)
        assert r.status_code == 200

        fake.script[A].append(snap(A, "S1", "S2"))
        await scan_once(client, owner, org, ids[A])
        [alert] = await alerts(client, viewer, org)
        r = await client.post(
            "/api/v1/alerts/bulk",
            json={"ids": [alert["id"], str(uuid.uuid4())], "action": "acknowledge"},
            headers=viewer.headers(org),
        )
        assert r.json() == {"updated": 1}
        r = await client.post(f"/api/v1/alerts/{alert['id']}/resolve", headers=viewer.headers(org))
        assert r.json()["status"] == "resolved"
        r = await client.post(
            f"/api/v1/alerts/{alert['id']}/acknowledge", headers=viewer.headers(org)
        )
        assert r.status_code == 409
        r = await client.post(
            f"/api/v1/alerts/{alert['id']}/retry-delivery", headers=viewer.headers(org)
        )
        assert r.status_code == 403

        # Deleting a rule keeps its alerts, labelled with the rule's name.
        r = await client.delete(f"/api/v1/alert-rules/{rule['id']}", headers=h)
        assert r.status_code == 204
        [kept] = await alerts(client, owner, org)
        assert kept["alert_rule_id"] is None and kept["rule_name"] == "Crowded"
        r = await client.get(f"/api/v1/alert-rules/{rule['id']}", headers=h)
        assert r.status_code == 404


async def test_rule_changes_are_audited(owner_engine: AsyncEngine) -> None:
    async with scan_api(FakeConnector()) as (client, dispatcher):
        mailer_of(dispatcher)
        owner, org, _ = await setup_org(client)
        rule = await add_rule(client, owner, org, name="R", rule_type="new_seller")
        await client.patch(
            f"/api/v1/alert-rules/{rule['id']}", json={"name": "R2"}, headers=owner.headers(org)
        )
        await client.delete(f"/api/v1/alert-rules/{rule['id']}", headers=owner.headers(org))
    async with owner_engine.connect() as conn:
        actions = (
            (
                await conn.execute(
                    text(
                        "SELECT action FROM audit_logs WHERE organization_id = :o "
                        "AND action LIKE 'alert_rule.%' ORDER BY created_at"
                    ),
                    {"o": org},
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["alert_rule.create", "alert_rule.update", "alert_rule.delete"]


async def test_a_bug_in_alerting_never_loses_the_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    import sellerscope.alerts.record as record

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("rule engine bug")

    fake = FakeConnector()
    async with scan_api(fake) as (client, dispatcher):
        mailer_of(dispatcher)
        owner, org, ids = await setup_org(client, A)
        await add_rule(client, owner, org, name="R", rule_type="seller_count_above",
                       params={"threshold": 0})  # fmt: skip
        monkeypatch.setattr(record, "evaluate", boom)
        fake.script[A].append(snap(A, "S1"))
        await scan_once(client, owner, org, ids[A])
        product = (
            await client.get(f"/api/v1/products/{ids[A]}", headers=owner.headers(org))
        ).json()
        assert product["latest_scan"]["unique_seller_count"] == 1
        assert await alerts(client, owner, org) == []
