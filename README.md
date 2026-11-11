# SellerScope

Marketplace seller mapping and intelligence SaaS for brand owners and manufacturers. It monitors the sellers offering their products on **Amazon India**.

## Current status

| | |
|---|---|
| Scope | **Amazon.in only.** Flipkart deferred. |
| Done | M0 planning, M1 monorepo foundation (health checks, worker skeleton, dashboard shell, CI) |
| Next | M2 database schema |

No business features are complete yet. See [`docs/plan/08-milestones.md`](docs/plan/08-milestones.md) for progress and [`docs/plan/`](docs/plan/README.md) for the design.

## Coverage statement

- **Amazon.in:** via the official Selling Partner API, using each customer's own Seller Central authorization. The API reports a total offer count and up to ~20 individual offers per ASIN. Seller names are not provided by the API. *(Pending verification with live credentials in M7.)*
- **Flipkart:** not supported. No authorized API is known to provide competitor seller data ([report](docs/plan/07-flipkart-feasibility.md)).

SellerScope never fabricates seller counts, prices or seller identities. Unavailable data is shown as unavailable.

## Repository layout

```
apps/api   FastAPI API + Celery workers (Python 3.12+, uv)
apps/web   Next.js 16 dashboard (TypeScript, Tailwind 4)
docs/plan  Architecture, ERD, API plan, feasibility, milestones, security
```

## Local development

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22, pnpm 10, and either Docker or local PostgreSQL 16 + Redis 7.

Full stack in Docker:

```bash
cp .env.example .env
```

```bash
make up
```

API: http://localhost:8000/docs · Web: http://localhost:3000 · Mail: http://localhost:8025

Without Docker (services running locally):

```bash
make install
```

```bash
make api      # API on :8000
```

```bash
make worker   # Celery worker
```

```bash
make web      # web on :3000
```

Checks:

```bash
make lint typecheck test
```

Backend integration tests need `TEST_DATABASE_URL` and `TEST_REDIS_URL`. The Makefile defaults to a local `sellerscope_test` database and Redis DB 15. In CI, integration tests are required to run.

## API

- `GET /api/v1/health/live`: process liveness
- `GET /api/v1/health/ready`: PostgreSQL + Redis readiness (503 if degraded)

OpenAPI: `/api/v1/openapi.json` (disabled in staging/production). The full endpoint plan is in [`docs/plan/05-api-endpoints.md`](docs/plan/05-api-endpoints.md).
