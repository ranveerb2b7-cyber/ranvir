#!/usr/bin/env bash
# Restores a backup.sh dump into an EMPTY database (never over a live one).
#
#   restore.sh <dump-file> <target-database-url>
# The application role (APP_DB_ROLE, default sellerscope_app) must already exist in the
# target cluster so its grants are restored; RLS policies and functions come with the dump.
set -euo pipefail

DUMP="${1:?usage: restore.sh <dump-file> <target-database-url>}"
TARGET="${2:?usage: restore.sh <dump-file> <target-database-url>}"

if [[ -f "$DUMP.sha256" ]]; then
  (cd "$(dirname "$DUMP")" && sha256sum --check --status "$(basename "$DUMP").sha256") \
    || { echo "checksum mismatch: $DUMP" >&2; exit 1; }
fi
tables="$(psql "$TARGET" -Atc "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")"
if [[ "$tables" != "0" ]]; then
  echo "refusing to restore: the target database is not empty ($tables tables)" >&2
  exit 1
fi
pg_restore --no-owner --exit-on-error --single-transaction --dbname="$TARGET" "$DUMP"
echo "restored $DUMP"
