"""Celery application. Queues are declared up front; tasks are added in later milestones."""

from __future__ import annotations

from celery import Celery
from kombu.entity import Queue

from sellerscope.core.config import get_settings

QUEUES = ("default", "imports", "scans.amazon", "reports", "alerts")


def create_celery() -> Celery:
    settings = get_settings()
    redis_url = settings.redis_url.get_secret_value()
    app = Celery(
        "sellerscope",
        broker=redis_url,
        backend=redis_url,
        include=["sellerscope.workers.tasks"],
    )
    app.conf.update(
        task_default_queue="default",
        task_queues=[Queue(q) for q in QUEUES],
        task_acks_late=True,  # a crashed worker's task is redelivered, not lost
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_expires=3600,
        timezone="UTC",
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        beat_schedule={
            "schedule-due-scans": {"task": "scans.schedule_due", "schedule": 15 * 60.0},
            "recover-stale-work": {"task": "maintenance.recover_stale", "schedule": 5 * 60.0},
        },
    )
    return app


celery_app = create_celery()
