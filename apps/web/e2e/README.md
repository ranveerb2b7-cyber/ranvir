# End-to-end tests

`make test-e2e` (or `apps/web/e2e/run-local.sh`) starts a throwaway stack and drives the real
web app in Chromium:

- a fresh PostgreSQL database, migrated with the restricted app role
- Redis
- an SMTP sink (aiosmtpd, writing a Maildir), so invitation emails are actually sent and read
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

## What the stub does not prove

The stub implements only the endpoints our flows call: sign-up (auto-confirmed), password sign-in, refresh, get/update user, recover, logout. It signs HS256 tokens the same way GoTrue does.

It does **not** cover these Supabase Auth behaviours:
- email confirmation
- the PKCE `/auth/callback` exchange
- real password-reset emails
- rate limits
- GoTrue's own validation

Verify those against the docker-compose GoTrue container (`make up`, then use Mailpit at http://localhost:8025) or a staging Supabase project before release.
