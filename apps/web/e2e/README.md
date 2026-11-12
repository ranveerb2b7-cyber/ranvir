# End-to-end tests

`make test-e2e` (or `apps/web/e2e/run-local.sh`) starts a throwaway stack and drives the real
web app in Chromium:

- a fresh PostgreSQL database, migrated with the restricted app role
- Redis
- an SMTP sink (aiosmtpd, writing a Maildir), so invitation emails are actually sent and read
- a Celery worker (parses uploads, same as production)
- the API (uvicorn) and the production web build (`next build` standalone server)
- `stub-auth.mjs`: a **test-only stand-in for Supabase Auth**

`accounts.e2e.mjs` covers:
- redirect when signed out
- sign-up, then onboarding, then creating an organization
- inviting by email, then the invitee registering and accepting
- read-only Team page for analysts
- reuse of an accepted link is rejected
- role change
- second organization and the org switcher, with isolation
- rename in Settings
- mobile layout

`products.e2e.mjs` covers:
- empty dashboard KPIs (real zero vs "Not available")
- adding from a URL, plus duplicate and short-link rejection
- 31 products with pagination
- search and brand filter (URL-synced)
- sorting, bulk set-brand, edit and stop monitoring
- dashboard counts and the phone card layout

`uploads.e2e.mjs` covers:
- template download, wrong file type refused
- upload with progress, worker parsing, and preview with reasons
- formula-safe rejected-rows CSV
- commit, then history
- a failed file (no ASIN column)

`scans.e2e.mjs` covers:
- the MOCK DATA banner
- Scan now, processed by the worker
- MOCK-labelled values in the table
- dashboard metrics, with "new sellers" still not available
- Scan all monitored, history and quota

`intel.e2e.mjs` covers:
- the baseline scan, then detected changes after the MOCK drift (`MOCK_EPOCH_SECONDS=5`)
- product detail with charts and table view
- seller labels, filters and comparison
- the dashboard new-seller count

`alerts.e2e.mjs` covers:
- creating rules in the UI, including a validation error (email without recipients)
- a threshold rule firing on the first scan while change rules wait for a baseline
- new-seller alerts after the MOCK drift, emailed by the worker's `alerts` queue to the SMTP sink
- acknowledge, resolve, status filter, bulk acknowledge, disabling a rule
- the open-alerts badge and dashboard tile, and the inbox at phone width

`reports.e2e.mjs` covers:
- a Products report as CSV prepared by the worker's `reports` queue, then downloaded. Checked in the file: MOCK labelling, blank cells with "Not scanned yet." (no invented zeros), and a neutralised `=` formula
- the same report as Excel
- the scan summary report, and the error shown for an invalid date range
- deleting a report, and the page at phone width

`extension.e2e.mjs` runs the built extension (`apps/extension/dist`, built by `run-local.sh`) in Chromium. It covers:
- the manifest permission review
- the badge on an Amazon.in product page, served locally by Playwright routing, with no network to Amazon
- pairing: approve on the web, a wrong code, then the right code
- lookup with "Not scanned yet", then "Check now" processed by the worker
- untracked and non-product pages
- that only the ASIN is sent to the API
- revocation from Settings

## What the stub does not prove

The stub implements only the endpoints our flows call: sign-up (auto-confirmed), password sign-in, refresh, get/update user, recover, logout. It signs HS256 tokens the same way GoTrue does.

It does **not** cover these Supabase Auth behaviours:
- email confirmation
- the PKCE `/auth/callback` exchange
- real password-reset emails
- rate limits
- GoTrue's own validation

Verify those against the docker-compose GoTrue container (`make up`, then use Mailpit at http://localhost:8025) or a staging Supabase project before release.
