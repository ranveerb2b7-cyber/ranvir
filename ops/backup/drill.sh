#!/usr/bin/env bash
# Restore drill: back up SOURCE, restore into a throwaway database, and prove the copy is
# complete and still secure. Exit code is non-zero if anything differs.
#
#   DRILL_SOURCE_URL  libpq URL of the database to back up (schema owner)
#   DRILL_ADMIN_URL   libpq URL that may CREATE/DROP DATABASE (same cluster or a restore host)
#   APP_DB_ROLE       application role whose grants must survive (default sellerscope_app)
set -euo pipefail

: "${DRILL_SOURCE_URL:?}" "${DRILL_ADMIN_URL:?}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROLE="${APP_DB_ROLE:-sellerscope_app}"
DB="sellerscope_restore_drill"
WORK="$(mktemp -d)"
TARGET="$(echo "$DRILL_ADMIN_URL" | sed -E "s#/[^/?]*(\?|$)#/$DB\1#")"
trap 'psql "$DRILL_ADMIN_URL" -qc "DROP DATABASE IF EXISTS $DB" >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT

started=$(date +%s)
BACKUP_DATABASE_URL="$DRILL_SOURCE_URL" BACKUP_DIR="$WORK" "$HERE/backup.sh"
DUMP="$(ls "$WORK"/*.dump)"
psql "$DRILL_ADMIN_URL" -qc "DROP DATABASE IF EXISTS $DB" -c "CREATE DATABASE $DB"
"$HERE/restore.sh" "$DUMP" "$TARGET"
elapsed=$(( $(date +%s) - started ))

COUNTS="SELECT string_agg(t || '=' || n, ' ' ORDER BY t) FROM (
  SELECT c.relname AS t,
         (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I', c.relname),
          false, true, '')))[1]::text AS n
  FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
  WHERE s.nspname = 'public' AND c.relkind = 'r') x"
CHECKS="SELECT
  (SELECT version_num FROM alembic_version),
  (SELECT count(*) FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
    WHERE s.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity),
  (SELECT count(*) FROM pg_policies WHERE schemaname = 'public'),
  (SELECT count(*) FROM pg_proc p JOIN pg_namespace s ON s.oid = p.pronamespace
    WHERE s.nspname = 'public' AND p.prosecdef),
  (SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'trg_%_append_only'),
  (SELECT count(*) FROM information_schema.role_table_grants WHERE grantee = '$ROLE')"

fail=0
for q in "$COUNTS" "$CHECKS"; do
  a="$(psql "$DRILL_SOURCE_URL" -Atc "$q")"
  b="$(psql "$TARGET" -Atc "$q")"
  if [[ "$a" != "$b" ]]; then
    echo "MISMATCH"; echo " source:   $a"; echo " restored: $b"; fail=1
  fi
done
checks="$(psql "$TARGET" -Atc "$CHECKS")"
IFS='|' read -r version rls policies definer appendonly grants <<<"$checks"
rows="$(psql "$TARGET" -Atc "$COUNTS" | tr ' ' '\n' | awk -F= '{s+=$2} END {print s}')"
echo "restore drill: $([[ $fail == 0 ]] && echo PASSED || echo FAILED) in ${elapsed}s"
echo "  migration $version; $rows rows across all tables (identical to source)"
echo "  RLS on $rls tables, $policies policies, $definer SECURITY DEFINER functions,"
echo "  $appendonly append-only triggers, $grants grants to $ROLE (identical to source)"
exit $fail
