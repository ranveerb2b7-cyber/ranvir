# Secrets rotation

| Secret | Where | Rotate | How |
|---|---|---|---|
| App DB password (`sellerscope_app`) | `DATABASE_URL` secret | Every 90 days; immediately if exposed | `ALTER ROLE sellerscope_app PASSWORD '<new>'`, update the secret, force a new ECS deployment |
| Owner DB password | `DB_MASTER_PASSWORD`, `MIGRATION_DATABASE_URL` | Every 90 days | Change in RDS (`aws rds modify-db-instance --master-user-password`), then update both secrets |
| Redis AUTH token | `REDIS_AUTH_TOKEN`, `REDIS_URL` | Every 180 days | ElastiCache `modify-replication-group --auth-token --auth-token-update-strategy ROTATE`, update `REDIS_URL`, redeploy, then `SET` the strategy to drop the old token |
| `METRICS_TOKEN` | secret + the Prometheus scraper | Every 180 days | Update both, then redeploy |
| SES SMTP password | `SMTP_PASSWORD` | Every 90 days | Create new SES SMTP credentials, update the secret, redeploy, delete the old IAM key |
| Supabase keys | Supabase dashboard | When a team member with access leaves | JWT signing keys rotate in Supabase; the API reads JWKS, so no redeploy is needed |
| Extension tokens | `extension_tokens` (hashed) | Users revoke in Settings; they expire after 90 days | To revoke everyone's: `UPDATE extension_tokens SET revoked_at = now() WHERE revoked_at IS NULL` |
| Amazon SP-API (M7) | encrypted connection credentials | Per Amazon's rules | Documented in M7 |

When someone with production access leaves:
- Remove their AWS IAM access.
- Rotate every secret they could read.
- Review `audit_logs` for their last 30 days.
