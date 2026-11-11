# 3. Database Entity-Relationship Design

Status: **Implemented in M2** (migrations `0001`–`0003`). See §3.4 for where the implementation refines this design. PostgreSQL 16. All PKs are `uuid` (UUIDv7) unless noted. All tables have `created_at timestamptz not null default now()` and `updated_at timestamptz not null default now()` (maintained by trigger). 🔒 means tenant-scoped: it has `organization_id uuid not null` and an RLS policy.

## 3.1 ER overview

```
organizations 1─┬─< organization_members >─1 users
                ├─< invitations
                ├─1 subscriptions >─1 plans
                ├─< marketplace_connections ─(encrypted credentials)
                ├─< product_batches 1─< product_batch_rows
                ├─< products >─1 marketplaces
                │     │
                ├─< scan_jobs 1─< scan_job_items >─1 products
                │                    │
                │                    1
                │                    │
                ├─< scan_results (1 per item attempt that produced data; append-only)
                │     │ 1─< product_offers >─1 seller_profiles
                │     └─< scan_history (change events vs. previous comparable result)
                ├─< seller_profiles
                ├─< alert_rules 1─< alerts
                ├─< report_exports
                ├─< extension_tokens >─1 users
                └─< audit_logs
marketplaces (global reference data, not tenant-owned)
```

## 3.2 Tables

### Identity and tenancy

**users**: a mirror of the Supabase identity. No passwords are stored here.
| column | type | notes |
|---|---|---|
| id | uuid PK | = Supabase `auth.users.id` |
| email | citext UNIQUE not null | |
| full_name | text | |
| last_login_at | timestamptz | |
| is_active | bool default true | |

**organizations**
| id | uuid PK |
|---|---|
| name | text not null |
| slug | citext UNIQUE not null |
| created_by | uuid FK users |
| deleted_at | timestamptz |

**organization_members** 🔒
| column | type | notes |
|---|---|---|
| organization_id | FK organizations ON DELETE CASCADE | |
| user_id | FK users ON DELETE CASCADE | |
| role | text CHECK (owner, admin, analyst, viewer) | |
| status | text CHECK (active, suspended) | |
| | | UNIQUE (organization_id, user_id); index (user_id) |

**invitations** 🔒: `email citext`, `role`, `token_hash bytea UNIQUE` (the raw token is never stored), `expires_at`, `accepted_at`, `invited_by FK users`. UNIQUE (organization_id, email) WHERE accepted_at IS NULL.

**plans** (global): `code UNIQUE`, `name`, `max_products int`, `max_scans_per_month int`, `max_members int`, `min_scan_interval interval`, `features jsonb`.

**subscriptions** 🔒: `plan_id FK`, `status CHECK (trialing, active, past_due, cancelled)`, `current_period_start/end`, `provider text` (razorpay/stripe), `provider_customer_id`, `provider_subscription_id UNIQUE`, `scans_used_this_period int`. UNIQUE (organization_id) WHERE status IN ('trialing','active','past_due').

### Marketplaces and credentials

**marketplaces** (global reference): `code text UNIQUE` (`amazon_in`, `flipkart`), `name`, `country char(2)`, `currency char(3)`, `external_marketplace_id text` (Amazon `A21TJRUUN4KGV`), `identifier_label` (ASIN/FSN), `is_enabled bool`.

**marketplace_connections** 🔒: one authorized data connection per org per marketplace account.
| column | type | notes |
|---|---|---|
| marketplace_id | FK | |
| connection_type | text | `sp_api_oauth`, `sp_api_self_auth`, `flipkart_seller_api`, `flipkart_affiliate` |
| external_account_id | text | e.g. Amazon selling_partner_id |
| status | text CHECK (pending, active, revoked, error) | |
| encrypted_secret | bytea | AES-256-GCM ciphertext of refresh token / client secret |
| encryption_key_id | text | KMS key / version used |
| granted_scopes | text[] | e.g. SP-API roles |
| last_verified_at, last_error | | |
| | | UNIQUE (organization_id, marketplace_id, external_account_id) |

