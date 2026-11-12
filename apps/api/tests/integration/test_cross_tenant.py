"""Cross-tenant isolation matrix for EVERY organization-scoped endpoint.

Routes are discovered from the app, so a new endpoint is covered automatically; an endpoint
that is not organization-scoped must be listed in NON_ORG_ROUTES or the meta-test fails.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import AsyncClient

from sellerscope.auth.deps import get_org_context
from sellerscope.main import create_app
from tests.integration.conftest import AppUser, RecordingMailer, api_settings
from tests.integration.test_api_accounts import join, make_org

pytestmark = pytest.mark.integration

# Routes that intentionally do not take an organization context.
NON_ORG_ROUTES = {
    ("GET", "/api/v1/health/live"),
    ("GET", "/api/v1/health/ready"),
    ("GET", "/api/v1/me"),
    ("PATCH", "/api/v1/me"),
    ("POST", "/api/v1/organizations"),
    ("POST", "/api/v1/invitations/preview"),
    ("POST", "/api/v1/invitations/accept"),
    ("GET", "/api/v1/uploads/template"),  # static file, no organization data
    ("GET", "/api/v1/meta"),  # public runtime facts (environment, mock mode)
}

# Minimal valid bodies so requests are not rejected by validation before authorization.
BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", "/api/v1/organizations/current"): {"name": "Hijacked"},
    ("PATCH", "/api/v1/members/{user_id}"): {"role": "viewer"},
    ("POST", "/api/v1/organizations/current/transfer-ownership"): {"user_id": "{user_id}"},
    ("POST", "/api/v1/invitations"): {"email": "intruder@example.com", "role": "admin"},
    ("POST", "/api/v1/products"): {"identifier": "B0INTRUDER"},
    ("POST", "/api/v1/products/validate"): {"items": [{"identifier": "B0INTRUDER"}]},
    ("POST", "/api/v1/products/bulk"): {"ids": ["{product_id}"], "action": "delete"},
    ("PATCH", "/api/v1/products/{product_id}"): {"brand_name": "Hijacked"},
    ("POST", "/api/v1/scan-jobs"): {"product_ids": ["{product_id}"]},
}


def _depends_on(dep: Dependant, fn: object) -> bool:
    return dep.call is fn or any(_depends_on(d, fn) for d in dep.dependencies)


def _walk(items: list[Any], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Flattens nested routers (FastAPI keeps included routers as nested objects)."""
    for item in items:
        if isinstance(item, APIRoute):
            yield prefix + item.path, item
        elif hasattr(item, "original_router"):
            yield from _walk(item.original_router.routes, prefix + item.include_context.prefix)


def routes(app: FastAPI) -> Iterator[tuple[str, str, APIRoute]]:
    for path, route in _walk(list(app.routes)):
        for method in sorted(route.methods):
            yield method, path, route


def org_scoped(app: FastAPI) -> list[tuple[str, str]]:
    return [(m, p) for m, p, r in routes(app) if _depends_on(r.dependant, get_org_context)]


def test_every_route_is_classified() -> None:
    app = create_app(api_settings())
    unclassified = [
        (m, p)
        for m, p, r in routes(app)
        if p.startswith("/api/v1")
        and (m, p) not in NON_ORG_ROUTES
        and not _depends_on(r.dependant, get_org_context)
    ]
    assert unclassified == [], "New routes must be org-scoped or listed in NON_ORG_ROUTES"
    # Cross-check discovery against the public OpenAPI schema so this can never pass vacuously.
    openapi_ops = {
        (method.upper(), path) for path, ops in app.openapi()["paths"].items() for method in ops
    }
    assert {(m, p) for m, p, _ in routes(app)} == openapi_ops
    assert len(org_scoped(app)) == len(openapi_ops) - len(NON_ORG_ROUTES)
    assert len(org_scoped(app)) >= 11


def _fill(path: str, ids: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: ids[m.group(1)], path)


