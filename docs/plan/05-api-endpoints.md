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

## Uploads
| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /uploads/template?format=xlsx\|csv | Download template | member |
| POST | /uploads | Multipart upload (size/type validated) → batch | products.write |
| GET | /uploads | Upload history | member |
| GET | /uploads/{id} | Status + counts (polled for progress) | member |
| GET | /uploads/{id}/rows?status= | Preview accepted/rejected rows | member |
| POST | /uploads/{id}/commit | Create products from valid rows | products.write |
| POST | /uploads/{id}/discard | Discard | products.write |
| GET | /uploads/{id}/rejected.csv | Download rejected rows with reasons | member |

## Scanning
| Method | Path | Purpose | Perm |
|---|---|---|---|
| POST | /scan-jobs | Create: `{product_ids}` or `{filter}`; 409 for products already in an active scan | scans.run |
| GET | /scan-jobs | List | member |
| GET | /scan-jobs/{id} | Progress counters | member |
| GET | /scan-jobs/{id}/items?status= | Per-product status + errors | member |
| POST | /scan-jobs/{id}/cancel | Cancel pending items | scans.run |
| POST | /scan-jobs/{id}/retry-failed | New job for failed items | scans.run |

## Seller intelligence and history
| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /products/{id}/offers?scan_result_id= | Offers in latest (or a given) snapshot | member |
| GET | /products/{id}/scan-results | Snapshot timeline | member |
| GET | /products/{id}/history | Change events | member |
| GET | /products/{id}/trends?metric=&from=&to= | Time series (offer count, sellers, min/max price) | member |
| GET | /sellers | Seller list: products count, last seen, tags | member |
| GET | /sellers/{id} | Seller detail: products, prices across products | member |
| PATCH | /sellers/{id} | Tag (authorized/unauthorized), note | products.write |
| GET | /sellers/compare?ids= | Side-by-side comparison | member |
| GET | /history | Org-wide change feed (filters: event_type, brand, marketplace, date) | member |

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
| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET/POST | /alert-rules | | alerts.manage |
| PATCH/DELETE | /alert-rules/{id} | | alerts.manage |
| GET | /alerts?status= | | member |
| POST | /alerts/{id}/acknowledge \| resolve | | member |

## Reports
| Method | Path | Purpose | Perm |
|---|---|---|---|
| POST | /reports | `{type: product\|marketplace\|brand\|seller\|scan_summary\|errors, format: xlsx\|csv, filters}` → async export | member |
| GET | /reports | Export history | member |
| GET | /reports/{id}/download | Short-lived signed URL | member |

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