### Products and uploads

**product_batches** 🔒 (upload history)
| column | type | notes |
|---|---|---|
| uploaded_by | FK users | |
| original_filename | text | |
| storage_key | text | object storage |
| file_sha256 | char(64) | detects re-upload of the same file |
| file_size_bytes | bigint | CHECK ≤ configured limit |
| status | CHECK (uploaded, parsing, preview_ready, committed, failed, discarded) | |
| total_rows, valid_rows, invalid_rows, duplicate_rows | int | |
| committed_at | timestamptz | |
| error_message | text | |

**product_batch_rows** 🔒: `batch_id FK ON DELETE CASCADE`, `row_number int`, `raw jsonb` (original cells), `marketplace_code`, `external_id_normalized`, `brand_name`, `product_name`, `status CHECK (valid, invalid, duplicate_in_file, duplicate_existing)`, `errors text[]`, `product_id FK nullable` (set on commit). UNIQUE (batch_id, row_number).

**products** 🔒
| column | type | notes |
|---|---|---|
| marketplace_id | FK | |
| external_id | text | normalized ASIN / FSN (uppercase, trimmed) |
| product_name, brand_name | text | user-supplied |
| catalog_title, catalog_brand | text | from the marketplace, if verified |
| identifier_status | CHECK (format_valid, verified, not_found, unverifiable) | |
| monitoring_enabled | bool | |
| scan_frequency | interval null | |
| source_batch_id | FK product_batches null | |
| latest_scan_result_id | FK scan_results null | denormalized pointer for fast tables |
| last_scanned_at | timestamptz | |
| deleted_at | timestamptz | |
| | | UNIQUE (organization_id, marketplace_id, external_id) WHERE deleted_at IS NULL; indexes on (organization_id, brand_name), (organization_id, marketplace_id), trigram index on product_name |

### Scanning

**scan_jobs** 🔒: `requested_by FK users null` (null = scheduled), `trigger CHECK (manual, scheduled, extension, api)`, `status CHECK (queued, running, completed, completed_with_errors, failed, cancelled)`, `total_items`, `completed_items`, `failed_items`, `unavailable_items`, `cancelled_items`, `started_at`, `finished_at`, `cancel_requested_at`.

**scan_job_items** 🔒: `scan_job_id FK`, `product_id FK`, `status CHECK (pending, processing, completed, partial, unavailable, failed, cancelled)`, `attempt_count`, `next_attempt_at`, `last_error_code`, `last_error_message`, `started_at`, `finished_at`.
- UNIQUE (scan_job_id, product_id)
- **Partial UNIQUE (product_id) WHERE status IN ('pending','processing')**, which blocks duplicate concurrent scans.

**scan_results** 🔒: append-only snapshot, one per item that reached a terminal state.
| column | type | notes |
|---|---|---|
| scan_job_item_id | FK UNIQUE | idempotency |
| product_id | FK | |
| marketplace_connection_id | FK null | which credential was used |
| status | CHECK (ok, partial, not_found, unavailable, error) | |
| data_source | text | e.g. `amazon_sp_api.getItemOffers.v0`, `MOCK` |
| total_offer_count | int null | marketplace-reported |
| observed_offer_count | int not null default 0 | offers actually received |
| unique_seller_count | int null | distinct seller ids among observed |
| is_offer_list_truncated | bool null | |
| lowest_observed_price, highest_observed_price | numeric(12,2) null | from observed offers only |
| buy_box_price | numeric(12,2) null | |
| currency | char(3) | |
| limitations | text[] | e.g. `{SELLER_NAME_NOT_PROVIDED}` |
| raw_payload_key | text | object storage |
| retrieved_at | timestamptz not null | |
| | | Index (organization_id, product_id, retrieved_at DESC). No UPDATE is granted to the app role (enforced by GRANT + trigger) |

