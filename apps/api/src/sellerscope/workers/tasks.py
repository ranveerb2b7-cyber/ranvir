import asyncio
import uuid

from sellerscope.core.config import get_settings
from sellerscope.db.session import create_engine, create_session_factory
from sellerscope.storage import create_storage
from sellerscope.uploads.dispatch import IMPORTS_QUEUE, PARSE_TASK
from sellerscope.workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """Round-trip check used by tests and ops tooling."""
    return "pong"


async def _parse(organization_id: str, batch_id: str) -> str:
    from sellerscope.uploads.service import parse_batch

    settings = get_settings()
    engine = create_engine(settings)
    try:
        return await parse_batch(
            create_session_factory(engine),
            create_storage(settings),
            settings,
            organization_id=uuid.UUID(organization_id),
            batch_id=uuid.UUID(batch_id),
        )
    finally:
        await engine.dispose()


@celery_app.task(name=PARSE_TASK, queue=IMPORTS_QUEUE, acks_late=True)
def parse_upload(organization_id: str, batch_id: str) -> str:
    """Parses an uploaded product file. Failures are recorded on the batch itself."""
    return asyncio.run(_parse(organization_id, batch_id))
