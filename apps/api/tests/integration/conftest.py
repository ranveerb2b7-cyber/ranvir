"""Fixtures for tests that need a migrated PostgreSQL database.

The TEST_DATABASE_URL user acts as schema owner (migrations) and must be able to create
roles (CREATEROLE) so the restricted app role can be provisioned. CI uses a superuser.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Table, insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from sellerscope.core.ids import uuid7
from tests.conftest import integration_settings

APP_ROLE = "sellerscope_app_test"
APP_PASSWORD = "app-test-only"  # test-only credential for a throwaway role
API_DIR = Path(__file__).resolve().parents[2]


def owner_url() -> str:
    settings = integration_settings()
    assert settings is not None
    return settings.database_url.get_secret_value()


def app_url() -> str:
    url = make_url(owner_url()).set(username=APP_ROLE, password=APP_PASSWORD)
    return url.render_as_string(hide_password=False)


def alembic_config() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.attributes["database_url"] = owner_url()
    cfg.attributes["app_db_role"] = APP_ROLE
    cfg.attributes["configure_logger"] = False
    return cfg


async def run_alembic(fn: str, revision: str) -> None:
    # Alembic's env.py calls asyncio.run(), so run it off the event loop thread.
    await asyncio.to_thread(getattr(command, fn), alembic_config(), revision)


@pytest.fixture(scope="session")
async def owner_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(owner_url())
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
                f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' "
                "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE; "
                "END IF; END $$;"
            )
        )
        # Start every test session from an empty schema.
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await run_alembic("upgrade", "head")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def app_engine(owner_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(app_url())
    yield engine
    await engine.dispose()


async def set_ctx(conn: AsyncConnection, org: uuid.UUID | None, user: uuid.UUID | None) -> None:
    await conn.execute(
        text(
            "SELECT set_config('app.current_org_id', :o, true), "
            "set_config('app.current_user_id', :u, true)"
        ),
        {"o": str(org) if org else "", "u": str(user) if user else ""},
    )


async def add(conn: AsyncConnection, table: Table, **values: Any) -> uuid.UUID:
    values.setdefault("id", uuid7())
    await conn.execute(insert(table).values(**values))
    return uuid.UUID(str(values["id"]))


async def marketplace_id(conn: AsyncConnection) -> uuid.UUID:
    row = (await conn.execute(text("SELECT id FROM marketplaces WHERE code = 'amazon_in'"))).one()
    return uuid.UUID(str(row[0]))


# ----------------------------------------------------------------------------- API fixtures

import tempfile  # noqa: E402
import time as _time  # noqa: E402
from email.message import EmailMessage  # noqa: E402

import jwt  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from redis.asyncio import Redis  # noqa: E402

from sellerscope.core.config import AppEnv, Settings  # noqa: E402
from sellerscope.main import create_app  # noqa: E402

AUTH_ISSUER = "http://auth.test/auth/v1"
_STORAGE_DIR = tempfile.mkdtemp(prefix="sellerscope-test-storage-")
AUTH_SECRET = "integration-test-hs256-secret-32-bytes!!"  # test-only signing key
WEB_BASE = "http://web.test"


class FakeClock:
    """Controllable time for retry/backoff tests. `sleep` advances it instead of waiting."""

    def __init__(self) -> None:
        from datetime import UTC, datetime

        self.now = datetime.now(UTC)

    def __call__(self) -> Any:
        return self.now

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self.now += timedelta(seconds=seconds)

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)


class InlineDispatcher:
    """Runs background work immediately instead of queueing it for a Celery worker.

    Scan jobs run once per dispatch (no automatic re-runs for delayed retries); the delay a
    real worker would wait is recorded in `scan_delays`. Set `defer_scans` to only record.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self.clock = FakeClock()
        self.defer_scans = False
        self.scan_calls: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.parse_calls: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.scan_delays: list[float | None] = []
        self.deliver_calls: list[uuid.UUID] = []
        self.defer_alerts = False

    def scan_deps(self) -> Any:
        from sellerscope.scanning.runner import ScanDeps

        state = self.app.state
        return ScanDeps(
            session_factory=state.session_factory,
            registry=state.connector_registry,
            limiter=state.token_bucket,
            storage=state.storage,
            settings=state.settings,
            clock=self.clock,
            sleep=self.clock.sleep,
        )

    async def run_scan_job(
        self, organization_id: uuid.UUID, job_id: uuid.UUID, countdown_s: float = 0
    ) -> None:
        from sellerscope.scanning.runner import run_job

        self.scan_calls.append((organization_id, job_id))
        if not self.defer_scans:
            self.scan_delays.append(await run_job(self.scan_deps(), organization_id, job_id))
            # Like the Celery task: alerts raised by the run are emailed right after it.
            await self.deliver_alerts(organization_id)

    async def deliver_alerts(self, organization_id: uuid.UUID) -> None:
        from sellerscope.alerts.delivery import deliver_pending

        self.deliver_calls.append(organization_id)
        if self.defer_alerts:
            return
        state = self.app.state
        await deliver_pending(
            state.session_factory,
            state.mailer,
            state.settings,
            organization_id=organization_id,
            now=self.clock(),
        )

    async def parse_upload(self, organization_id: uuid.UUID, batch_id: uuid.UUID) -> None:
        from sellerscope.uploads.service import parse_batch

        self.parse_calls.append((organization_id, batch_id))
        state = self.app.state
        await parse_batch(
            state.session_factory,
            state.storage,
            state.settings,
            organization_id=organization_id,
            batch_id=batch_id,
        )


