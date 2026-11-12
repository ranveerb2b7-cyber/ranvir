# SellerScope

Marketplace seller mapping and intelligence SaaS for brand owners and manufacturers. It monitors the sellers offering their products on **Amazon India**.

## Current status

| | |
|---|---|
| Scope | **Amazon.in only.** Flipkart deferred. |
| Done | M0 planning, M1 foundation, M2 database schema (RLS isolation), M3 authentication, organizations, team & roles, M4 product management & dashboard, M5 Excel/CSV upload, M6 scanning engine, M8 seller intelligence & change history, M10 alerts (in-app + email), M11 reports (Excel/CSV exports), M12 Chrome extension, M14 production hardening (partly: cloud parts not applied; see docs/plan/08) (MOCK data until M7) |
| Next | M7 Amazon SP-API connector (waiting for credentials) |

No business features are complete yet. See [`docs/plan/08-milestones.md`](docs/plan/08-milestones.md) for progress and [`docs/plan/`](docs/plan/README.md) for the design.

## Coverage statement

- **Amazon.in:** via the official Selling Partner API, using each customer's own Seller Central authorization. The API reports a total offer count and up to ~20 individual offers per ASIN. Seller names are not provided by the API. *(Pending verification with live credentials in M7.)*
- **Flipkart:** not supported. No authorized API is known to provide competitor seller data ([report](docs/plan/07-flipkart-feasibility.md)).

SellerScope never fabricates seller counts, prices or seller identities. Unavailable data is shown as unavailable.

## Authentication setup

| Environment | Auth provider | API settings |
|---|---|---|
| Local | GoTrue container (docker-compose) | `AUTH_JWT_ISSUER=http://localhost:54321/auth/v1`, `AUTH_JWT_SECRET` (same value GoTrue signs with) |
| Staging / production | Hosted Supabase project (Mumbai region) | `AUTH_JWT_ISSUER=https://<ref>.supabase.co/auth/v1`, `AUTH_JWKS_URL=https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` |

The web app needs `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`, the public key. They're compiled into the browser bundle at build time.

## Repository layout

```
apps/api   FastAPI API + Celery workers (Python 3.12+, uv)
apps/web   Next.js 16 dashboard (TypeScript, Tailwind 4)
apps/extension  Chrome MV3 extension (see apps/extension/README.md)
docs/plan  Architecture, ERD, API plan, feasibility, milestones, security, ASVS + compliance checklists
docs/runbooks  Deploy, backup/restore, incidents, observability, load testing, secrets
infra/terraform  AWS ap-south-1 (validated, not yet applied)
ops  Backup/restore drill and load-test scripts
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

Web: http://localhost:3000 · API docs: http://localhost:8000/docs · Mail (Mailpit): http://localhost:8025 · Auth (local GoTrue): http://localhost:54321/auth/v1

Sign-up sends a confirmation email to Mailpit. Open it there to activate the account.

To try scanning before Amazon credentials exist, set `ENABLE_MOCK_CONNECTOR=true` in `.env`. This is development only: every page then shows a red MOCK DATA banner, and staging/production refuse to start with it.

Without Docker (services running locally; create the app role first, as `infra/docker/postgres/init/01-app-role.sh` does):

```bash
make install
```

```bash
make migrate  # as the schema owner (MIGRATION_DATABASE_URL)
```

```bash
make api      # API on :8000
```

```bash
make worker   # Celery worker (required: it processes uploaded files)
```

```bash
make web      # web on :3000
```

Checks:

```bash
make lint typecheck test
```

Browser end-to-end test (needs local Postgres + Redis + Playwright; see `apps/web/e2e/README.md`):

```bash
make test-e2e
```

Backend integration tests need `TEST_DATABASE_URL` (a user with CREATEROLE; the tests drop and recreate the `public` schema of that database) and `TEST_REDIS_URL`. The Makefile defaults to a local `sellerscope_test` database and Redis DB 15. In CI, integration tests are required to run.

## API

- `GET /api/v1/health/live`, `GET /api/v1/health/ready`
- `GET|PATCH /api/v1/me`
- `POST /api/v1/organizations`, `GET|PATCH|DELETE /api/v1/organizations/current`, `POST /api/v1/organizations/current/transfer-ownership`
- `GET /api/v1/members`, `PATCH|DELETE /api/v1/members/{user_id}`, `DELETE /api/v1/members/me`
- `GET|POST /api/v1/invitations`, `POST /api/v1/invitations/{id}/resend`, `DELETE /api/v1/invitations/{id}`, `POST /api/v1/invitations/preview`, `POST /api/v1/invitations/accept`

- `GET|POST /api/v1/products`, `POST /api/v1/products/validate`, `POST /api/v1/products/bulk`, `GET|PATCH|DELETE /api/v1/products/{id}`, `GET /api/v1/brands`
- `GET /api/v1/dashboard/summary`
- `POST /api/v1/scan-jobs`, `GET /api/v1/scan-jobs`, `GET /api/v1/scan-jobs/quota`, `GET /api/v1/scan-jobs/{id}`, `GET /api/v1/scan-jobs/{id}/items`, `POST /api/v1/scan-jobs/{id}/cancel`, `POST /api/v1/scan-jobs/{id}/retry-failed`, `GET /api/v1/meta`
- `GET /api/v1/sellers`, `GET /api/v1/sellers/compare`, `GET|PATCH /api/v1/sellers/{id}`, `GET /api/v1/changes`
- `GET /api/v1/products/{id}/offers`, `/scans`, `/history`, `/trends`
- `GET /api/v1/uploads/template`, `GET|POST /api/v1/uploads`, `GET /api/v1/uploads/{id}`, `GET /api/v1/uploads/{id}/rows`, `POST /api/v1/uploads/{id}/commit`, `POST /api/v1/uploads/{id}/discard`, `GET /api/v1/uploads/{id}/rejected.csv`

Authentication: `Authorization: Bearer <Supabase access token>`. Organization-scoped endpoints also need `X-Organization-Id`.

OpenAPI: `/api/v1/openapi.json` (disabled in staging/production). The full endpoint plan is in [`docs/plan/05-api-endpoints.md`](docs/plan/05-api-endpoints.md).
