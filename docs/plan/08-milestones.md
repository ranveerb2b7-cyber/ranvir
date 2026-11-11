# 8. Development Milestones

Status: **Approved, Amazon-only scope (2026-11-11).** Each milestone follows the same loop. Before starting: plan → dependencies → limitations → credentials → acceptance tests. After finishing: run tests → fix → verify → update docs → report what is complete and what remains. A milestone is only "done" when its acceptance tests pass in CI.

| # | Milestone | Key deliverables | Acceptance tests (summary) | Credentials needed |
|---|---|---|---|---|
| **M0** ✅ | Planning (this) | Architecture, ERD, API plan, feasibility reports | Your approval | — |
| **M1** ✅ | Monorepo foundation | Folder structure, uv + pnpm workspaces, docker-compose (pg, redis, minio, mailpit, auth), Makefile, CI (lint/type/test), `.env.example`, README, CLAUDE.md, health endpoints, Next.js shell | `make test` green; CI green; `/health/ready` checks DB + Redis; web builds; compose file validates | none |
| **M2** ✅ | Database schema | SQLAlchemy models + Alembic migrations for all tables, RLS policies, DB roles, append-only triggers, seed of `marketplaces` / `plans` | Migrations up/down on empty DB; RLS test: the app role can't read another org's rows even without a WHERE clause; UPDATE on `scan_results` is rejected; unique/partial indexes enforced | none |
| **M3** ✅ | Auth + orgs + RBAC | Supabase JWT verification, `/me`, org creation, invitations, member management, permission dependency, audit log writes, API rate limiting; web login/register/forgot/reset/accept-invite pages, org switcher, Team page | Invalid/expired JWT → 401; viewer can't write → 403; cross-org access → 404 for **every** tenant endpoint (generated test matrix); invite flow e2e; password reset e2e (Mailpit) | Supabase project URL + anon key + JWT secret/JWKS (or local GoTrue) |
| **M4** | Initial dashboard + product management | App shell with 9 nav items, product CRUD, ASIN/FSN validators, duplicate detection, product table (search/filter/sort/pagination), brand filter, bulk actions, KPI tiles wired to real (initially empty) data | Validator unit tests (valid/invalid/edge cases); duplicate → 409; table query tests; Playwright: add product, filter, paginate; empty states say "No scans yet", never 0 | none |
| **M5** | Uploads | Template download, upload with size/type/magic-byte checks, async parse, preview accepted/rejected rows, dedupe (in file + existing), commit, history, rejected-rows CSV | Fixture files: valid, mixed, malformed, oversize, wrong type, macro-enabled `.xlsm` rejected, 50k rows within time budget; formula-injection-safe exports | none |
| **M6** | Scanning engine + connector interfaces | Connector protocol and registry, **MockConnector (dev/test only, labelled)**, job/item state machine, Celery queues, token bucket, backoff, retries, cancellation, stale reaper, duplicate-scan guard, scan UI with live progress | Concurrency test: two scan requests for the same product → one 409; 429 → retried with backoff (fake clock); cancellation; production boot refuses the mock connector; failed items visible with reason | none |
| **M7** | Amazon connector | Spike (feasibility §6.7), LWA token handling, credential encryption (KMS/AES-GCM), OAuth connect flow (option A) + manual credentials (option B), getItemOffers(+Batch), catalog verification, parser, limitation codes, raw payload storage | Parser tests on recorded fixtures (1 seller, many sellers, >20 offers, not found, throttled); encryption round-trip + key rotation; live smoke test against a real account (manual, documented) | **Amazon seller account, SP-API developer registration, LWA client id/secret, refresh token** |
| **M8** | Seller intelligence + history | Seller profiles, offer views, comparison, confidence, diff engine, history timeline, trends charts | Diff engine table-driven tests incl. truncated lists and failed scans **not** producing disappearance events; metrics never conflated | (M7) |
| **M9** ⏸ deferred | Flipkart connector | Capability-limited connector, FSN validation, seller-API own-listing sub-connector and/or affiliate sub-connector **only if access is granted**, coverage messaging | Unavailable results recorded and displayed as unavailable; no competitor fields populated; capability-driven UI | Flipkart seller API app id/secret and/or affiliate credentials (optional) |
| **M10** | Alerts | Alert rules, evaluation after each scan, in-app alerts, email (via provider), signed webhooks | Rule evaluation unit tests; no alerts from inconclusive events unless the rule opts in | Email provider API key (e.g. SES/Postmark/Resend) |
| **M11** | Reports | Product, marketplace, brand, seller, scan-summary and errors/unavailable reports; XLSX + CSV async export; signed download URLs | Exports match DB queries; CSV injection escaped; unavailable values exported as blank + reason column, not 0 | S3/R2 bucket |
| **M12** | Chrome extension | MV3, URL-based ASIN/FSN detection, PKCE pairing, popup with stored data + timestamp, "Check now", dashboard deep link, token revocation | Detection unit tests on URL corpus; e2e with Playwright loading the unpacked extension against local pages; minimal permissions review | none (Chrome Web Store developer account for publishing) |
| **M13** | Subscriptions + billing | Plans, quotas enforcement, Razorpay (India) or Stripe checkout + webhooks, usage meters | Quota exceeded → 402 problem response; webhook signature verification; idempotent webhook handling | Razorpay/Stripe keys |
| **M14** | Production hardening | Observability, backups/PITR, IaC, staging env, load test, security review, pen-test fixes, DPDP/AUP compliance checklist, runbooks | Load test hits target throughput; restore-from-backup drill; OWASP ASVS L2 checklist | Cloud account (AWS ap-south-1 or similar), domain, KMS |

