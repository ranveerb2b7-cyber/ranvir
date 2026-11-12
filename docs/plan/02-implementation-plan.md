# 2. Technical Implementation Plan

Status: **PROPOSAL — awaiting approval.**

## 2.1 Development environment (inspected 2026-11-11)

| Tool | Version found | Note |
|---|---|---|
| Python | 3.13 | Target 3.12+ (pin 3.12 in Docker for broad wheel support; 3.13 OK locally) |
| uv / Poetry | 0.11 / 2.4 | Use **uv** |
| Node / pnpm | 22 / 10.28 | Node 22 LTS, pnpm workspaces |
| PostgreSQL | 16 (native binaries) | Used directly for tests in this sandbox |
| Redis | 7.0 (native) | Same |
| Docker | CLI 29.9, **daemon not running** in this sandbox | docker-compose is still authored and is the standard for developer machines and CI; it can't be exercised in this cloud session |
| Network | PyPI and npm reachable | Marketplace APIs aren't called without credentials |

**This session can't push to `ranveerb2b7-cyber/ranvir`** (the repo was cloned read-only). Work is committed locally until write access is granted.

## 2.2 Cross-cutting conventions

- **IDs:** UUIDv7 (time-ordered) primary keys, generated in Python.
- **Timestamps:** `timestamptz`, UTC. `created_at` / `updated_at` on every table, and `deleted_at` (soft delete) where the user can delete.
- **Money:** `numeric(12,2)` + `currency char(3)` (INR). Never float.
- **Enums:** Postgres `text` + CHECK constraints (simpler migrations than native enums), mirrored as Python `StrEnum`.
- **Errors:** RFC 9457 `application/problem+json` with stable `code` strings.
- **Pagination:** cursor-based (`?cursor=&limit=`) for large append-only tables (history, audit). **The product list uses page/page_size with a total count** (decided in M4): the UI needs page numbers and totals, and product counts are bounded by the plan limit. Sort and filter parameters are whitelisted.
- **Validation:** Pydantic v2 for every request and response. No `dict` passthrough.
- **Testing pyramid:** unit tests (pure parsing/diff/validators), integration tests (API + real Postgres + Redis, connector tests against recorded fixtures via `respx`), contract tests (OpenAPI snapshot), e2e tests (Playwright for critical paths).
- **Fixtures** recorded from real API responses are stored **only** under `tests/fixtures`, with identifying data scrubbed. They are never loaded at runtime.

## 2.3 Scanning engine details

- **Job state machine:** `queued → running → (completed | completed_with_errors | failed | cancelled)`. Items: `pending → processing → (completed | partial | unavailable | failed | cancelled)`, plus a `retry_count` and `next_attempt_at`.
- **Concurrency guard:** partial unique index `scan_job_items(product_id) WHERE status IN ('pending','processing')`, plus a Redis lock per product while it is being fetched.
- **Rate limiting:** a Redis Lua token bucket per `(connector, credential_id)`, seeded from the documented rate and adjusted from the `x-amzn-RateLimit-Limit` response header when present.
- **Retry policy:** exponential backoff `min(cap, base·2^n) + jitter`, base 2 s, cap 5 min, max 6 attempts for 429/5xx/network errors. Errors that are not retryable (invalid ASIN, 403 role missing) fail immediately with a reason code.
- **Cancellation:** only `pending` items are cancellable. An in-flight item finishes (its result is real data) and is then marked `cancelled` at job level.
- **Stale-job reaper (beat):** items stuck in `processing` beyond a visibility timeout go back to `pending`. This is idempotent because results are keyed by `(scan_job_item_id)`.
- **Scheduling:** per-product or per-org monitoring frequency (e.g., daily) via beat. Quotas come from the subscription.

## 2.4 Seller intelligence and diff rules

These are stored separately for every snapshot:
- `total_offer_count` is what the marketplace **reports** exists (may be `null`).
- `observed_offer_count` is how many individual offers we **actually received**.
- `unique_seller_count` is the number of distinct seller IDs among observed offers.
- `is_offer_list_truncated` is true when total > observed or observed == the connector's cap.

**Diff engine.** It compares a new snapshot with the latest previous snapshot for the same product where `status in (ok, partial)`.

| Situation | Event recorded |
|---|---|
| Seller in new, not in previous | `seller_newly_observed` |
| Seller in previous, absent in new, **and the new list is complete (not truncated)** | `seller_no_longer_observed` |
| Seller absent but the new list is truncated, or the scan failed | `seller_not_observed_inconclusive` (not shown as "disappeared") |
| `total_offer_count` changed | `offer_count_changed` (old, new) |
| Same seller, price changed | `price_changed` (old, new) |
| Scan failed or unavailable | No seller events; previous state is kept as "last known", with its age shown |

**Seller detection confidence:**
- `high` means the seller ID is present in a complete list.
- `medium` means the seller ID is present but the list is truncated.
- `low` means the seller was seen only in an older snapshot.

**Implementation notes (M8):**
- **Comparison baseline:** the previous *usable* snapshot (`ok`/`partial`). Failed scans are never diffed. The first usable snapshot is a baseline with no events.
- **When "unavailable" is recorded:** `scan_unavailable` is emitted once, on the transition from usable data to no data, not on every scan while data stays unavailable.
- **Unknown completeness:** a list whose completeness is unknown is treated like a truncated one, so an absence there is inconclusive, never "gone".
- **Seller events require known seller ids:** both snapshots must have seller ids for every offer (`unique_seller_count` not null).

## 2.5 Frontend plan

- Route groups `(auth)` and `(app)`. The app shell has a sidebar with the 9 navigation items from the spec, an org switcher, and the user menu.
- **Every metric** has an info tooltip with source, timestamp and completeness. `null` renders as "Not available" with the reason, never `0`.
- The product table is server-side paginated, sorted and filtered (TanStack Table), with URL-synced filters and the 10 required columns.
- Mock data shows a non-dismissible red banner.
- Accessibility: keyboard navigable, WCAG AA contrast. Responsive down to 360 px (the table collapses to cards).

## 2.6 Deployment target (proposal)

- Containers on AWS: ECS Fargate or Fly.io / Render for an early stage. RDS PostgreSQL, ElastiCache Redis, S3, KMS.
- Hosting should be in **ap-south-1 (Mumbai)**: the customers are in India, and this helps with India's DPDP Act data-residency expectations.
- Web on Vercel or as a container.
- Supabase: hosted project in the Mumbai region, or self-hosted GoTrue.
- Environments: `development`, `staging`, `production`, with separate credentials and SP-API apps (or at least separate LWA clients).
