# 5. API Endpoint Plan

Status: **PROPOSAL — awaiting approval.**

- Base path: `/api/v1`. OpenAPI is served at `/api/v1/openapi.json`, with Swagger UI at `/docs` (disabled or auth-gated in production).
- Auth: `Authorization: Bearer <Supabase JWT>`, or an extension token for `/extension/*`.
- Tenant: the `X-Organization-Id` header is required on tenant routes, and membership is verified server-side.
- **Perm** is the required permission; see the RBAC table in the architecture doc.

## Auth and account
Registration, login, logout and password recovery happen in Supabase Auth from the web client. The API exposes:

| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /me | Current user + memberships | authenticated |
| PATCH | /me | Update profile | authenticated |
| POST | /auth/session/revoke | Revoke all extension tokens + sign-out hook (M12) | authenticated |

The first authenticated request creates the user's local record (`users` mirrors the identity provider) and keeps the email in sync.

## Organizations and team
| Method | Path | Purpose | Perm |
|---|---|---|---|
| POST | /organizations | Create org (caller becomes owner, trial subscription) | authenticated |
| GET | /organizations/current | Org details | member |
| PATCH | /organizations/current | Rename etc. | org.manage |
| DELETE | /organizations/current | Soft-delete org | org.delete (owner) |
| GET | /members | List members (with email/name) | member |
| PATCH | /members/{user_id} | Change role / suspend | members.manage |
| DELETE | /members/{user_id} | Remove member | members.manage |
| DELETE | /members/me | Leave the organization (owners must transfer first) | member |
| GET | /invitations | List pending invitations | member |
| POST | /invitations | Create invite and send email; response says whether the email was delivered | members.manage |
| POST | /invitations/{id}/resend | New token (old link stops working), new expiry, email again | members.manage |
| DELETE | /invitations/{id} | Revoke | members.manage |
| POST | /invitations/preview | `{token}` → org name, role, status, whether the email matches the signed-in user | authenticated |
| POST | /invitations/accept | `{token}` → join (email must match) | authenticated |
| POST | /organizations/current/transfer-ownership | Owner hands over ownership and becomes admin | owner |

**Implemented in M3.** Rules:
- Ownership is never assignable by invite or role change, only by transfer.
- Admins can't modify the owner or themselves.
- Suspended members lose access immediately.
- Cross-tenant access returns 404.
- **Rate limits** (per verified user unless noted):
  - org create: 10/h
  - invite create and resend: 30/h each
  - invite preview + accept: 20/min combined
  - all API routes except health: 300/min per IP

## Marketplace connections
| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /marketplaces | Reference list + connector capabilities | member |
| GET | /connections | List (never returns secrets) | member |
| POST | /connections/amazon/oauth/start | Returns Seller Central consent URL + signed state | connections.manage |
| GET | /connections/amazon/oauth/callback | LWA code exchange, store encrypted refresh token | (state-verified) |
| POST | /connections/flipkart | Register authorized Flipkart credentials | connections.manage |
| POST | /connections/{id}/verify | Test call, update status | connections.manage |
| DELETE | /connections/{id} | Revoke + wipe secret | connections.manage |