**Order rationale:** the scanning engine (M6) is built against the labelled mock connector, so it doesn't depend on Amazon credentials arriving. The Amazon connector (M7) can start as soon as you provide credentials.

## Progress

| Milestone | Status | Notes |
|---|---|---|
| M0 | ✅ Complete | Plan approved with Amazon-only scope |
| M1 | ✅ Complete | See "M1 report" below |
| M2 | ✅ Complete | See "M2 report" below |
| M3 | ✅ Complete (with stated limits) | See "M3 report" below |
| M9 | ⏸ Deferred | Flipkart out of current scope |
| Others | Not started | |

### M1 report (2026-11-11)

**Delivered**
- uv-managed FastAPI package (`apps/api`):
  - settings with a production guard against the mock connector
  - structured logging
  - RFC 9457 problem+json errors
  - request-ID and security-header middleware
  - CORS allow-list
  - `/api/v1/health/live` and `/api/v1/health/ready` (PostgreSQL + Redis, 503 when degraded)
  - OpenAPI docs disabled in staging/production
  - Celery app with the queues declared, plus a `system.ping` task
- Next.js 16 + Tailwind 4 web shell (`apps/web`):
  - responsive sidebar with the 9 required sections
  - Dashboard KPI tiles that render "Not available" (never 0) until real data exists
  - other screens show an explicit "not built yet (milestone X)" notice
- Dockerfiles for api and web, `docker-compose.yml` (postgres, redis, minio, mailpit, api, worker, beat, web), `Makefile`, `.env.example`, GitHub Actions CI. CI fails if integration tests are skipped.

**Verified**
- `make lint`, `make typecheck`: clean.
- `make test`: 15 backend tests (incl. integration against real PostgreSQL 16 + Redis 7) and 5 frontend tests pass.
- A real Celery worker processed `system.ping` through Redis.
- `next build` succeeds. Screenshots checked at 1280 px and 375 px (no horizontal scroll).
- `docker compose config` validates.

**Not verified / remaining**
- `docker compose up` could not be run: no Docker daemon in the build sandbox. It must be run on a developer machine or in CI.
- The CI workflow has not run on GitHub yet; it will on the next push.
- No database schema, auth, or business features yet. These are M2+.

### M2 report (2026-11-11)

**Delivered**
- SQLAlchemy 2 models for all 22 tables (`apps/api/src/sellerscope/models/`).
- Alembic, with three migrations:
  - `0001` schema
  - `0002` security layer (app-role grants, RLS policies, append-only and `updated_at` triggers)
  - `0003` seed data (Amazon.in marketplace; a trial plan with **provisional** limits, flagged `features.provisional = true`)
- Same-tenant composite foreign keys, so a row can't reference another org's row even without RLS.
- Partial unique indexes:
  - one live product per ASIN per org
  - one active scan item per product
  - one live subscription per org
  - one pending invite per email
- `set_tenant_context()` helper (transaction-local settings, safe with connection pooling).
- Docker: the app-role init script, a one-off `migrate` service, and the API/worker connecting as the restricted role. New `make migrate` / `make migration` targets.

