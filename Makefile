# SellerScope developer commands. Run `make help`.
API := apps/api
TEST_DATABASE_URL ?= postgresql+asyncpg://sellerscope:sellerscope@127.0.0.1:5432/sellerscope_test
TEST_REDIS_URL ?= redis://127.0.0.1:6379/15

.PHONY: help install up down migrate migration api worker web lint typecheck test test-api test-web build-web

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Install Python and JS dependencies
	cd $(API) && uv sync
	pnpm install

up: ## Start the full stack in Docker
	docker compose up --build -d

down: ## Stop the Docker stack
	docker compose down

migrate: ## Apply database migrations (uses MIGRATION_DATABASE_URL)
	cd $(API) && uv run alembic upgrade head

migration: ## Create a migration: make migration m="describe change"
	cd $(API) && uv run alembic revision --autogenerate -m "$(m)"

api: ## Run the API locally with reload
	cd $(API) && uv run uvicorn sellerscope.asgi:app --reload --port 8000

worker: ## Run a Celery worker locally
	cd $(API) && uv run celery -A sellerscope.workers.celery_app worker -Q default,imports,scans.amazon,reports,alerts --loglevel=INFO

web: ## Run the web app locally
	pnpm web:dev

lint: ## Lint everything
	cd $(API) && uv run ruff check . && uv run ruff format --check .
	pnpm web:lint

typecheck: ## Type-check everything
	cd $(API) && uv run mypy src
	pnpm web:typecheck

test: test-api test-web ## Run all tests

test-api: ## Backend tests (integration tests need Postgres + Redis)
	cd $(API) && TEST_DATABASE_URL=$(TEST_DATABASE_URL) TEST_REDIS_URL=$(TEST_REDIS_URL) uv run pytest

test-web: ## Frontend unit tests
	pnpm web:test

build-web: ## Production build of the web app
	pnpm web:build
