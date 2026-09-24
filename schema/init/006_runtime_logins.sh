#!/usr/bin/env sh
set -eu

set_login_password() {
  role_name="$1"
  role_password="$2"

  psql \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set ON_ERROR_STOP=1 \
    --set role_name="$role_name" \
    --set role_password="$role_password" <<'SQL'
SELECT format(
    'ALTER ROLE %I LOGIN PASSWORD %L',
    :'role_name',
    :'role_password'
) \gexec
SQL
}

set_login_password \
  pharma_runtime_auth \
  "${PHARMA_DB_AUTH_PASSWORD:-local_auth_only}"
set_login_password \
  pharma_runtime_limited \
  "${PHARMA_DB_LIMITED_PASSWORD:-local_limited_only}"
set_login_password \
  pharma_runtime_exec \
  "${PHARMA_DB_EXEC_PASSWORD:-local_exec_only}"