**Verified**
- 43 backend tests pass (17 unit, 26 integration against real PostgreSQL 16 + Redis), covering:
  - migrations down to base and back up
  - models and migrations in sync (autogenerate diff is empty)
  - every table with `organization_id` has RLS enabled plus a policy (a meta-test, so future tables can't skip it)
  - the app role is not superuser, can't bypass RLS, owns nothing, and can't UPDATE/DELETE/TRUNCATE snapshots
  - RLS hides and protects another org's rows with no WHERE clause, blocks inserts into another org, and returns nothing without context
  - tenant context doesn't leak across transactions on a pooled connection
  - org-switcher visibility of the user's own memberships
  - composite FKs block cross-tenant references, even for the owner
  - the append-only trigger blocks the owner too, with the purge flag as the only exception
  - duplicate products and concurrent scans are rejected
  - CHECK constraints work, including unknown metrics stored as NULL (not 0)
  - the `updated_at` trigger
- End to end on a fresh database: the init script creates the role, then `alembic upgrade head`, then the API reports `/health/ready` OK as the restricted role. The role gets `permission denied` on CREATE TABLE.
- ruff and mypy (strict) are clean.

**Not verified / remaining**
- `docker compose up` (no Docker daemon in the build sandbox); the compose file validates.
- Trial plan limits are placeholders until pricing is decided (M13).
- Cross-tenant paths for invitation acceptance (M3) and the scheduler (M6) are designed but not built (see 03-database-design §3.4).

### M3 report (2026-11-11)

**Delivered: backend**
- **Access-token verification:** JWKS (RS256/ES256) or HS256 secret, plus strict claim checks. Staging/production refuse to start without an auth configuration.
- **First-login user sync.** `X-Organization-Id` membership check: non-members and suspended members get 404.
- **RBAC** via `require(Permission)`, with the role matrix unit-tested against the architecture doc.
- **Organizations:** create (owner plus trial subscription), get, rename, soft-delete.
- **Members:** list, change role/status, remove, leave, ownership transfer, with guard rails: the owner is untouchable except through transfer, and you can't edit yourself.
- **Invitations:** create, resend, revoke, preview, accept.
  - Tokens are 256-bit; only the SHA-256 is stored.
  - Acceptance requires the invitation email to match the signed-in user's email.
  - Acceptance runs through `SECURITY DEFINER` functions (migration `0004`).
- **Invitation emails** go over SMTP and are sent only after the invitation is committed. A failed delivery is reported (`email_sent: false`), not hidden.
- **Audit log** entries for every org, member and invitation change.
- **Redis rate limits:** per IP globally, plus per verified user on sensitive endpoints. They fail open if Redis is down, and that is logged.

**Delivered: web**
- Supabase SSR client and `proxy.ts` route protection with safe `?next=` redirects.
- Pages: login, register, forgot password, reset password, `/auth/callback` (PKCE code exchange), onboarding (create organization), accept invitation (with a wrong-account message), organization switcher, user menu and sign-out.
- **Team page:** invite, role change, remove, make owner, pending invites with resend/cancel. It is read-only for analysts and viewers.
- **Settings page:** profile, organization name, leave, delete.
- TanStack Query for data fetching.

**Delivered: local stack**
- docker-compose `auth` (`supabase/gotrue:v2.197.0`) on its own `auth` database, behind an nginx `auth-gateway` that serves it at `/auth/v1` on port 54321 like hosted Supabase.
- Mailpit receives both GoTrue's emails and SellerScope's invitation emails.

**Verified**
- **Backend: 100 tests pass** (ruff and mypy strict clean). They include:
  - 17 token tests (valid HS256, expired, wrong key/aud/iss, `alg: none`, anon/service_role/anonymous, missing email/exp, ES256 via a real JWKS HTTP endpoint, HS256 rejected when only JWKS is configured).
  - The full invitation lifecycle, RBAC per role, member rules, and 429 with `Retry-After`.
  - SMTP delivery to a real SMTP server.
  - **Cross-tenant matrix:** every organization-scoped route (12, discovered from the app and cross-checked against OpenAPI) returns 404 for non-members and for foreign resource ids, and the victim org's data is unchanged afterwards. A planted bug (membership check removed) made the matrix fail as expected.
  - A meta-test fails if a new route is neither org-scoped nor explicitly allow-listed.
- **Web:** 20 unit tests pass (open-redirect guard, error parsing, Team page role visibility). Lint, typecheck and production build are clean.
- **Browser end-to-end** (`make test-e2e`, also added to CI): 11 steps pass against the real API, a fresh database, real SMTP delivery and the production web build:
  - sign-up, then onboarding, then invite by email, then the invitee registers and accepts
  - analyst read-only view
  - an accepted link can't be reused
  - role change
  - second organization, switcher and isolation
  - rename
  - mobile layout (no horizontal scroll)
- **Bugs the e2e run found and fixed:**
  - a stale cached "no organizations" answer bounced users back to onboarding
  - a squashed role selector on mobile

**Not verified / remaining**
- **Real Supabase Auth was not exercised.** Building GoTrue from source in the sandbox was blocked by policy, and Docker isn't available. The e2e run used a test-only stand-in (`apps/web/e2e/stub-auth.mjs`). Still unchecked: email confirmation, the PKCE callback, the real password-reset email flow, and GoTrue rate limits. Check these with `make up` + Mailpit, or a staging Supabase project.
- **The GoTrue image tag `v2.197.0`** is taken from the auth repository's changelog and hasn't been pulled. The compose `auth` and `auth-gateway` services are written but haven't been run.
- **Planned for later:** MFA for owners/admins is a Supabase project setting, to configure at deployment (M14). Org purge after soft-delete is part of the retention work (M14). The `/auth/session/revoke` endpoint arrives with extension tokens (M12).
