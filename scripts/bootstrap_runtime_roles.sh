#!/usr/bin/env sh
set -eu

db_name="${POSTGRES_DB:-pharma}"
db_user="${POSTGRES_USER:-pharma_admin}"

auth_password="${PHARMA_DB_AUTH_PASSWORD:-local_auth_only}"
limited_password="${PHARMA_DB_LIMITED_PASSWORD:-local_limited_only}"
exec_password="${PHARMA_DB_EXEC_PASSWORD:-local_exec_only}"

set_login_password() {
  role_name="$1"
  role_password="$2"

  docker compose exec -T postgres psql \
    --username "$db_user" \
    --dbname "$db_name" \
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

set_login_password pharma_runtime_auth "$auth_password"
set_login_password pharma_runtime_limited "$limited_password"
set_login_password pharma_runtime_exec "$exec_password"

echo "Runtime database logins enabled for local development."
