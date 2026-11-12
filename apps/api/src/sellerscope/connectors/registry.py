"""Which connector an organization may use for a marketplace."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.connectors.base import (
    ConnectorContext,
    ConnectorUnavailableError,
    MarketplaceConnector,
)
from sellerscope.connectors.mock import MockConnector
from sellerscope.core.config import Settings
from sellerscope.models import Marketplace

NO_CONNECTION = (
    "No data connection is set up for Amazon.in yet. Connecting your Amazon seller account "
    "is coming in the next release; until then products can't be scanned."
)


class ConnectorRegistry:
    def __init__(self, settings: Settings) -> None:
        # Settings already refuses ENABLE_MOCK_CONNECTOR in staging/production; this is a
        # second, independent guard.
        self._mock = (
            MockConnector()
            if settings.enable_mock_connector and not settings.is_production_like
            else None
        )

    @property
    def mock_enabled(self) -> bool:
        return self._mock is not None

    async def resolve(
        self, session: AsyncSession, organization_id: uuid.UUID, marketplace_code: str
    ) -> tuple[MarketplaceConnector, ConnectorContext]:
        """Raises ConnectorUnavailableError if no authorized source exists for this org."""
        marketplace = (
            await session.execute(select(Marketplace).where(Marketplace.code == marketplace_code))
        ).scalar_one_or_none()
        if marketplace is None or not marketplace.is_enabled:
            raise ConnectorUnavailableError(marketplace_code, "Unsupported marketplace.")
        ctx = ConnectorContext(
            organization_id=organization_id,
            marketplace_code=marketplace_code,
            external_marketplace_id=marketplace.external_marketplace_id,
            connection=None,
        )
        # Amazon SP-API connections (milestone M7) are resolved here first.
        if self._mock is not None:
            return self._mock, ctx
        raise ConnectorUnavailableError(marketplace_code, NO_CONNECTION)
