# 1. System Architecture

Status: **PROPOSAL — awaiting approval.** Nothing in this document is implemented yet.

## 1.1 Guiding principles

1. **Truthful data only.** Every number shown to a customer comes from a named source, carries a timestamp, and carries a completeness flag. When we don't have a value, we store and display `null` + a reason. We never fill it in or guess.
2. **Connectors are isolated plugins.** Amazon and Flipkart have very different (and differently-restricted) data access. Each lives behind one `MarketplaceConnector` interface and declares its own capabilities, so the scanning engine never assumes a field exists.
3. **Tenant isolation is enforced twice.** First in the application layer (every query is scoped by `organization_id`), then in PostgreSQL Row-Level Security as a backstop.
4. **Snapshots are append-only.** A scan never updates a previous scan's results. "Current state" is a pointer to the latest snapshot.
5. **Compliance before features.** No scraping, CAPTCHA solving, login automation or access-control bypass, by the backend or by the Chrome extension.

## 1.2 High-level component diagram

```
                       ┌───────────────────────────────┐
                       │   Supabase Auth (GoTrue)      │
                       │   identities, passwords,      │
                       │   password recovery, JWTs     │
                       └──────────────┬────────────────┘
                                      │ JWT (RS256/ES256, JWKS)
 ┌───────────────┐   HTTPS   ┌────────▼─────────────────────────────┐
 │ Next.js web   │──────────▶│ FastAPI  (apps/api)                   │
 │ (apps/web)    │  Bearer   │  • /api/v1 REST, OpenAPI docs         │
 └───────────────┘   JWT     │  • AuthN (JWT verify) + RBAC          │
 ┌───────────────┐           │  • Tenant context → Postgres RLS      │
 │ Chrome ext.   │──────────▶│  • Upload parsing/validation          │
 │ MV3           │ ext token │  • Rate limiting (Redis)              │
 │ (apps/ext)    │           │  • Audit logging                      │
 └───────────────┘           └──────┬──────────────┬─────────────────┘
                                    │ SQLAlchemy   │ enqueue (Celery)
                             ┌──────▼─────┐   ┌────▼──────┐
                             │ PostgreSQL │   │  Redis    │ broker, result
                             │ 16 + RLS   │   │           │ backend, rate-limit
                             └──────▲─────┘   └────┬──────┘ buckets, locks
                                    │              │
                             ┌──────┴──────────────▼─────────────────┐
                             │ Celery workers (apps/api, same code)  │
                             │  queues: scans.amazon, scans.flipkart,│
                             │  imports, reports, alerts, default    │
                             │ Celery beat: scheduled re-scans,      │
                             │  stale-job reaper, token refresh      │
                             └──────┬──────────────┬─────────────────┘
                                    │              │
                         ┌──────────▼───┐   ┌──────▼──────────────────┐
                         │ Amazon       │   │ Flipkart connector      │
                         │ SP-API       │   │ (capability-limited;    │
                         │ (EU region,  │   │  see feasibility report)│
                         │  A21TJRUUN4KGV)│ └─────────────────────────┘
                         └──────────────┘
          Object storage (S3-compatible): uploaded files, generated reports,
          raw connector payloads (for audit / re-parsing). Encrypted at rest.
```

## 1.3 Main runtime flows

### Upload → products
1. Web uploads a file to `POST /uploads`. The API checks size, extension, MIME type and magic bytes, then stores the file in object storage and creates a `product_batches` row (`status=uploaded`).
2. The `imports` worker parses it with `openpyxl` (read-only mode, no macros, no formulas evaluated) or the `csv` module. Each row becomes a `product_batch_rows` record with a status of `valid`, `invalid` or `duplicate` and a reason.
3. The user previews accepted and rejected rows, then confirms. Products are created or upserted, keyed on `(organization_id, marketplace_id, external_id)`.

### Scan
1. `POST /scan-jobs` with product IDs or a filter. The API checks the subscription quota and takes a Redis lock plus a DB partial unique index, so there's never more than one active scan per product. It creates a `scan_jobs` row plus one `scan_job_items` row per product.
2. The dispatcher enqueues items onto the queue for that marketplace. Workers acquire a token from a **Redis token bucket keyed by credential** (SP-API limits apply per selling-partner + app). If the connector supports batching, the worker groups items.
3. The connector returns a typed `OfferSnapshot` with `completeness` and `limitations[]`. The worker writes `scan_results` + `product_offers` (append-only), upserts `seller_profiles`, then runs the **diff engine** against the previous *comparable* snapshot and writes `scan_history` change events. If any rules match, it raises `alerts`.
4. Failures: HTTP 429 and 5xx retry with exponential backoff and jitter, honouring `Retry-After` and rate-limit headers. 4xx errors fail the item with a recorded reason. Nothing fails silently: each item ends as `completed`, `partial`, `failed`, `unavailable` or `cancelled`.

### Extension check
The extension parses the ASIN or FSN **from the URL only** and calls `GET /extension/lookup`. That returns the last stored snapshot and its timestamp. If the user clicks "Check now", it calls `POST /extension/check`, which enqueues a normal scan through the official connector. The extension never extracts marketplace page data.

## 1.4 Technology choices (and why)

