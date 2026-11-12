"""Public runtime facts the web app needs (e.g. to show a MOCK DATA banner). No secrets."""

from fastapi import APIRouter, Request

from sellerscope import __version__
from sellerscope.connectors.registry import ConnectorRegistry
from sellerscope.schemas.scans import Meta

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=Meta)
async def meta(request: Request) -> Meta:
    registry: ConnectorRegistry = request.app.state.connector_registry
    return Meta(
        environment=request.app.state.settings.app_env,
        version=__version__,
        mock_connector_enabled=registry.mock_enabled,
    )
