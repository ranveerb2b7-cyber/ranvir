from __future__ import annotations

import os

import pytest

from sellerscope.core.config import AppEnv, Settings


def integration_settings() -> Settings | None:
    """Integration tests need TEST_DATABASE_URL and TEST_REDIS_URL (CI sets both)."""
    db, redis = os.getenv("TEST_DATABASE_URL"), os.getenv("TEST_REDIS_URL")
    if not db or not redis:
        return None
    return Settings(app_env=AppEnv.TEST, database_url=db, redis_url=redis)  # type: ignore[arg-type]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if integration_settings() is not None:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL / TEST_REDIS_URL not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