class RecordingMailer:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

    def last_token(self, to: str) -> str:
        for message in reversed(self.sent):
            if message["To"] == to:
                body = message.get_content()
                return body.split("accept-invite?token=")[1].split()[0]
        raise AssertionError(f"no email to {to}")


def api_settings(**overrides: Any) -> Settings:
    base = integration_settings()
    assert base is not None
    values: dict[str, Any] = {
        "app_env": AppEnv.TEST,
        "database_url": app_url(),
        "redis_url": base.redis_url.get_secret_value(),
        "auth_jwt_issuer": AUTH_ISSUER,
        "auth_jwt_secret": AUTH_SECRET,
        "web_base_url": WEB_BASE,
        "rate_limit_ip_per_minute": 100_000,
        "storage_backend": "local",
        "storage_local_dir": _STORAGE_DIR,
        "enable_mock_connector": True,
    }
    values.update(overrides)
    return Settings(**values)


def mint(user_id: uuid.UUID, email: str, **overrides: Any) -> str:
    now = int(_time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "aud": "authenticated",
        "iss": AUTH_ISSUER,
        "role": "authenticated",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(overrides)
    return jwt.encode(payload, AUTH_SECRET, algorithm="HS256")


class AppUser:
    def __init__(self, label: str) -> None:
        self.id = uuid.uuid4()
        self.email = f"{label}-{self.id.hex[:8]}@example.com"

    def headers(self, org: uuid.UUID | str | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {mint(self.id, self.email)}"}
        if org:
            h["X-Organization-Id"] = str(org)
        return h


@pytest.fixture(scope="session")
async def _flush_test_redis() -> None:
    base = integration_settings()
    assert base is not None
    redis = Redis.from_url(base.redis_url.get_secret_value())
    await redis.flushdb()
    await redis.aclose()


@pytest.fixture
async def api(
    owner_engine: AsyncEngine, _flush_test_redis: None
) -> AsyncIterator[tuple[AsyncClient, RecordingMailer]]:
    app = create_app(api_settings())
    mailer = RecordingMailer()
    app.state.mailer = mailer
    app.state.task_dispatcher = InlineDispatcher(app)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://api.test") as c,
    ):
        yield c, mailer
