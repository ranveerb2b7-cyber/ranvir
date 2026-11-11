from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from sellerscope.main import create_app
from tests.conftest import integration_settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    settings = integration_settings()
    assert settings is not None
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as c,
    ):
        yield c


async def test_ready_ok_with_real_postgres_and_redis(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_celery_ping_roundtrip_eager() -> None:
    from sellerscope.workers.celery_app import celery_app
    from sellerscope.workers.tasks import ping

    celery_app.conf.task_always_eager = True
    try:
        assert ping.delay().get(timeout=5) == "pong"
    finally:
        celery_app.conf.task_always_eager = False