| Concern | Choice | Rationale |
|---|---|---|
| Web | Next.js 15 (App Router), React 19, TypeScript strict, Tailwind CSS, shadcn/ui (Radix), TanStack Table + Query, Recharts | Mature enterprise dashboard stack; accessible primitives |
| API client | TS client generated from FastAPI's OpenAPI schema (`openapi-typescript`) | One source of truth for types |
| API | FastAPI, Pydantic v2, SQLAlchemy 2.0 (async, `asyncpg`), Alembic | As specified; typed end to end |
| Workers | Celery 5 + Redis broker; Celery beat for schedules | As specified. Separate queues per marketplace so Amazon throttling can't starve imports |
| DB | PostgreSQL 16, RLS enabled on tenant tables | Defence-in-depth isolation |
| Auth | Supabase Auth for identity. Orgs, memberships and roles live in **our** DB, and authorization is enforced in FastAPI | Supabase handles passwords, recovery and email verification. We keep authorization logic portable |
| Secrets | Envelope encryption (AES-256-GCM data keys wrapped by cloud KMS; local-dev key from env) for marketplace credentials | Credentials are never stored in plain text and keys can be rotated |
| Files | S3-compatible object storage (AWS S3 / Cloudflare R2; MinIO locally) | Large uploads and exports stay out of Postgres |
| Excel | `openpyxl` (read/write), `python-calamine` optional for fast reads; `XlsxWriter` for exports | Safe parsing, no macro execution |
| Observability | Structured JSON logs, OpenTelemetry traces, Sentry, Prometheus metrics (queue depth, 429 rate, scan latency) | Rate-limit behaviour must be visible |
| Package mgmt | `uv` (Python), `pnpm` workspaces (JS) | Fast, lockfile-reproducible |
| Containers | Docker + docker-compose for local; one image each for api / worker / beat / web | |
| CI | GitHub Actions: lint (ruff, mypy, eslint, tsc), tests (pytest with real Postgres + Redis services, vitest, Playwright e2e), migration check, image build | |

## 1.5 Multi-tenancy model

- An **organization** is the tenant. A user can belong to many orgs through `organization_members`, each with a role.
- The active org comes from the `X-Organization-Id` header. The API verifies membership on **every** request and does not trust the client.
- In each DB transaction the API runs `SET LOCAL app.current_org_id = '<uuid>'`. RLS policies on tenant tables check `organization_id = current_setting('app.current_org_id')::uuid`. The app connects as a non-superuser role **without** `BYPASSRLS`. Migrations run as a separate owner role.
- Workers set the same tenant context from the job's `organization_id` before they touch data.
- Cross-tenant tests are part of the required suite: for every tenant-scoped endpoint, a member of org A must get 404 for org B's resources.

### Roles (RBAC)

| Permission | owner | admin | analyst | viewer |
|---|:-:|:-:|:-:|:-:|
| View products, scans, reports | ✔ | ✔ | ✔ | ✔ |
| Export reports | ✔ | ✔ | ✔ | ✔ |
| Add/upload/edit/delete products | ✔ | ✔ | ✔ | |
| Start/cancel scans | ✔ | ✔ | ✔ | |
| Manage alert rules | ✔ | ✔ | ✔ | |
| Manage marketplace connections (credentials) | ✔ | ✔ | | |
| Invite/remove members, change roles | ✔ | ✔ (not owners) | | |
| Billing/subscription, delete org, transfer ownership | ✔ | | | |

Permissions are defined in code as an enum plus a role→permission map, and enforced with a FastAPI dependency `require(Permission.X)`.

## 1.6 Connector abstraction

```python
class ConnectorCapabilities(BaseModel):
    total_offer_count: bool          # marketplace-reported total
    offer_list: bool                 # individual offers returned
    offer_list_max: int | None       # e.g. Amazon: 20 → list may be truncated
    seller_id: bool
    seller_name: bool
    price: bool
    fulfilment: bool
    batch_size: int                  # 1 = no batching
    identifier_existence_check: bool

class OfferSnapshot(BaseModel):
    marketplace: MarketplaceCode
    external_id: str                 # ASIN / FSN
    status: Literal["ok", "partial", "not_found", "unavailable", "error"]
    total_offer_count: int | None    # what the marketplace says exists
    offers: list[ObservedOffer]      # what we actually received
    is_offer_list_truncated: bool | None
    limitations: list[str]           # machine codes, e.g. "SELLER_NAME_NOT_PROVIDED"
    source: str                      # e.g. "amazon_sp_api.getItemOffers.v0"
    retrieved_at: datetime
    raw_payload_ref: str | None      # object-storage key of the raw response

class MarketplaceConnector(Protocol):
    code: MarketplaceCode
    capabilities: ConnectorCapabilities
    def validate_identifier(self, value: str) -> IdentifierValidation: ...
    async def verify_identifier(self, ctx: ConnectorContext, ids: list[str]) -> list[IdentifierCheck]: ...
    async def fetch_offers(self, ctx: ConnectorContext, ids: list[str]) -> list[OfferSnapshot]: ...
```

There are three implementations: `AmazonSpApiConnector`, `FlipkartConnector` (limited capabilities; see report 7) and `MockConnector`. The mock connector can only be enabled when `APP_ENV in {development, test}`. Every record it produces gets `data_source = "MOCK"`, and the UI shows a red **MOCK DATA** banner on it. On startup the API refuses to boot in production if the mock connector is enabled.
