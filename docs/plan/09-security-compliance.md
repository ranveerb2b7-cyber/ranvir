# 9. Security and Compliance Considerations

Status: **PROPOSAL — awaiting approval.**

## 9.1 Authentication
- Supabase Auth handles passwords (bcrypt), email verification, password recovery, and optional MFA (TOTP) for owners/admins.
- FastAPI verifies access tokens (`sellerscope.auth.tokens`), implemented in M3:
  - **Keys:** asymmetric keys from the project's JWKS (RS256/ES256, hosted Supabase), or a shared HS256 secret (local GoTrue). Only the algorithm matching the configured key type is accepted, so `alg: none` and HS/RS confusion are rejected.
  - **Claims:** `exp`, `aud`, `iss` and `sub` are required. Allowed clock skew is 30 s.
  - **Who:** only `role = authenticated` users with an email; anonymous sign-ins and `anon`/`service_role` keys are rejected.
  - **Production:** startup fails in staging/production without an issuer and a key source.
- **Correction (M3):** the web app keeps the Supabase session in cookies managed by `@supabase/ssr`. These cookies are **readable by JavaScript**, by design of that library, because the browser client refreshes tokens itself. They are not httpOnly, as an earlier draft claimed.
  - **Mitigations:**
    - the strict CSP planned for M14
    - no third-party scripts
    - short-lived access tokens (1 h)
    - refresh-token rotation in Supabase Auth
    - every API call independently verified
  - `proxy.ts` validates the session with the auth server before rendering protected pages.
  - The selected organization id is the only value in localStorage, and it is not a secret.
- Sign-in, sign-up and sign-out clear the client data cache, so a previous user's data is never shown.
- `?next=` redirects are restricted to same-site relative paths (open-redirect protection, unit tested).
- **Extension tokens:** paired via a one-time code + PKCE. They are opaque random 256-bit values, stored hashed (SHA-256), scoped (`extension:read`, `extension:check`), expire after 90 days, and can be revoked from the web UI.

## 9.2 Authorization and tenant isolation
- Every tenant route checks membership + permission. Resources from another org return **404** (not 403), to avoid enumeration.
- Postgres RLS on all tenant tables, plus composite `(organization_id, id)` foreign keys. The app DB role has no `BYPASSRLS`, no DDL rights, and no UPDATE/DELETE on append-only tables.
- Celery tasks carry `organization_id` and set the tenant context before touching data.
- An automated **cross-tenant test matrix** covers every endpoint and runs in CI.

## 9.3 Secrets and credentials
- Marketplace refresh tokens and client secrets use envelope encryption: AES-256-GCM with a per-record data key, wrapped by KMS. The key ID is stored for rotation. Secrets are decrypted only inside workers at call time and are never logged, returned by the API, or sent to the frontend.
- Platform secrets (LWA client secret, DB password, Supabase service key) come from the environment / secret manager. `.env` is git-ignored, `.env.example` holds placeholders only, and gitleaks runs in pre-commit and CI.
- `NEXT_PUBLIC_*` variables are restricted to non-secret values (API URL, Supabase anon key), and a lint check enforces this.

## 9.4 Upload security (implemented in M5)
- **Accepted files:** only `.csv` and `.xlsx`, checked by **extension and content**:
  - XLSX must be a ZIP with `[Content_Types].xml` and `xl/workbook.xml`.
  - CSV must not be a ZIP/OLE file or contain NUL bytes.
- **Rejected with specific messages:**
  - macro-enabled workbooks (`.xlsm`, or any archive containing `vbaProject.bin` / a macro content type, even when renamed `.xlsx`)
  - legacy `.xls` and password-protected (OLE) files
  - mismatched content
- **Size limits:**
  - 10 MB, enforced while streaming the upload, plus a `Content-Length` pre-check
  - 50,000 rows
  - ZIP bomb guard: at most 2,000 entries and 200 MB uncompressed
- **Parsing:** `openpyxl` in read-only mode with `data_only=True`: formulas are never evaluated, only cached values are read. CSV encoding is UTF-8 (with/without BOM), falling back to Windows-1252.
- **Storage:**
  - Files are stored under application-generated keys (`org/<org>/uploads/<batch>/original.<ext>`). The uploaded file name is display-only and stripped of path parts.
  - S3 objects use server-side encryption.
  - Local-disk storage is refused in staging/production.
- **CSV/Excel formula injection:** exported cells beginning with `= + - @ \t \r` are prefixed with `'` (rejected-rows export).

## 9.5 API protection
- Redis-backed rate limiting per IP (auth/pairing endpoints) and per user and org (general), with tighter limits on scan creation.
- CORS is limited to the web origin and the extension origin (`chrome-extension://<id>`).
- Security headers are set: HSTS, CSP (no inline scripts in web), X-Content-Type-Options, frame-ancestors none.
- Request size limits, Pydantic validation on everything, and SQLAlchemy parameterised queries (no string SQL).
- OAuth `state` is signed and single-use. The redirect URI is an exact match.
- Webhooks (billing) require signature verification and are idempotent.

## 9.6 Audit and monitoring
- Append-only `audit_logs` for: auth events, member changes, connection create/verify/delete, product bulk ops, uploads, scan start/cancel, exports, settings changes.
- Alerting on spikes of 401/403/429, connector errors, and failed jobs.
- Logs scrub tokens, secrets and personal data.

## 9.7 Chrome extension constraints
- MV3, with minimum host permissions (`*://*.amazon.in/*`, `*://*.flipkart.com/*`, our API origin) and no `<all_urls>`.
- The content script only reads `location.href` to detect ASIN/FSN. **It doesn't read or transmit page content, automate clicks, or interact with logins or CAPTCHAs.**
- The token lives in `chrome.storage.session` (cleared on browser restart) or in `storage.local`, with an explicit "remember this device" choice. No remote code (an MV3 requirement).

## 9.8 Marketplace compliance
- **Amazon:** SP-API only, under the Acceptable Use Policy and Data Protection Policy (encryption, access control, logging, incident response within the required window, data deletion on deauthorization). Legal review is needed before the public Appstore submission.
- **Flipkart:** authorized APIs only. No scraping, no reverse-engineered mobile APIs, no CAPTCHA or bot-detection bypass.
- **No fabricated data:** the mock connector is blocked in production, results carry provenance, and unavailable values are displayed as unavailable.

## 9.9 Privacy and legal (India)
- **Digital Personal Data Protection Act, 2023 (DPDP):**
  - user personal data (names, emails) needs a privacy notice, consent, purpose limitation, and deletion on request
  - a breach-notification process
  - hosting in India (ap-south-1) is recommended
- Seller identifiers are business data, but seller names of individual proprietors can be personal data. They should be minimised and retained only as long as needed.
- Terms of Service, Privacy Policy and DPA templates need legal drafting before commercial launch.
- **Retention:**
  - raw payloads are kept for a configurable period (default 90 days)
  - snapshots are kept for the plan's history window
  - everything is deleted on org deletion after a grace period

## 9.10 Engineering security practices
- Dependency scanning (`pip-audit`, `pnpm audit`, Dependabot), container image scanning, SAST (`bandit`, `semgrep`).
- Branch protection, required reviews, and CI must be green before merge.
- Before public launch: an external penetration test, plus OWASP ASVS Level 2 as the target baseline.
