# CLAUDE.md — SellerScope

## Project rules (non-negotiable)
- Never fabricate seller counts, prices, seller identities or scan results. A missing value is stored as `null` with a reason or limitation code, and shown as "Not available". It is never `0`.
- `total_offer_count`, `observed_offer_count` and `unique_seller_count` are distinct metrics. Never derive one from another.
- Snapshot tables (`scan_results`, `product_offers`, `scan_history`, `audit_logs`) are append-only.
- Every tenant-owned table has `organization_id`. Every query is tenant-scoped. RLS is the backstop. Cross-tenant tests are required for new endpoints.
- Marketplace access only through authorized APIs. No scraping, no CAPTCHA/auth bypass. The extension reads only the URL.
- The mock connector is dev/test only, is labelled `MOCK`, and must not load in production.
- No secrets in code or frontend. Add new variables to `.env.example` with placeholders.
- Missing absence in a truncated or failed scan is *not* a seller disappearance (see the diff rules in docs/plan/02).

## Process
- Work milestone by milestone (docs/plan/08-milestones.md). Before a milestone: plan, dependencies, limitations, credentials, acceptance tests. After: run tests, fix, verify, update docs, report what's done and what remains.
- Don't mark incomplete functionality as finished.

## Scope
Amazon.in only (decided 2026-11-11). Flipkart is deferred. Keep connector code marketplace-agnostic, but don't build Flipkart features.

## Layout
- `apps/api`: FastAPI + Celery, package `sellerscope` under `src/`. Tests in `tests/unit` and `tests/integration` (marked `integration`).
- `apps/web`: Next.js 16 App Router, Tailwind 4. Screens live under `src/app/(app)/`. Nav is defined in `src/lib/navigation.ts`.
- Target structure: docs/plan/04-folder-structure.md.

## Database
- Models live in `apps/api/src/sellerscope/models/`. After changing them, run `make migration m="..."`, then review the generated file.
  - asyncpg allows **one SQL statement per `op.execute`**.
  - Autogenerate can't render circular FKs; add those with `op.create_foreign_key` after both tables exist.
- New tenant tables need: the `TenantOwned` mixin, `tenant_unique(...)`, `tenant_fk(...)` for same-tenant references, plus an RLS policy and grants in a migration. `test_every_tenant_table_has_rls_and_a_policy` enforces this.
- The API connects as the restricted app role. Always call `set_tenant_context()` inside the transaction before tenant queries.

## API conventions (M3)
- Use the dependencies in `sellerscope.auth.deps`:
  - `PrincipalDep` for the signed-in user (no org)
  - `OrgDep` for org-scoped routes (checks membership, sets tenant context)
  - `require(Permission.X)` for RBAC
  - `rate_limit(name, limit, window_s)` for per-user limits
- **New routes:**
  - Org-scoped routes are covered by the cross-tenant matrix automatically (`tests/integration/test_cross_tenant.py`).
  - Non-org routes must be added to `NON_ORG_ROUTES` deliberately.
  - Return 404 (not 403) for other tenants' resources.
- Record security-relevant changes with `services.audit.record(...)` in the same transaction.
- Send emails only after commit. Report delivery failures; don't swallow them.
- Web data fetching uses TanStack Query. Tenant data query keys start with `["tenant", orgId, ...]`.

## Commands
- `make test-e2e`: browser end-to-end test on a throwaway stack (uses a test-only auth stub; see apps/web/e2e/README.md)
- `make migrate`: apply migrations as the owner (`MIGRATION_DATABASE_URL`)
- `make install`, `make lint`, `make typecheck`, `make test`, `make build-web`
- Backend only: `cd apps/api && uv run pytest`. Integration tests need `TEST_DATABASE_URL` and `TEST_REDIS_URL`.
- Web only: `pnpm web:test`, `pnpm web:lint`, `pnpm web:typecheck`

## Conventions
- Python: ruff (line length 100), mypy strict, Pydantic v2, async SQLAlchemy 2. Errors are RFC 9457 problem+json via `AppError`.
- TS: strict + `noUncheckedIndexedAccess`. Use `MetricTile` with `value={null}` for unavailable metrics.