**seller_profiles** 🔒: per org, so even public seller info observed by one tenant isn't shared with another.
| column | type | notes |
|---|---|---|
| marketplace_id | FK | |
| external_seller_id | text | e.g. Amazon SellerId |
| display_name | text null | null when not provided by an authorized source |
| display_name_source | text null | |
| first_observed_at, last_observed_at | timestamptz | |
| is_amazon_retail | bool null | |
| tags | text[] | user labels: authorized, unauthorized, own-brand |
| | | UNIQUE (organization_id, marketplace_id, external_seller_id) |

**product_offers** 🔒: append-only, one per offer within a scan_result.
| column | type | notes |
|---|---|---|
| scan_result_id | FK ON DELETE CASCADE | |
| product_id | FK | denormalized for queries |
| seller_profile_id | FK null | null if the source didn't provide a seller id |
| listing_price, shipping_price, landed_price | numeric(12,2) null | |
| currency | char(3) | |
| condition, sub_condition | text | |
| fulfilment_channel | CHECK (amazon, merchant, flipkart_assured, unknown) | |
| is_buy_box_winner, is_featured_merchant, is_prime | bool null | |
| seller_feedback_rating, seller_feedback_count | numeric / int null | |
| ships_from_country | text null | |
| position | int | rank in the returned list |
| | | Index (organization_id, seller_profile_id, created_at), (scan_result_id) |

**scan_history** 🔒: change events between consecutive comparable scan_results.
| column | type | notes |
|---|---|---|
| product_id | FK | |
| scan_result_id | FK | the new snapshot |
| previous_scan_result_id | FK null | |
| event_type | CHECK (seller_newly_observed, seller_no_longer_observed, seller_not_observed_inconclusive, offer_count_changed, price_changed, buy_box_changed, scan_unavailable) | |
| seller_profile_id | FK null | |
| old_value, new_value | jsonb | |
| confidence | CHECK (high, medium, low) | |
| | | Index (organization_id, product_id, created_at DESC), (organization_id, event_type, created_at DESC) |

### Alerts, reports, extension, audit

**alert_rules** 🔒: `name`, `rule_type CHECK (new_seller, seller_count_above, price_below, offer_count_change, scan_failed)`, `params jsonb` (validated by Pydantic per type), `scope jsonb` (brand / marketplace / product ids), `channels text[]` (in_app, email, webhook), `is_enabled`.

**alerts** 🔒: `alert_rule_id FK`, `product_id FK`, `scan_history_id FK null`, `severity`, `title`, `body`, `status CHECK (open, acknowledged, resolved)`, `acknowledged_by`, `acknowledged_at`, `delivered_channels text[]`.

**report_exports** 🔒: `requested_by`, `report_type CHECK (product, marketplace, brand, seller, scan_summary, errors)`, `format CHECK (xlsx, csv)`, `filters jsonb`, `status`, `storage_key`, `expires_at`.

**extension_tokens** 🔒: `user_id`, `token_hash bytea UNIQUE`, `name`, `scopes text[]`, `last_used_at`, `expires_at`, `revoked_at`.

**audit_logs** 🔒 (append-only; app role has INSERT + SELECT only): `actor_user_id null`, `actor_type (user, system, extension)`, `action text` (e.g. `product.delete`, `connection.create`, `member.role_change`), `entity_type`, `entity_id`, `ip inet`, `user_agent`, `metadata jsonb`. Index (organization_id, created_at DESC).

## 3.3 Integrity rules

- Every 🔒 table has an FK to `organizations(id)` and an index starting with `organization_id`.
- Composite FKs `(organization_id, id)` on child→parent relations within a tenant (e.g. `product_offers(organization_id, scan_result_id) → scan_results(organization_id, id)`). This makes it impossible at the DB level for a row to reference another tenant's row.
- Snapshot tables (`scan_results`, `product_offers`, `scan_history`, `audit_logs`) are append-only. Retention is handled by monthly partitioning on `created_at` (introduced when volume requires it), and old partitions are dropped according to plan retention.
- `total_offer_count`, `observed_offer_count` and `unique_seller_count` are separate columns and are never derived from one another in the UI.