def _fill_value(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _fill(value, ids)
    if isinstance(value, list):
        return [_fill_value(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: _fill_value(v, ids) for k, v in value.items()}
    return value


def _body(method: str, path: str, ids: dict[str, str]) -> dict[str, Any] | None:
    body = BODIES.get((method, path))
    return None if body is None else _fill_value(body, ids)


async def _product(client: AsyncClient, user: AppUser, org: str) -> str:
    r = await client.post(
        "/api/v1/products",
        json={"identifier": "B0VICTIM01", "brand_name": "V"},
        headers=user.headers(org),
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _upload(client: AsyncClient, user: AppUser, org: str) -> str:
    r = await client.post(
        "/api/v1/uploads",
        files={"file": ("victim.csv", b"ASIN\nB0VICTIM02\n", "text/csv")},
        headers=user.headers(org),
    )
    assert r.status_code == 202, r.text
    return str(r.json()["id"])


async def _scan(client: AsyncClient, user: AppUser, org: str) -> str:
    products = (await client.get("/api/v1/products", headers=user.headers(org))).json()["items"]
    r = await client.post(
        "/api/v1/scan-jobs", json={"product_ids": [products[0]["id"]]}, headers=user.headers(org)
    )
    assert r.status_code == 202, r.text
    return str(r.json()["id"])


async def _setup(client: AsyncClient, mailer: RecordingMailer) -> dict[str, Any]:
    alice, alice_member, bob, bob_member = (AppUser(n) for n in ("alice", "am", "bob", "bm"))
    org_a = await make_org(client, alice, "Org A")
    org_b = await make_org(client, bob, "Org B")
    await join(client, mailer, org_a, alice, alice_member, "analyst")
    await join(client, mailer, org_b, bob, bob_member, "analyst")
    inv_a = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "pa@example.com", "role": "viewer"},
            headers=alice.headers(org_a),
        )
    ).json()["id"]
    inv_b = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "pb@example.com", "role": "viewer"},
            headers=bob.headers(org_b),
        )
    ).json()["id"]
    return {
        "alice": alice,
        "bob": bob,
        "org_a": org_a,
        "org_b": org_b,
        "a_ids": {
            "user_id": str(alice_member.id),
            "invitation_id": inv_a,
            "product_id": await _product(client, alice, org_a),
            "batch_id": await _upload(client, alice, org_a),
            "job_id": await _scan(client, alice, org_a),
        },
        "b_ids": {
            "user_id": str(bob_member.id),
            "invitation_id": inv_b,
            "product_id": await _product(client, bob, org_b),
            "batch_id": await _upload(client, bob, org_b),
            "job_id": await _scan(client, bob, org_b),
        },
    }


async def _snapshot(client: AsyncClient, user: AppUser, org: str) -> tuple[Any, ...]:
    org_body = (await client.get("/api/v1/organizations/current", headers=user.headers(org))).json()
    members = (await client.get("/api/v1/members", headers=user.headers(org))).json()
    invites = (await client.get("/api/v1/invitations", headers=user.headers(org))).json()
    products = (await client.get("/api/v1/products", headers=user.headers(org))).json()["items"]
    uploads = (await client.get("/api/v1/uploads", headers=user.headers(org))).json()["items"]
    jobs = (await client.get("/api/v1/scan-jobs", headers=user.headers(org))).json()["items"]
    return (
        org_body["name"],
        sorted((m["user_id"], m["role"], m["status"]) for m in members),
        sorted(i["id"] for i in invites),
        sorted((p["id"], p["brand_name"], p["monitoring_enabled"]) for p in products),
        sorted((b["id"], b["status"]) for b in uploads),
        sorted((j["id"], j["status"], j["cancelled_items"]) for j in jobs),
    )


async def test_non_member_gets_404_on_every_org_scoped_route(
    api: tuple[AsyncClient, RecordingMailer],
) -> None:
    """Bob (owner of B) aims at org A using A's own resource ids."""
    client, mailer = api
    s = await _setup(client, mailer)
    before = await _snapshot(client, s["alice"], s["org_a"])
    app_routes = org_scoped(client._transport.app)  # type: ignore[attr-defined]
    assert len(app_routes) >= 11

    failures = []
    for method, path in app_routes:
        r = await client.request(
            method,
            _fill(path, s["a_ids"]),
            json=_body(method, path, s["a_ids"]),
            headers=s["bob"].headers(s["org_a"]),
        )
        if r.status_code != 404 or r.json().get("code") != "organization_not_found":
            failures.append((method, path, r.status_code, r.text[:200]))
    assert failures == []
    assert await _snapshot(client, s["alice"], s["org_a"]) == before


async def test_member_cannot_reach_other_orgs_resources_by_id(
    api: tuple[AsyncClient, RecordingMailer],
) -> None:
    """Alice (owner of A, full permissions) uses org A context but org B's resource ids."""
    client, mailer = api
    s = await _setup(client, mailer)
    before_b = await _snapshot(client, s["bob"], s["org_b"])
    app_routes = [
        (m, p)
        for m, p in org_scoped(client._transport.app)  # type: ignore[attr-defined]
        if "{" in p or "transfer-ownership" in p
    ]
    assert app_routes, "expected id-addressed routes"

    failures = []
    for method, path in app_routes:
        r = await client.request(
            method,
            _fill(path, s["b_ids"]),
            json=_body(method, path, s["b_ids"]),
            headers=s["alice"].headers(s["org_a"]),
        )
        if r.status_code != 404:
            failures.append((method, path, r.status_code, r.text[:200]))
    assert failures == []
    assert await _snapshot(client, s["bob"], s["org_b"]) == before_b
