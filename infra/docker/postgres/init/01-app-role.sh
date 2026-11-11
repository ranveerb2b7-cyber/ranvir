#!/bin/sh
# Runs once, on first start of an empty Postgres volume (docker-entrypoint-initdb.d).
# Creates the restricted role the API connects as. Migrations run as POSTGRES_USER (owner)
# and grant this role table privileges; it never owns tables and cannot bypass RLS.
set -eu

: "${APP_DB_ROLE:?APP_DB_ROLE must be set}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_role="$APP_DB_ROLE" -v app_password="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE :"app_role" LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
SQL
