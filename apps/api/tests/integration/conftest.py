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
