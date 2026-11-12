"""How the API hands work to background workers (swappable in tests)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

PARSE_TASK = "uploads.parse"
IMPORTS_QUEUE = "imports"


class TaskDispatcher(Protocol):
    async def parse_upload(self, organization_id: uuid.UUID, batch_id: uuid.UUID) -> None: ...


class CeleryDispatcher:
    async def parse_upload(self, organization_id: uuid.UUID, batch_id: uuid.UUID) -> None:
        from sellerscope.workers.celery_app import celery_app

        await asyncio.to_thread(
            celery_app.send_task,
            PARSE_TASK,
            args=[str(organization_id), str(batch_id)],
            queue=IMPORTS_QUEUE,
        )
