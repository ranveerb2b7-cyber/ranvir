#!/usr/bin/env bash
# Runs the accounts end-to-end test against a throwaway local stack:
#   PostgreSQL (fresh database) + Redis + SMTP sink + stub auth server + API + production web build.
#
# Requirements: local PostgreSQL 16 and Redis 7 running; `uv`, `pnpm`, and Playwright
# (require('playwright') resolvable) available.
#
# Env:
#   E2E_ADMIN_DATABASE_URL  libpq URL of a user that can CREATE DATABASE / CREATE ROLE
#                           (default postgresql://postgres@127.0.0.1:5432/postgres)
#   E2E_REDIS_URL           (default redis://127.0.0.1:6379/13)
#   E2E_WORKDIR             where logs, mail and screenshots go (default: a temp dir)
#
# The stub auth server is a TEST-ONLY stand-in for Supabase Auth; see e2e/README.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"
ADMIN_URL="${E2E_ADMIN_DATABASE_URL:-postgresql://postgres@127.0.0.1:5432/postgres}"
REDIS_URL="${E2E_REDIS_URL:-redis://127.0.0.1:6379/13}"
WORK="${E2E_WORKDIR:-$(mktemp -d)}"
DB=sellerscope_e2e
APP_ROLE=sellerscope_app_e2e
APP_PW="e2e-$(openssl rand -hex 8)"
SECRET="$(openssl rand -hex 32)"
PG_HOSTPORT="$(echo "$ADMIN_URL" | sed -E 's#^[a-z]+://([^@]*@)?([^/]+)/.*#\2#')"
OWNER_URL="$(echo "$ADMIN_URL" | sed -E "s#/[^/]*\$#/$DB#; s#^postgresql://#postgresql+asyncpg://#")"

mkdir -p "$WORK"/{maildir/new,maildir/cur,maildir/tmp,shots,logs}
pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

echo "› database $DB"
psql "$ADMIN_URL" -q -v ON_ERROR_STOP=1 <<SQL
DROP DATABASE IF EXISTS $DB;
CREATE DATABASE $DB;
DO \$\$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_ROLE') THEN
    ALTER ROLE $APP_ROLE LOGIN PASSWORD '$APP_PW';
  ELSE
    CREATE ROLE $APP_ROLE LOGIN PASSWORD '$APP_PW' NOSUPERUSER NOBYPASSRLS;
  END IF;
END \$\$;
SQL
(cd "$API" && MIGRATION_DATABASE_URL="$OWNER_URL" APP_DB_ROLE=$APP_ROLE uv run alembic upgrade head >"$WORK/logs/migrate.log" 2>&1)

echo "› services"
(cd "$API" && exec uv run python -m aiosmtpd -n -l 127.0.0.1:1025 -c aiosmtpd.handlers.Mailbox "$WORK/maildir") >"$WORK/logs/smtp.log" 2>&1 &
pids+=($!)
(cd "$WEB" && STUB_JWT_SECRET="$SECRET" STUB_PORT=9999 exec node e2e/stub-auth.mjs) >"$WORK/logs/stub.log" 2>&1 &
pids+=($!)
export STORAGE_BACKEND=local STORAGE_LOCAL_DIR="$WORK/storage"
API_ENV=(APP_ENV=development ENABLE_MOCK_CONNECTOR=true
  DATABASE_URL="postgresql+asyncpg://$APP_ROLE:$APP_PW@$PG_HOSTPORT/$DB" REDIS_URL="$REDIS_URL"
  AUTH_JWT_ISSUER=http://127.0.0.1:9999/auth/v1 AUTH_JWT_SECRET="$SECRET"
  WEB_BASE_URL=http://localhost:3100 CORS_ORIGINS=http://localhost:3100 SMTP_HOST=127.0.0.1 SMTP_PORT=1025)
# Celery worker: parses uploads exactly as in production (no inline shortcut).
(cd "$API" && exec env "${API_ENV[@]}" uv run celery -A sellerscope.workers.celery_app worker \
  -Q imports,scans.amazon,default -c 2 --loglevel=INFO) >"$WORK/logs/worker.log" 2>&1 &
pids+=($!)
(cd "$API" && APP_ENV=development ENABLE_MOCK_CONNECTOR=true \
  DATABASE_URL="postgresql+asyncpg://$APP_ROLE:$APP_PW@$PG_HOSTPORT/$DB" REDIS_URL="$REDIS_URL" \
  AUTH_JWT_ISSUER=http://127.0.0.1:9999/auth/v1 AUTH_JWT_SECRET="$SECRET" \
  WEB_BASE_URL=http://localhost:3100 CORS_ORIGINS=http://localhost:3100 SMTP_HOST=127.0.0.1 SMTP_PORT=1025 \
  exec uv run uvicorn sellerscope.asgi:app --port 8000) >"$WORK/logs/api.log" 2>&1 &
pids+=($!)

echo "› web build"
export NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:9999 \
  NEXT_PUBLIC_SUPABASE_ANON_KEY=e2e-placeholder-anon-key NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
(cd "$WEB" && npx next build >"$WORK/logs/build.log" 2>&1 && cp -r .next/static .next/standalone/apps/web/.next/)
(cd "$WEB" && PORT=3100 HOSTNAME=127.0.0.1 exec node .next/standalone/apps/web/server.js) >"$WORK/logs/web.log" 2>&1 &
pids+=($!)

for url in http://localhost:8000/api/v1/health/ready http://localhost:3100/login; do
  for _ in $(seq 1 60); do curl -sf -o /dev/null "$url" && break; sleep 1; done
  curl -sf -o /dev/null "$url" || { echo "not ready: $url (see $WORK/logs)"; exit 1; }
done

echo "› e2e"
export E2E_BASE_URL=http://localhost:3100 E2E_API_URL=http://localhost:8000/api/v1 \
  E2E_AUTH_URL=http://127.0.0.1:9999/auth/v1 E2E_MAILDIR="$WORK/maildir" E2E_SCREENSHOTS="$WORK/shots"
export E2E_WORKDIR="$WORK"
(cd "$WEB" && node e2e/accounts.e2e.mjs && node e2e/products.e2e.mjs && node e2e/uploads.e2e.mjs \
  && node e2e/scans.e2e.mjs)
echo "logs and screenshots: $WORK"
