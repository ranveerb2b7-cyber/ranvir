# Incident response

## Severity
| Level | Examples | Response |
|---|---|---|
| SEV1 | Data of one organization visible to another, credentials leaked, data loss, total outage | Start immediately, all hands; regulatory clock may be running (below) |
| SEV2 | Scans or alerts not running for everyone, error rate > 5%, Amazon access revoked | Within 1 hour |
| SEV3 | One customer affected, degraded performance | Next business day |

## When an alarm fires (CloudWatch → SNS email)
| Alarm | First checks |
|---|---|
| `api-5xx` | CloudWatch logs `/sellerscope/<env>/api` for `"level": "error"` and the `request_id`. Was a deploy in the last hour? Then roll back (deploy.md). |
| `api-latency` | `sellerscope_http_request_duration_seconds` by route; RDS Performance Insights (slow queries are logged above 500 ms). |
| `api-unhealthy` | `/api/v1/health/ready` says which dependency (database or Redis) is failing. |
| `db-cpu`, `db-storage` | Performance Insights; scale the instance class or storage (Terraform). |
| `redis-memory` | `sellerscope_queue_length`: a growing queue means workers are down or too slow. Check worker logs and scale `worker_desired_count`. |

App-level signals from `/metrics` (see observability.md) cover what CloudWatch can't: scan backlog age, scan error rate, alert emails that gave up, and failed reports.

## Security incident or personal-data breach
1. **Contain:**
   - Revoke the exposed credentials (secrets-rotation.md).
   - Disable affected accounts or extension tokens.
   - Block the source at the ALB or WAF.
   - Preserve logs: CloudWatch, `audit_logs` (append-only), and ALB logs if enabled.
2. **Assess:** which organizations, what data (product data, seller data, user emails), and when. `audit_logs` records who did what, with IP and user agent.
3. **Notify (India).** Get legal review; these are the obligations as understood when written:
   - **CERT-In:** report cyber incidents within **6 hours** of noticing them (CERT-In Directions, April 2022).
   - **DPDP Act 2023:** notify the Data Protection Board and affected users of a personal-data breach, in the form and time set by the DPDP Rules.
   - **Amazon (once SP-API is live, M7):** the Data Protection Policy requires notifying Amazon of incidents involving Amazon information within **24 hours** of detection, to security@amazon.com.
   - **Affected customers:** contractual notice per the DPA.
4. **Recover and review:** restore if needed (backup-restore.md); write a blameless post-incident review within 5 business days, with action items tracked.

Keep an incident log (time-stamped actions and decisions) from the first minute.
