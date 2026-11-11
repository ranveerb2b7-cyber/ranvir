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

## Layout
See docs/plan/04-folder-structure.md. (Commands are added here as M1 is built.)
