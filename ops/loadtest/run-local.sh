#!/usr/bin/env bash
# Load test on a throwaway LOCAL stack: PostgreSQL (fresh DB) + Redis + Celery worker + API
# (uvicorn, LOAD_API_WORKERS processes). Seeds LOAD_PRODUCTS scanned (MOCK) products, then runs
# locust headless and checks the targets in docs/runbooks/load-testing.md.
#
# Local numbers measure this machine, not production capacity. Re-run against staging.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="$ROOT/apps/api"
HERE="$ROOT/ops/loadtest"
ADMIN_URL="${E2E_ADMIN_DATABASE_URL:-postgresql://postgres@127.0.0.1:5432/postgres}"
REDIS_URL="${LOAD_REDIS_URL:-redis://127.0.0.1:6379/12}"
WORK="${LOAD_WORKDIR:-$(mktemp -d)}"
USERS="${LOAD_USERS:-50}"
DURATION="${LOAD_DURATION:-90s}"
PRODUCTS="${LOAD_PRODUCTS:-100}"  # the trial plan allows 100
WORKERS="${LOAD_API_WORKERS:-2}"
P95_MS="${LOAD_TARGET_P95_MS:-500}"
MIN_RPS="${LOAD_TARGET_RPS:-30}"
DB=sellerscope_load
ROLE=sellerscope_app_load
PW="load-$(openssl rand -hex 8)"
SECRET="$(openssl rand -hex 32)"
ISSUER=http://127.0.0.1:9998/auth/v1
HOSTPORT="$(echo "$ADMIN_URL" | sed -E 's#^[a-z]+://([^@]*@)?([^/]+)/.*#\2#')"
OWNER_URL="$(echo "$ADMIN_URL" | sed -E "s#/[^/]*\$#/$DB#; s#^postgresql://#postgresql+asyncpg://#")"
mkdir -p "$WORK"
pids=()
trap 'for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done' EXIT

psql "$ADMIN_URL" -q -v ON_ERROR_STOP=1 <<SQL
DROP DATABASE IF EXISTS $DB;
CREATE DATABASE $DB;
DO \$\$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$ROLE') THEN
    ALTER ROLE $ROLE LOGIN PASSWORD '$PW';
  ELSE CREATE ROLE $ROLE LOGIN PASSWORD '$PW' NOSUPERUSER NOBYPASSRLS; END IF;
END \$\$;
SQL
(cd "$API" && MIGRATION_DATABASE_URL="$OWNER_URL" APP_DB_ROLE=$ROLE uv run alembic upgrade head >"$WORK/migrate.log" 2>&1)
redis-cli -u "$REDIS_URL" flushdb >/dev/null

ENV=(APP_ENV=development ENABLE_MOCK_CONNECTOR=true LOG_LEVEL=WARNING
  DATABASE_URL="postgresql+asyncpg://$ROLE:$PW@$HOSTPORT/$DB" REDIS_URL="$REDIS_URL"
  AUTH_JWT_ISSUER="$ISSUER" AUTH_JWT_SECRET="$SECRET" STORAGE_BACKEND=local
  STORAGE_LOCAL_DIR="$WORK/storage" RATE_LIMIT_IP_PER_MINUTE=1000000)
(cd "$API" && exec env "${ENV[@]}" uv run celery -A sellerscope.workers.celery_app worker \
  -Q imports,scans.amazon,alerts,default -c 2 --loglevel=WARNING) >"$WORK/worker.log" 2>&1 &
pids+=($!)
(cd "$API" && exec env "${ENV[@]}" uv run uvicorn sellerscope.asgi:app --port 8100 \
  --workers "$WORKERS" --no-access-log) >"$WORK/api.log" 2>&1 &
pids+=($!)
for _ in $(seq 1 60); do curl -sf -o /dev/null http://127.0.0.1:8100/api/v1/health/ready && break; sleep 1; done

echo "› seeding $PRODUCTS products (uploaded and scanned through the worker)"
read -r ORG USER_ID < <(cd "$API" && uv run python "$HERE/seed.py" http://127.0.0.1:8100/api/v1 "$SECRET" "$ISSUER" "$PRODUCTS" 2>"$WORK/seed.log")
cat "$WORK/seed.log"

echo "› locust: $USERS users for $DURATION against $WORKERS API processes"
(cd "$API" && LOAD_ORG_ID="$ORG" LOAD_USER_ID="$USER_ID" LOAD_JWT_SECRET="$SECRET" LOAD_JWT_ISSUER="$ISSUER" \
  uv run --with "locust==2.43.4" locust -f "$HERE/locustfile.py" --host http://127.0.0.1:8100 \
  --headless -u "$USERS" -r 10 -t "$DURATION" --csv "$WORK/result" --only-summary) >"$WORK/locust.log" 2>&1 || true

python3 - "$WORK/result_stats.csv" "$P95_MS" "$MIN_RPS" <<'PY'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
p95_limit, min_rps = float(sys.argv[2]), float(sys.argv[3])
total = next(r for r in rows if r["Name"] == "Aggregated")
print(f"{'endpoint':<20}{'requests':>9}{'fails':>7}{'median ms':>11}{'p95 ms':>9}{'p99 ms':>9}")
for r in rows:
    print(f"{r['Name']:<20}{r['Request Count']:>9}{r['Failure Count']:>7}{r['Median Response Time']:>11}"
          f"{r['95%']:>9}{r['99%']:>9}")
rps = float(total["Requests/s"]); p95 = float(total["95%"])
fails = int(total["Failure Count"]) / max(int(total["Request Count"]), 1)
ok = p95 <= p95_limit and fails < 0.01 and rps >= min_rps
print(f"throughput {rps:.1f} req/s (target >= {min_rps}); p95 {p95:.0f} ms (target <= {p95_limit:.0f}); "
      f"errors {fails:.2%} (target < 1%) -> {'PASSED' if ok else 'FAILED'}")
sys.exit(0 if ok else 1)
PY
