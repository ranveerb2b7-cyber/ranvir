# Backup and restore

## What protects the data
| Layer | What | Recovery point (RPO) | Status |
|---|---|---|---|
| RDS automated backups + point-in-time recovery | Daily snapshot + transaction logs, kept 14 days (staging) / 35 days (production) | ~5 minutes | ⚠ configured in Terraform, not yet applied |
| Multi-AZ (production) | Synchronous standby in a second AZ | 0 (failover in 1–2 min) | ⚠ configured, not applied |
| Logical dumps (`ops/backup/backup.sh`) | `pg_dump` custom format + SHA-256, uploaded to the backups bucket (SSE-KMS, versioned, 35 days) | Last dump | ✅ script tested locally |
| S3 versioning | Uploaded files and reports keep previous versions for 30 days | 0 | ⚠ configured, not applied |

**Recovery time objective (RTO):** under 2 hours for a full point-in-time restore of a database up to tens of GB.

## Restore drill (quarterly, and before launch)
```bash
DRILL_SOURCE_URL=postgresql://owner:…@host/sellerscope \
DRILL_ADMIN_URL=postgresql://owner:…@restore-host/postgres \
APP_DB_ROLE=sellerscope_app ./ops/backup/drill.sh
```
**What the drill does:**
1. Backs up the source.
2. Restores into a throwaway database.
3. Compares the copy with the source: the migration version, the row count of every table, and the RLS, policies, SECURITY DEFINER functions, append-only triggers and grants to the app role.

It exits non-zero on any difference.

**Last run, 2026-11-12, local** (on the e2e database: migration 0010, 485 rows):
```
restore drill: PASSED in 1s
  migration 0010; 485 rows across all tables (identical to source)
  RLS on 22 tables, 25 policies, 11 SECURITY DEFINER functions,
  4 append-only triggers, 82 grants to sellerscope_app_e2e (identical to source)
```
⚠ Not yet run against an RDS point-in-time restore.

## Point-in-time restore (production) ⚠
1. **Decide the target time (UTC),** just before the incident. Record it in the incident log.
2. **Restore to a NEW instance.** Never overwrite the live one:
   ```bash
   aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier sellerscope-production \
     --target-db-instance-identifier sellerscope-production-pitr --restore-time <ISO-8601> \
     --db-subnet-group-name sellerscope-production --vpc-security-group-ids <data sg> --no-publicly-accessible
   ```
3. **Verify the copy:** run `drill.sh`'s checks against it (set `DRILL_SOURCE_URL` to the restored instance), and spot-check the affected organization's data.
4. **Choose a recovery:**
   - **Partial:** copy the affected rows back with SQL, as the owner, inside a transaction. Snapshot tables are append-only, so most incidents need only additive repairs.
   - **Full:** point the `DATABASE_URL` and `MIGRATION_DATABASE_URL` secrets at the restored instance, then force a new ECS deployment.
5. **Keep the old instance** for 7 days, then delete it with a final snapshot.

## Single file restore
To bring back an overwritten or deleted file, restore its previous S3 object version:
```bash
aws s3api list-object-versions --bucket <files bucket> --prefix org/<org-id>/
```
