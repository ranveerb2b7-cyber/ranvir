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
| POST | /auth/session/revoke | Revoke all extension tokens + sign-out hook | authenticated |

## Organizations and team
| Method | Path | Purpose | Perm |
|---|---|---|---|
| POST | /organizations | Create org (caller becomes owner, trial subscription) | authenticated |
| GET | /organizations/current | Org details | member |
| PATCH | /organizations/current | Rename etc. | org.manage |
| DELETE | /organizations/current | Soft-delete org | org.delete (owner) |
| GET | /members | List members | member |
| PATCH | /members/{user_id} | Change role / suspend | members.manage |
| DELETE | /members/{user_id} | Remove member | members.manage |
| GET/POST | /invitations | List / create invite (email sent) | members.manage |
| DELETE | /invitations/{id} | Revoke | members.manage |
| POST | /invitations/accept | Accept by token | authenticated |
| POST | /organizations/current/transfer-ownership | | owner |

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

## Products
| Method | Path | Purpose | Perm |
|---|---|---|---|
| GET | /products | List: `q, marketplace, brand, scan_status, has_multiple_sellers, sort, cursor, limit` | member |
| POST | /products | Add one manually | products.write |
| POST | /products/validate | Validate identifiers without saving | products.write |
| GET | /products/{id} | Detail + latest snapshot | member |
| PATCH | /products/{id} | Edit name/brand/monitoring | products.write |
| DELETE | /products/{id} | Soft delete | products.write |
| POST | /products/bulk | Bulk action: delete / enable / disable monitoring / set frequency | products.write |
| GET | /brands | Distinct brands with counts | member |

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
| GET | /dashboard/summary | The 7 KPI tiles (each with as-of time and completeness) | member |
| GET | /dashboard/marketplace-breakdown | | member |

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
