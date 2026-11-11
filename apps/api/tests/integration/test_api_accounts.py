"""M3 acceptance tests: auth, organizations, members, invitations, RBAC, audit, rate limits."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import (
    WEB_BASE,
    AppUser,
    RecordingMailer,
    api_settings,
    mint,
)

pytestmark = pytest.mark.integration

Api = tuple[AsyncClient, RecordingMailer]


async def make_org(client: AsyncClient, owner: AppUser, name: str = "Acme Brands") -> str:
    r = await client.post("/api/v1/organizations", json={"name": name}, headers=owner.headers())
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def join(
    client: AsyncClient,
    mailer: RecordingMailer,
    org: str,
    owner: AppUser,
    user: AppUser,
    role: str,
) -> None:
    r = await client.post(
        "/api/v1/invitations", json={"email": user.email, "role": role}, headers=owner.headers(org)
    )
    assert r.status_code == 201, r.text
    token = mailer.last_token(user.email)
    r = await client.post(
        "/api/v1/invitations/accept", json={"token": token}, headers=user.headers()
    )
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------------------ authentication


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Basic abc", "Bearer ", "Bearer not-a-jwt"],
)
async def test_me_requires_valid_bearer_token(api: Api, authorization: str | None) -> None:
    client, _ = api
    headers = {"Authorization": authorization} if authorization is not None else {}
    r = await client.get("/api/v1/me", headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_expired_token_rejected(api: Api) -> None:
    client, _ = api
    u = AppUser("exp")
    token = mint(u.id, u.email, exp=1_000_000_000)
    r = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Token expired"


async def test_first_request_creates_user_and_syncs_email(
    api: Api, owner_engine: AsyncEngine
) -> None:
    client, _ = api
    u = AppUser("new")
    r = await client.get("/api/v1/me", headers=u.headers())
    assert r.status_code == 200
    assert r.json() == {"id": str(u.id), "email": u.email, "full_name": None, "memberships": []}
    # Email changed at the identity provider -> mirrored on next request.
    u.email = f"changed-{u.email}"
    r = await client.get("/api/v1/me", headers=u.headers())
    assert r.json()["email"] == u.email
    async with owner_engine.connect() as conn:
        count = (
            await conn.execute(text("SELECT count(*) FROM users WHERE id = :i"), {"i": u.id})
        ).scalar_one()
    assert count == 1


async def test_update_profile(api: Api) -> None:
    client, _ = api
    u = AppUser("prof")
    r = await client.patch("/api/v1/me", json={"full_name": "  Asha Rao "}, headers=u.headers())
    assert r.status_code == 200
    assert r.json()["full_name"] == "Asha Rao"


# ------------------------------------------------------------------------------ organizations


async def test_create_org_makes_owner_with_trial_and_audit(
    api: Api, owner_engine: AsyncEngine
) -> None:
    client, _ = api
    owner = AppUser("owner")
    r = await client.post(
        "/api/v1/organizations", json={"name": "Acme Brands"}, headers=owner.headers()
    )
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "owner"
    assert body["slug"].startswith("acme-brands-")
    assert "org.delete" in body["permissions"]

    me = (await client.get("/api/v1/me", headers=owner.headers())).json()
    assert [m["organization_id"] for m in me["memberships"]] == [body["id"]]

    async with owner_engine.connect() as conn:
        sub = (
            await conn.execute(
                text(
                    "SELECT s.status, p.code FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :o"
                ),
                {"o": body["id"]},
            )
        ).one()
        actions = (
            (
                await conn.execute(
                    text("SELECT action FROM audit_logs WHERE organization_id = :o"),
                    {"o": body["id"]},
                )
            )
            .scalars()
            .all()
        )
    assert tuple(sub) == ("trialing", "trial")
    assert actions == ["organization.create"]


@pytest.mark.parametrize("name", ["", " ", "x", "y" * 81])
async def test_org_name_validated(api: Api, name: str) -> None:
    client, _ = api
    r = await client.post(
        "/api/v1/organizations", json={"name": name}, headers=AppUser("v").headers()
    )
    assert r.status_code == 422


async def test_org_header_required_and_membership_checked(api: Api) -> None:
    client, _ = api
    owner, stranger = AppUser("o"), AppUser("s")
    org = await make_org(client, owner)
    assert (await client.get("/api/v1/members", headers=owner.headers())).status_code == 400
    r = await client.get("/api/v1/members", headers=stranger.headers(org))
    assert r.status_code == 404
    assert r.json()["code"] == "organization_not_found"
    r = await client.get("/api/v1/members", headers=owner.headers(uuid.uuid4()))
    assert r.status_code == 404
    r = await client.get("/api/v1/members", headers={**owner.headers(), "X-Organization-Id": "x"})
    assert r.status_code == 422


async def test_rename_and_soft_delete_org(api: Api) -> None:
    client, _ = api
    owner = AppUser("o")
    org = await make_org(client, owner)
    r = await client.patch(
        "/api/v1/organizations/current", json={"name": "Renamed Co"}, headers=owner.headers(org)
    )
    assert r.json()["name"] == "Renamed Co"
    r = await client.delete("/api/v1/organizations/current", headers=owner.headers(org))
    assert r.status_code == 204
    assert (await client.get("/api/v1/me", headers=owner.headers())).json()["memberships"] == []
    r = await client.get("/api/v1/organizations/current", headers=owner.headers(org))
    assert r.status_code == 404


# ------------------------------------------------------------------------------ RBAC


async def test_role_permissions_enforced(api: Api) -> None:
    client, mailer = api
    owner, admin, analyst, viewer = (AppUser(n) for n in ("o", "ad", "an", "vi"))
    org = await make_org(client, owner)
    for user, role in ((admin, "admin"), (analyst, "analyst"), (viewer, "viewer")):
        await join(client, mailer, org, owner, user, role)

    invite = {"email": "x@example.com", "role": "viewer"}
    for user in (analyst, viewer):
        r = await client.post("/api/v1/invitations", json=invite, headers=user.headers(org))
        assert r.status_code == 403
        r = await client.patch(
            "/api/v1/organizations/current", json={"name": "Nope"}, headers=user.headers(org)
        )
        assert r.status_code == 403
        # ...but every member can read.
        assert (await client.get("/api/v1/members", headers=user.headers(org))).status_code == 200

    r = await client.post("/api/v1/invitations", json=invite, headers=admin.headers(org))
    assert r.status_code == 201
    r = await client.delete("/api/v1/organizations/current", headers=admin.headers(org))
    assert r.status_code == 403  # only the owner deletes


async def test_member_management_rules(api: Api, owner_engine: AsyncEngine) -> None:
    client, mailer = api
    owner, admin, analyst = AppUser("o"), AppUser("a"), AppUser("n")
    org = await make_org(client, owner)
    await join(client, mailer, org, owner, admin, "admin")
    await join(client, mailer, org, owner, analyst, "analyst")

    # Admin cannot touch the owner or themselves, cannot grant ownership.
    r = await client.patch(
        f"/api/v1/members/{owner.id}", json={"role": "viewer"}, headers=admin.headers(org)
    )
    assert r.status_code == 403
    r = await client.patch(
        f"/api/v1/members/{admin.id}", json={"role": "viewer"}, headers=admin.headers(org)
    )
    assert r.status_code == 403
    r = await client.patch(
        f"/api/v1/members/{analyst.id}", json={"role": "owner"}, headers=admin.headers(org)
    )
    assert r.status_code == 422

    r = await client.patch(
        f"/api/v1/members/{analyst.id}", json={"role": "viewer"}, headers=admin.headers(org)
    )
    assert r.status_code == 200 and r.json()["role"] == "viewer"

    # Suspended members lose access.
    r = await client.patch(
        f"/api/v1/members/{analyst.id}", json={"status": "suspended"}, headers=admin.headers(org)
    )
    assert r.status_code == 200
    assert (await client.get("/api/v1/members", headers=analyst.headers(org))).status_code == 404

    r = await client.delete(f"/api/v1/members/{analyst.id}", headers=admin.headers(org))
    assert r.status_code == 204

    # Owner cannot leave; admin can.
    assert (
        await client.delete("/api/v1/members/me", headers=owner.headers(org))
    ).status_code == 403
    assert (
        await client.delete("/api/v1/members/me", headers=admin.headers(org))
    ).status_code == 204

    async with owner_engine.connect() as conn:
        actions = set(
            (
                await conn.execute(
                    text("SELECT action FROM audit_logs WHERE organization_id = :o"), {"o": org}
                )
            ).scalars()
        )
    assert {"member.update", "member.remove", "member.leave", "invitation.accept"} <= actions


async def test_transfer_ownership(api: Api) -> None:
    client, mailer = api
    owner, admin = AppUser("o"), AppUser("a")
    org = await make_org(client, owner)
    await join(client, mailer, org, owner, admin, "admin")
    r = await client.post(
        "/api/v1/organizations/current/transfer-ownership",
        json={"user_id": str(admin.id)},
        headers=admin.headers(org),
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/organizations/current/transfer-ownership",
        json={"user_id": str(admin.id)},
        headers=owner.headers(org),
    )
    assert r.status_code == 200
    roles = {m["user_id"]: m["role"] for m in r.json()}
    assert roles == {str(owner.id): "admin", str(admin.id): "owner"}


# ------------------------------------------------------------------------------ invitations


async def test_invitation_flow(api: Api) -> None:
    client, mailer = api
    owner, invitee = AppUser("o"), AppUser("i")
    org = await make_org(client, owner, "Acme")
    r = await client.post(
        "/api/v1/invitations",
        json={"email": invitee.email.upper(), "role": "analyst"},
        headers=owner.headers(org),
    )
    assert r.status_code == 201
    assert r.json()["email_sent"] is True
    assert r.json()["email"] == invitee.email  # normalised

    message = mailer.sent[-1]
    assert message["To"] == invitee.email
    assert f"{WEB_BASE}/accept-invite?token=" in message.get_content()
    token = mailer.last_token(invitee.email)

    pending = (await client.get("/api/v1/invitations", headers=owner.headers(org))).json()
    assert [p["email"] for p in pending] == [invitee.email]

    r = await client.post(
        "/api/v1/invitations/preview", json={"token": token}, headers=invitee.headers()
    )
    assert r.json() == {
        "organization_name": "Acme",
        "email": invitee.email,
        "role": "analyst",
        "status": "pending",
        "email_matches": True,
    }

    r = await client.post(
        "/api/v1/invitations/accept", json={"token": token}, headers=invitee.headers()
    )
    assert r.status_code == 200 and r.json() == {"organization_id": org}

    members = (await client.get("/api/v1/members", headers=invitee.headers(org))).json()
    assert {(m["email"], m["role"]) for m in members} == {
        (owner.email, "owner"),
        (invitee.email, "analyst"),
    }
    assert (await client.get("/api/v1/invitations", headers=owner.headers(org))).json() == []

    r = await client.post(
        "/api/v1/invitations/accept", json={"token": token}, headers=invitee.headers()
    )
    assert r.status_code == 410 and r.json()["code"] == "invitation_already_used"


async def test_invitation_cannot_be_used_by_another_email(api: Api) -> None:
    client, mailer = api
    owner, invitee, thief = AppUser("o"), AppUser("i"), AppUser("t")
    org = await make_org(client, owner)
    await client.post(
        "/api/v1/invitations",
        json={"email": invitee.email, "role": "admin"},
        headers=owner.headers(org),
    )
    token = mailer.last_token(invitee.email)
    r = await client.post(
        "/api/v1/invitations/preview", json={"token": token}, headers=thief.headers()
    )
    assert r.json()["email_matches"] is False
    r = await client.post(
        "/api/v1/invitations/accept", json={"token": token}, headers=thief.headers()
    )
    assert r.status_code == 403 and r.json()["code"] == "invitation_email_mismatch"
    assert (await client.get("/api/v1/members", headers=thief.headers(org))).status_code == 404


async def test_revoked_expired_resent_and_unknown_tokens(
    api: Api, owner_engine: AsyncEngine
) -> None:
    client, mailer = api
    owner, a, b = AppUser("o"), AppUser("a"), AppUser("b")
    org = await make_org(client, owner)

    inv = (
        await client.post(
            "/api/v1/invitations",
            json={"email": a.email, "role": "viewer"},
            headers=owner.headers(org),
        )
    ).json()
    old_token = mailer.last_token(a.email)
    r = await client.post(f"/api/v1/invitations/{inv['id']}/resend", headers=owner.headers(org))
    assert r.status_code == 200
    new_token = mailer.last_token(a.email)
    assert new_token != old_token
    r = await client.post(
        "/api/v1/invitations/accept", json={"token": old_token}, headers=a.headers()
    )
    assert r.status_code == 404  # old link no longer works
    assert (
        await client.delete(f"/api/v1/invitations/{inv['id']}", headers=owner.headers(org))
    ).status_code == 204
    r = await client.post(
        "/api/v1/invitations/accept", json={"token": new_token}, headers=a.headers()
    )
    assert r.status_code == 410 and r.json()["code"] == "invitation_revoked"

    inv_b = (
        await client.post(
            "/api/v1/invitations",
            json={"email": b.email, "role": "viewer"},
            headers=owner.headers(org),
        )
    ).json()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE invitations SET expires_at = now() - interval '1 minute' WHERE id = :i"),
            {"i": inv_b["id"]},
        )
    r = await client.post(
        "/api/v1/invitations/accept",
        json={"token": mailer.last_token(b.email)},
        headers=b.headers(),
    )
    assert r.status_code == 410 and r.json()["code"] == "invitation_expired"

    r = await client.post(
        "/api/v1/invitations/accept", json={"token": "x" * 43}, headers=b.headers()
    )
    assert r.status_code == 404


async def test_duplicate_invites_and_existing_members_rejected(api: Api) -> None:
    client, mailer = api
    owner, a = AppUser("o"), AppUser("a")
    org = await make_org(client, owner)
    await join(client, mailer, org, owner, a, "viewer")
    r = await client.post(
        "/api/v1/invitations", json={"email": a.email, "role": "viewer"}, headers=owner.headers(org)
    )
    assert r.status_code == 409 and r.json()["code"] == "already_member"
    body = {"email": "pending@example.com", "role": "viewer"}
    assert (
        await client.post("/api/v1/invitations", json=body, headers=owner.headers(org))
    ).status_code == 201
    r = await client.post("/api/v1/invitations", json=body, headers=owner.headers(org))
    assert r.status_code == 409 and r.json()["code"] == "invitation_pending"
    r = await client.post(
        "/api/v1/invitations",
        json={"email": "z@example.com", "role": "owner"},
        headers=owner.headers(org),
    )
    assert r.status_code == 422


async def test_failed_email_is_reported_not_hidden(api: Api) -> None:
    client, mailer = api

    async def boom(message: Any) -> None:
        raise OSError("smtp down")

    mailer.send = boom  # type: ignore[method-assign]
    owner = AppUser("o")
    org = await make_org(client, owner)
    r = await client.post(
        "/api/v1/invitations",
        json={"email": "q@example.com", "role": "viewer"},
        headers=owner.headers(org),
    )
    assert r.status_code == 201
    assert r.json()["email_sent"] is False


# ------------------------------------------------------------------------------ rate limiting


async def test_endpoint_rate_limit_returns_429(api: Api) -> None:
    client, _ = api
    u = AppUser("rl")
    statuses = []
    for _ in range(21):
        r = await client.post(
            "/api/v1/invitations/preview", json={"token": "y" * 43}, headers=u.headers()
        )
        statuses.append(r.status_code)
    assert statuses[:20] == [404] * 20
    assert statuses[20] == 429
    assert int(r.headers["retry-after"]) >= 1
    assert r.json()["code"] == "rate_limited"


async def test_ip_rate_limit_skips_health(owner_engine: AsyncEngine) -> None:
    from httpx import ASGITransport

    from sellerscope.main import create_app

    app = create_app(api_settings(rate_limit_ip_per_minute=3))
    async with app.router.lifespan_context(app):
        await app.state.redis.delete(
            *[k async for k in app.state.redis.scan_iter("rl:ip:*")] or ["_"]
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = [(await c.get("/api/v1/me")).status_code for _ in range(4)]
            assert codes == [401, 401, 401, 429]
            assert (await c.get("/api/v1/health/live")).status_code == 200
