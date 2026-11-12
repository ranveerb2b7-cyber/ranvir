# OWASP ASVS 4.0.3 Level 2: SellerScope self-assessment

**Status:** self-assessed on 2026-11-12 against the code at M14, by the development team. It is **not** an independent audit or penetration test; book one before commercial launch.

**Legend:**
- ✅ met, with the evidence named
- 🟡 partly met
- ❌ gap: an action is listed
- ➖ not applicable

| Chapter | Requirement area | Status | Evidence / action |
|---|---|---|---|
| V1 Architecture | Documented architecture, trust boundaries, threat model | 🟡 | docs/plan/01 and 09 describe the components and boundaries. **Action:** a written threat model (STRIDE) per external interface: web, API, extension, SP-API. |
| V1 | Secure build and deploy | ✅ | CI: tests, browser e2e, lint, type checks, dependency audits (`security` job), Terraform validation; immutable image tags; non-root containers |
| V2 Authentication | Password storage and policy, credential recovery | 🟡 | Delegated to Supabase Auth (bcrypt, reset by email). **Action:** set a minimum length of 12 and leaked-password protection in the Supabase project settings. |
| V2 | Multi-factor authentication | ❌ | **Action:** enable Supabase TOTP MFA and add enrolment/verification UI. Require it for owners/admins (L2 expectation). |
| V2 | Brute-force protection | ✅ | Supabase rate limits; API per-IP and per-user limits (`core/rate_limit.py`); extension pairing codes: per-IP limit, 10-minute validity, single use, PKCE-bound |
| V3 Session management | Token verification, expiry, logout | ✅ | JWT signature/issuer/audience/expiry checks with pinned algorithms (`auth/tokens.py`); refresh via Supabase; extension tokens are opaque, hashed, expiring, revocable, and re-checked against membership per request |
| V3 | Cookie protections | 🟡 | `@supabase/ssr` session cookies are JavaScript-readable by design (docs/plan/09); mitigated by a strict nonce CSP. **Action:** evaluate httpOnly server-side session handling. |
| V4 Access control | Deny by default, tenant isolation, IDOR | ✅ | `OrgDep`, RBAC (`auth/permissions.py`), PostgreSQL RLS on all 22 tenant tables, restricted app role (NOBYPASSRLS), cross-tenant matrix over 64 routes plus dedicated extension tests; 404 for other tenants' resources |
| V5 Validation, sanitization, encoding | Input validation, injection | ✅ | Pydantic models with `extra="forbid"`; SQLAlchemy bound parameters (no user input in SQL text); ASIN parsing in one module; upload type/size/content checks |
| V5 | Output encoding, CSV/XLSX injection, email header injection | ✅ | React escaping; `csv_safe` and typed XLSX text cells; email subjects stripped of line breaks (`services/mailer.py`); the extension builds DOM without `innerHTML` |
| V6 Cryptography | Random values, hashing, TLS | ✅ | `secrets` / `crypto.getRandomValues` for tokens and codes; SHA-256 for token storage; TLS 1.2+ at the ALB, `rds.force_ssl`, Redis TLS (Terraform) |
| V6 | Encryption at rest, key management | 🟡 | KMS-encrypted RDS, ElastiCache, S3 and ECR in Terraform (⚠ not applied). **Action:** M7 credential encryption (envelope encryption with KMS). |
| V7 Errors and logging | No sensitive data in errors or logs; security events logged | ✅ | RFC 9457 errors with no stack traces; structured logs with request ids; `LOG_LEVEL=DEBUG` refused in production; Sentry without PII or bodies; append-only `audit_logs` for security-relevant actions |
| V8 Data protection | Sensitive data not cached; minimisation | ✅ | API responses `Cache-Control: no-store`; downloads only through authenticated, audited requests; no seller names unless the user adds them |
| V8 | Retention and deletion | ❌ | **Action:** a purge job for soft-deleted organizations after the grace period; retention of raw payloads (90 days); self-service account deletion (also a DPDP item) |
| V9 Communications | TLS everywhere, HSTS | ✅ | HTTPS-only URLs enforced by the production settings guard; HTTP→HTTPS redirect at the ALB; HSTS on web and API; the S3 bucket denies non-TLS requests |
| V10 Malicious code | Dependency integrity, no remote code | ✅ | Lockfiles (`uv.lock`, `pnpm-lock.yaml`); `pip-audit` and `pnpm audit` in CI (clean on 2026-11-12, after overriding `minimatch` in dev tooling); the extension loads no remote code |
| V11 Business logic | Quotas, anti-automation, sequencing | ✅ | Plan quotas for products and scans; duplicate-scan guard; rate limits; idempotent workers |
| V12 Files and resources | Upload validation, storage, SSRF | ✅ | Size/row limits, magic-byte checks, app-generated storage keys; no server-side fetching of user-supplied URLs (product links are parsed, never fetched) |
| V13 API | Authentication on all endpoints, schema validation, CORS | ✅ | Every route classified (org-scoped or deliberately listed); explicit CORS allow-list (https only in production); OpenAPI disabled in production |
| V14 Configuration | Hardened configuration, security headers | ✅ | The API refuses to start with unsafe production settings (`core/config.py`, `_problems`, unit-tested); web: nonce-based CSP without `unsafe-inline` scripts, `frame-ancestors 'none'`, nosniff, Referrer-Policy, Permissions-Policy, HSTS; API: `default-src 'none'` CSP |
| V14 | Least-privilege runtime | ✅ | Non-root containers; ECS task role limited to its own bucket prefix; database app role without DDL or BYPASSRLS; SECURITY DEFINER functions take hashes or limits and return ids or counts only, with EXECUTE revoked from PUBLIC |

## Open items before launch (ordered)
1. MFA for owners/admins (V2).
2. Data retention and deletion jobs, and account deletion (V8, DPDP).
3. An independent penetration test against staging, with a re-test after fixes.
4. A written threat model (V1).
5. Supabase password policy settings (V2).
6. M7 credential encryption (V6).
