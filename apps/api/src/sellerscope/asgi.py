"""ASGI entrypoint: `uvicorn sellerscope.asgi:app`."""

from sellerscope.main import create_app

app = create_app()
