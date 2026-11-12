# Compliance checklist (India DPDP Act 2023, CERT-In, Amazon SP-API policies)

**Not legal advice.** This tracks engineering readiness; obligations must be confirmed by counsel, especially the DPDP Rules, whose detailed requirements were being phased in.

**Legend:**
- ✅ built
- 🟡 partly built
- ❌ not built
- ⚖ needs legal or business action

## Digital Personal Data Protection Act, 2023
| Item | Status | Notes |
|---|---|---|
| **Data map:** what personal data we hold | ✅ | Users: email, optional name, IP and user agent in the audit log. Customer-entered seller labels can name individual sellers (docs/plan/09 §9.9). Amazon gives seller IDs, not names. |
| Purpose limitation and minimisation | ✅ | No tracking or analytics SDKs; Sentry is configured without PII; no seller names stored unless a customer types them |
| Notice and consent at sign-up | ❌ ⚖ | Needs a privacy notice and a consent checkbox at registration, with the policy text drafted by counsel |
| Rights: access, correction, erasure, grievance | 🟡 | Users can edit their profile and leave organizations. ❌ Self-service account deletion; ❌ data export of personal data; ⚖ grievance officer contact |
| Retention and erasure after the purpose ends | ❌ | Organizations are soft-deleted (`deleted_at`) but **no purge job yet**; raw payload retention isn't enforced yet |
| Security safeguards | ✅ | See 10-asvs-l2-checklist.md: tenant isolation (RLS), encryption in transit and at rest (⚠ infrastructure not applied), access control, audit log |
| Breach notification to the Board and individuals | 🟡 ⚖ | Process in runbooks/incident-response.md; templates and timelines to be confirmed by counsel |
| Data processing agreements with sub-processors | ⚖ | AWS, Supabase, the email provider and Sentry, if used |
| Data localisation | ✅ | Hosting planned in ap-south-1 (Mumbai) and a Mumbai Supabase project; ⚠ Sentry region to choose (EU or US) if enabled, or disable it |

## CERT-In Directions (April 2022)
| Item | Status | Notes |
|---|---|---|
| Report cyber incidents within 6 hours | 🟡 ⚖ | In runbooks/incident-response.md; name the point of contact |
| Keep logs 180 days, within India | 🟡 | CloudWatch Logs in ap-south-1 with 180-day retention in production (Terraform, ⚠ not applied) |
| Synchronise clocks to NTP | ✅ | AWS-managed time on Fargate and RDS |

## Amazon Selling Partner API policies (applies from M7)
| Item | Status | Notes |
|---|---|---|
| Developer profile and Acceptable Use Policy review | ❌ ⚖ | Needed for the Seller Central developer registration (M7 prerequisite) |
| Data Protection Policy: encryption in transit and at rest | 🟡 | TLS everywhere; at-rest KMS in Terraform (⚠ not applied); M7 must encrypt refresh tokens with KMS |
| Data Protection Policy: access control, least privilege, MFA for admin access | 🟡 | RBAC and RLS done; ❌ MFA (see ASVS); AWS IAM MFA is an operational action |
| Data Protection Policy: logging and monitoring | ✅ | Audit log, CloudWatch alarms, metrics |
| Notify Amazon of incidents within 24 hours | 🟡 | In the incident runbook |
| Delete Amazon information when access is revoked or the purpose ends | ❌ | Must be built with M7 (connection removal → delete stored SP-API data and credentials) |
| Never scrape, never bypass CAPTCHAs or access controls | ✅ | Architectural rule; the extension reads URLs only, with no content scripts (M12) |
