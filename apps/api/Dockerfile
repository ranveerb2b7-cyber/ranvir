# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
RUN useradd --system --uid 10001 app && mkdir -p /data/storage && chown app /data/storage
COPY --from=deps /app/.venv /app/.venv
COPY pyproject.toml uv.lock alembic.ini* ./
COPY src ./src
RUN uv sync --frozen --no-dev && chown -R app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
# Same image runs the worker/beat with a different command (see docker-compose.yml).
CMD ["uvicorn", "sellerscope.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
