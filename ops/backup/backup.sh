#!/usr/bin/env bash
# Logical backup of the SellerScope database (pg_dump custom format) with a SHA-256 checksum.
# Production relies on the managed database's automated backups + point-in-time recovery
# (see docs/runbooks/backup-restore.md); this script is for extra off-site copies, pre-upgrade
# snapshots and restore drills.
#
#   BACKUP_DATABASE_URL  libpq URL of the schema OWNER (postgresql://user:pass@host:5432/db)
#   BACKUP_DIR           local directory for the dump (default ./backups)
#   BACKUP_S3_URI        optional, e.g. s3://sellerscope-backups/db/ (uploaded with SSE-KMS)
#   BACKUP_KMS_KEY_ID    optional KMS key for the upload (default: the bucket's default key)
set -euo pipefail

: "${BACKUP_DATABASE_URL:?set BACKUP_DATABASE_URL}"
DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$DIR/sellerscope-$STAMP.dump"
mkdir -p "$DIR"
umask 077  # dumps contain customer data

pg_dump --format=custom --compress=9 --no-password --file="$FILE" "$BACKUP_DATABASE_URL"
sha256sum "$FILE" >"$FILE.sha256"
echo "backup written: $FILE ($(du -h "$FILE" | cut -f1))"

if [[ -n "${BACKUP_S3_URI:-}" ]]; then
  sse=(--sse aws:kms)
  [[ -n "${BACKUP_KMS_KEY_ID:-}" ]] && sse+=(--sse-kms-key-id "$BACKUP_KMS_KEY_ID")
  aws s3 cp "$FILE" "$BACKUP_S3_URI" "${sse[@]}"
  aws s3 cp "$FILE.sha256" "$BACKUP_S3_URI" "${sse[@]}"
  echo "uploaded to $BACKUP_S3_URI"
fi
