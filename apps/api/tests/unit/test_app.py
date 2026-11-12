from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from sellerscope.core.config import AppEnv, Settings
from sellerscope.main import create_app

# Points at ports where nothing listens, so dependency checks fail fast and deterministically.
UNREACHABLE = Settings(
    app_env=AppEnv.TEST,
    database_url="postgresql+asyncpg://x:x@127.0.0.1:1/x",  # type: ignore[arg-type]
    redis_url="redis://127.0.0.1:1/0",  # type: ignore[arg-type]
    health_check_timeout_s=1.0,
)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app(UNREACHABLE)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_live(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-request-id"]


async def test_ready_reports_503_when_dependencies_down(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "checks": {"database": "error", "redis": "error"}}


async def test_unknown_route_is_problem_json(client: AsyncClient) -> None:
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "not_found"


async def test_request_id_is_propagated_when_valid(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/live", headers={"X-Request-ID": "abcd1234-test"})
    assert r.headers["x-request-id"] == "abcd1234-test"


async def test_malformed_request_id_is_replaced(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id <script>"})
    assert r.headers["x-request-id"] != "bad id <script>"


async def test_openapi_available_outside_production(client: AsyncClient) -> None:
    r = await client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    assert "/api/v1/health/ready" in r.json()["paths"]


async def test_docs_disabled_in_production() -> None:
    app = create_app(
        Settings(
            app_env=AppEnv.PRODUCTION,
            auth_jwt_issuer="https://auth.example/auth/v1",
            auth_jwks_url="https://auth.example/auth/v1/.well-known/jwks.json",
            storage_backend="s3",
            s3_bucket="sellerscope-prod",
            web_base_url="https://app.sellerscope.example",
            cors_origins="https://app.sellerscope.example",
            metrics_token="m" * 40,
            smtp_starttls=True,
            database_url="postgresql+asyncpg://app:prod-secret@db.internal/sellerscope",
            redis_url="rediss://:prod-secret@cache.internal:6379/0",
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/api/v1/openapi.json")).status_code == 404
        assert (await c.get("/docs")).status_code == 404


async def test_security_headers_on_api_responses(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/live")
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["strict-transport-security"].startswith("max-age=")
    # Swagger UI (development only) loads its own scripts, so it is exempt from the API CSP.
    docs = await client.get("/docs")
    assert docs.status_code == 200 and "content-security-policy" not in docs.headers