## Products (implemented in M4)
| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /products | List with the latest scan per product. Params: `q` (ASIN prefix, name or brand), `marketplace`, `brand` (`__none__` = no brand), `scan_status` (incl. `not_scanned`), `multiple_sellers`, `monitoring`, `sort`, `order`, `page`, `page_size` (≤100) | member |
| POST | /products | Add one: `{identifier}` is an ASIN **or an Amazon product URL**. 422 `identifier_invalid` (with `reason`), 409 `product_exists` (with `existing_product_id`), 402 `plan_limit_reached` / `subscription_required` | products.write |
| POST | /products/validate | Check up to 1000 identifiers (format, warnings, existing duplicates) without saving | member |
| GET | /products/{id} | One product + latest snapshot | member |
| PATCH | /products/{id} | Edit name / brand / monitoring (identifier is immutable) | products.write |
| DELETE | /products/{id} | Soft delete; scan history is kept; the same ASIN can be re-added | products.write |
| POST | /products/bulk | Up to 500 ids: `delete`, `enable_monitoring`, `disable_monitoring`, `set_brand`. Returns `affected` and `not_found` (other orgs' ids land here) | products.write |
| GET | /brands | Distinct brands with product counts (including "no brand") | member |

**List semantics:**
- **Unknown values** (never scanned, or not provided by the source) are `null`.
- **Sorting:** unknown values sort last in both directions.
- **`multiple_sellers`:** products whose seller count is unknown match neither `true` nor `false`.

## Uploads (implemented in M5)
| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /uploads/template?format=xlsx\|csv | Empty template (XLSX includes an Instructions sheet) | authenticated |
| POST | /uploads | Multipart `file`. Safety checks happen before storing; returns **202** with the batch (`status: uploaded`); a worker parses it. 413 `file_too_large`, 422 with a specific `code` for unsafe or unsupported files | products.write |
| GET | /uploads | Upload history, newest first (paged) | member |
| GET | /uploads/{id} | Status, counts, detected columns, error, plan usage, `same_file_as` (poll while `uploaded`/`parsing`) | member |
| GET | /uploads/{id}/rows?status= | Rows with original cells, normalized ASIN, error/warning codes and messages (paged) | member |
| POST | /uploads/{id}/commit | Adds the valid rows as products. All-or-nothing; re-checks duplicates; 402 when over the plan limit; 409 unless `preview_ready` | products.write |
| POST | /uploads/{id}/discard | Discard (nothing is added) | products.write |
| GET | /uploads/{id}/rejected.csv | Non-added rows with reasons and original cells (formula-injection safe) | member |

Rate limit: 30 uploads per user per hour.

## Scanning (implemented in M6)
| Method | Path | Purpose | Perm |
|---|---|---|---|
| POST | /scan-jobs | `{product_ids}` or `{all_monitored: true}` → **202** job. Products already being scanned are skipped (`already_running`); 409 `scan_already_running` if none left, 409 `connector_unavailable` without an authorized data source, 402 `scan_quota_exceeded` | scans.run |
| GET | /scan-jobs | Jobs, newest first (paged) | member |
| GET | /scan-jobs/quota | Product scans used this UTC month vs plan limit | member |
| GET | /scan-jobs/{id} | Status and counters (poll while `queued`/`running`) | member |
| GET | /scan-jobs/{id}/items?status= | Per product: status, attempts, next retry, last error, result summary | member |
| POST | /scan-jobs/{id}/cancel | Cancels products not started yet; in-flight ones finish | scans.run |
| POST | /scan-jobs/{id}/retry-failed | New job for the products that failed | scans.run |
| GET | /meta | Public: environment, version, `mock_connector_enabled` (drives the MOCK DATA banner) | public |

Rate limit: 60 scan starts per user per hour.

## Seller intelligence and history (implemented in M8)
| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /products/{id}/offers?scan_result_id= | Offers in the latest (or a given) snapshot, with seller labels | member |
| GET | /products/{id}/scans | Every snapshot of the product, newest first (failed scans included) | member |
| GET | /products/{id}/history | Change events for the product | member |
| GET | /products/{id}/trends?days=90 | Usable snapshots over time (failed/unavailable scans are gaps) | member |
| GET | /changes?event_type=&product_id=&seller_id=&include_inconclusive= | Organization-wide change feed | member |
| GET | /sellers?q=&tag=&currently_offering= | Sellers with products currently offered, Buy Box count, lowest current price | member |
| GET | /sellers/{id} | Seller detail: per product presence (`observed`, `no_longer_observed`, `not_observed_inconclusive`, `unknown`), current offer, recent changes | member |
| PATCH | /sellers/{id} | Your labels: display name (source `user`), tags, notes | products.write |
| GET | /sellers/compare?ids=&ids= | 2–4 sellers side by side on the products they currently offer | member |

**Change events** (`scan_history`) are written in the same transaction as each snapshot by `scanning/diff.py`. Types:
- `seller_newly_observed`, `seller_no_longer_observed`, `seller_not_observed_inconclusive`
- `offer_count_changed`, `price_changed`, `buy_box_changed`
- `scan_unavailable`

Each event carries a confidence of `high`, `medium` or `low`.

## Dashboard
| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /dashboard/summary | The KPI tiles plus a per-marketplace breakdown (implemented in M4) | member |

Each KPI is `{value, reason}`.
- **Product counts** are always known (0 is a real zero).
- **Scan-derived KPIs** are `null` with `reason: "no_scans_yet"` until the first scan.
- **"Products with multiple sellers"** says how many scanned products it excludes because their seller data was unavailable.
- **"Total offers observed"** sums offers actually received, not marketplace-reported totals.

## Alerts
Implemented in M10. Alerts come only from rule evaluation after each scan, in the same transaction as the snapshot.

| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /alert-rules | Rules with their unresolved-alert counts, plus the per-organization limit (50) | member |
| POST | /alert-rules | `{name, rule_type, params, scope: {product_ids, brands}, severity?, channels: [in_app, email], recipient_user_ids, is_enabled}` (params are validated per type; recipients must be active members) | alerts.manage |
| GET | /alert-rules/{id} | One rule | member |
| PATCH | /alert-rules/{id} | Partial update; the type can't change | alerts.manage |
| DELETE | /alert-rules/{id} | Deletes the rule; its alerts are kept with the rule's name | alerts.manage |
| GET | /alerts?status=&active=&severity=&rule_id=&product_id=&page= | Newest first; each alert has its product, seller and email delivery status | member |
| GET | /alerts/summary | Open count by severity, acknowledged count, emails that gave up | member |
| GET | /alerts/{id} | One alert | member |
| POST | /alerts/{id}/acknowledge \| resolve | Triage. A resolved alert can't be acknowledged (409). | member |
| POST | /alerts/bulk | `{ids, action: acknowledge\|resolve}`; ids from other organizations are ignored | member |
| POST | /alerts/{id}/retry-delivery | Re-queue emails that failed after all retries | alerts.manage |

**Rule types**
| Type | Params | Behaviour |
|---|---|---|
| `new_seller` | `min_confidence: high\|medium`, `exclude_seller_tags` | One alert per "newly observed" change event |
| `seller_gone` | `include_inconclusive` (default false), `exclude_seller_tags` | Proven departures only, unless opted in |
| `buy_box_changed` | `exclude_seller_tags` (new winner) | One alert per Buy Box change |
| `offer_count_change` | `min_change`, `direction: any\|increase\|decrease` | Reported total offer count |
| `seller_count_above` | `threshold` | Threshold rule (see below) |
| `price_below` | `threshold` (₹, landed), `exclude_seller_tags` | Threshold rule |
| `scan_failed` | `include_unavailable` | Fires on a failed scan; resolves on the next scan that didn't fail |

**Threshold rules** have at most one unresolved alert per rule and product. They fire only on values known to cross the threshold, for example a lower-bound seller count from a cut-off list that is already above it. They resolve automatically only when complete data proves the condition cleared. Unknown values neither fire nor resolve.

## Reports
Implemented in M11. Every active member may export their organization's data. Exports and downloads are audited.

| Method | Path | Purpose | Perm |
|---|---|---|---|
| POST | /reports | `{report_type, format: xlsx\|csv, filters}` → 202. The export is prepared by the `reports` worker queue. At most 3 queued or running per organization (409). | member |
| GET | /reports?page= | Export history, newest first, with requester, rows, size and expiry | member |
| GET | /reports/{id} | One export, including the failure reason if it failed | member |
| GET | /reports/{id}/download | The file, streamed through the API with `Cache-Control: no-store`. 409 if not ready, 410 if expired. | member |
| DELETE | /reports/{id} | The export and its file. Allowed for the requester or an admin; 409 while running. | member |

**Report types and filters**
| Type | Filters | Rows |
|---|---|---|
| `product` | `brand` (`__none__` = no brand), `monitoring` | One per product: latest data, last scan attempt, notes |
| `brand` | none | One per brand |
| `seller` | `tag`, `currently_offering` | One per seller profile |
| `marketplace` | none | One per enabled marketplace |
| `scan_summary` | `date_from`, `date_to` (UTC, inclusive; default last 30 days; max 366 days) | One per scan job |
| `errors` | `date_from`, `date_to` | One per failed, unavailable or not-found scan result |
| `alerts` | `date_from`, `date_to`, `status` | One per alert |

**Design notes**
- **No shareable links:** the plan proposed signed download URLs. Downloads instead go through the authenticated API, so a leaked link can't expose data, and each download is audited.
- **Retention:** files are kept for `REPORT_RETENTION_DAYS` (default 7). Then the beat task marks the export expired and deletes the file.
- **Missing values:** unknown values are empty cells, never 0, and a Notes column explains why.
- **MOCK data:** labelled in rows, in the XLSX "About" sheet, and in the API (`contains_mock`).
- **Formula injection:**
  - CSV: text starting with `= + - @`, a tab or a carriage return gets an apostrophe prefix.
  - XLSX: text cells are typed as strings, so they're never evaluated as formulas.

## Chrome extension
| Method | Path | Purpose | Perm |
|---|---|---|---|
| POST | /extension/pair/start | From a logged-in web session: issue a one-time pairing code | authenticated |
| POST | /extension/pair/complete | Extension exchanges code (+PKCE verifier) for a scoped, revocable token | public, rate-limited |
| GET | /extension/lookup?marketplace=&id= | Last stored snapshot + timestamp + dashboard URL | ext token |
| POST | /extension/check | Enqueue a scan via the official connector (quota applies) | ext token, scans.run |
| GET/DELETE | /extension/tokens[/{id}] | Manage paired devices | authenticated |

## Billing (later milestone)
`GET /billing/plans`, `GET /billing/subscription`, `POST /billing/checkout`, `POST /billing/webhook` (provider-signature verified).

## System
`GET /health/live`, `GET /health/ready` (DB + Redis), `GET /audit-logs` (admin).
