#!/bin/sh
# LOCAL DEVELOPMENT ONLY. Creates a separate `auth` database for the self-hosted Supabase Auth
# (GoTrue) container. Staging/production use a hosted Supabase project instead.
set -eu

: "${AUTH_DB_PASSWORD:?AUTH_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v auth_password="$AUTH_DB_PASSWORD" <<'SQL'
CREATE ROLE supabase_auth_admin LOGIN NOINHERIT PASSWORD :'auth_password';
CREATE DATABASE auth OWNER supabase_auth_admin;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname auth <<'SQL'
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION supabase_auth_admin;
ALTER ROLE supabase_auth_admin SET search_path = auth;
SQL
