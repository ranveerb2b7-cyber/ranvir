"""How the API and beat hand work to background workers (swappable in tests)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

PARSE_TASK = "uploads.parse"
IMPORTS_QUEUE = "imports"
SCAN_TASK = "scans.run_job"
SCANS_QUEUE = "scans.amazon"


class TaskDispatcher(Protocol):
    async def parse_upload(self, organization_id: uuid.UUID, batch_id: uuid.UUID) -> None: ...

    async def run_scan_job(
        self, organization_id: uuid.UUID, job_id: uuid.UUID, countdown_s: float = 0
    ) -> None: ...


class CeleryDispatcher:
    async def _send(self, name: str, args: list[str], queue: str, countdown: float = 0) -> None:
        from sellerscope.workers.celery_app import celery_app

        await asyncio.to_thread(
            celery_app.send_task, name, args=args, queue=queue, countdown=countdown or None
        )

    async def parse_upload(self, organization_id: uuid.UUID, batch_id: uuid.UUID) -> None:
        await self._send(PARSE_TASK, [str(organization_id), str(batch_id)], IMPORTS_QUEUE)

    async def run_scan_job(
        self, organization_id: uuid.UUID, job_id: uuid.UUID, countdown_s: float = 0
    ) -> None:
        await self._send(SCAN_TASK, [str(organization_id), str(job_id)], SCANS_QUEUE, countdown_s)