## 3.4 Implementation notes (M2)

Source of truth: `apps/api/src/sellerscope/models/` and `apps/api/migrations/versions/`. A test fails if the two drift apart.

**Refinements to the design above:**
- **Amazon-only scope:**
  - Only `amazon_in` is seeded.
  - `connection_type` allows `sp_api_oauth` and `sp_api_self_auth`.
  - `fulfilment_channel` allows `amazon`, `merchant` and `unknown`.
- **`scan_frequency` / `min_scan_interval`:** stored as integer minutes instead of `interval`.
- **New `scan_results` columns:**
  - `offer_count_breakdown` (jsonb): Amazon `Summary.NumberOfOffers`.
  - `error_code`.
- **`seller_profiles.is_amazon_retail`** became `is_marketplace_retail`. There is also a `notes` column, and a CHECK that a `display_name` always has a `display_name_source`.
- **`invitations.revoked_at`** was added. The pending-invite uniqueness excludes revoked invites.
- **`audit_logs`:**
  - `metadata` is named `details` (`metadata` is reserved by SQLAlchemy).
  - `actor_user_id` is deliberately **not** a foreign key, so audit rows outlive deleted users and never need an UPDATE.
- **Nullable composite FKs** use `ON DELETE NO ACTION`. Products are soft-deleted, so hard deletes of referenced rows are rare.
- **Extra CHECK constraints:**
  - normalized uppercase identifiers
  - non-negative counters
  - `lowest_observed_price <= highest_observed_price`
  - prices require a currency
  - `unique_seller_count <= observed_offer_count`
  - an encrypted secret requires its key id
- **Primary keys** are UUIDv7, generated in Python (`sellerscope.core.ids.uuid7`).

**Database roles:**

| Role | Used by | Rights |
|---|---|---|
| owner (`POSTGRES_USER` / `MIGRATION_DATABASE_URL`) | `alembic upgrade head` only | Owns all tables; not subject to RLS |
| app (`APP_DB_ROLE`, default `sellerscope_app`) | API and workers (`DATABASE_URL`) | `NOSUPERUSER NOBYPASSRLS`, no DDL. CRUD on mutable tables; `SELECT, INSERT` only on append-only tables; `SELECT` only on `marketplaces`/`plans` |

The app role must exist before migrating. Docker creates it via `infra/docker/postgres/init/01-app-role.sh`. In other environments, ops create it.

**Row-level security.** The policies read two transaction-local settings, set via `sellerscope.db.tenant.set_tenant_context()`:

| Table(s) | Read | Write |
|---|---|---|
| 18 tenant tables | `organization_id = current org` | same |
| `organization_members` | current org **or** the user's own memberships (org switcher) | current org only |
| `organizations` | current org **or** orgs the user belongs to | current org only (create = set context to the new org's id first) |
| `users` | yourself **or** members of the current org | yourself only |

With no context set, tenant queries return no rows.

**Append-only enforcement** applies to `scan_results`, `product_offers`, `scan_history` and `audit_logs`, in two layers:
1. The app role has no UPDATE/DELETE grant.
2. A trigger rejects UPDATE and DELETE for every role, including the owner. The only exception is DELETE inside a transaction that sets `app.retention_purge = 'on'`, for owner-run retention jobs.

**Deferred to later milestones:**
- **M3, invitation acceptance:** an invitee isn't yet a member, so looking up an invitation by token crosses tenants. This will use a narrowly scoped `SECURITY DEFINER` function.
- **M6, scheduler:** Celery beat must find due products across all orgs. This will use a dedicated role or `SECURITY DEFINER` function that returns only `(organization_id, product_id)` pairs.
- **Volume:** partitioning of snapshot tables is deferred until data volume requires it.
