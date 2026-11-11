from sellerscope.workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """Round-trip check used by tests and ops tooling."""
    return "pong"
