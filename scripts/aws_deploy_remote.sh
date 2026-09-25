#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: $0 s3://bucket/full-data-prefix app-runtime-secret-arn [release-id]" >&2
    exit 2
fi

data_uri="${1%/}"
runtime_secret_arn="$2"
release_id="${3:-manual}"
source_dir="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
app_dir="/opt/pharma-nl2sql"
data_dir="$app_dir/data"
backend_container="pharma-backend"
frontend_container="pharma-frontend"
network_name="pharma-app"

# shellcheck source=/dev/null
source /opt/pharma-nl2sql/infrastructure.env

if ! command -v psql >/dev/null 2>&1; then
    dnf install -y postgresql16 >/dev/null
fi

mkdir -p "$data_dir"
aws s3 sync "$data_uri" "$data_dir" --exclude '*' --include '*.csv' --only-show-errors
(
    cd "$data_dir"
    sha256sum --check "$source_dir/deploy/full_data.sha256"
)

master_secret="$(aws secretsmanager get-secret-value \
    --secret-id "$DATABASE_SECRET_ARN" \
    --query SecretString \
    --output text)"
master_username="$(jq -er '.username' <<<"$master_secret")"
master_password="$(jq -er '.password' <<<"$master_secret")"
unset master_secret

export PGPASSWORD="$master_password"
admin_connection="host=$DATABASE_HOST port=$DATABASE_PORT dbname=$DATABASE_NAME user=$master_username sslmode=require"

schema_exists="$(psql "$admin_connection" --tuples-only --no-align \
    --command "SELECT to_regclass('public.sales') IS NOT NULL;")"
if [[ "$schema_exists" != "t" ]]; then
    psql "$admin_connection" --set ON_ERROR_STOP=1 \
        --file "$source_dir/schema/migrations/001_initial.sql" >/dev/null
fi

current_counts="$(psql "$admin_connection" --tuples-only --no-align --command \
    "SELECT (SELECT count(*) FROM organizations) || ':' ||
            (SELECT count(*) FROM products) || ':' ||
            (SELECT count(*) FROM zip_territory) || ':' ||
            (SELECT count(*) FROM sales) || ':' ||
            (SELECT count(*) FROM users);")"

if [[ "$current_counts" != "40000:40:29728:2000000:23" ]]; then
    load_script="$(mktemp /tmp/pharma-full-load.XXXXXX.sql)"
    trap 'rm -f "$load_script"; unset PGPASSWORD master_password auth_password limited_password exec_password session_secret' EXIT
    cat >"$load_script" <<SQL
\set ON_ERROR_STOP on
BEGIN;
ALTER TABLE organizations DISABLE ROW LEVEL SECURITY;
ALTER TABLE sales DISABLE ROW LEVEL SECURITY;
TRUNCATE sales, users, organizations, products, zip_territory RESTART IDENTITY CASCADE;
\copy products (ndc, drug_name, generic_name, strength, form, brand_flag, specialty, market_category, market_subcategory, unit_conversion_factor, mg_equivalent) FROM '$data_dir/products.csv' WITH (FORMAT csv, HEADER true)
\copy zip_territory (zip, state, territory_number, territory_name, region_number, region_name) FROM '$data_dir/zip_territory.csv' WITH (FORMAT csv, HEADER true)
\copy organizations (org_id, org_name, org_type, org_status, org_archetype, specialty, address_line1, city, state, zip, parent_org_id, parent_org_name, grandparent_org_id, grandparent_org_name, gpo_name, is_340b) FROM '$data_dir/organizations.csv' WITH (FORMAT csv, HEADER true)
\copy sales (org_id, ndc, drug_name, data_source, brand_flag, pack_units, total_mg, wac, transaction_date, week_ending_date, state, specialty, period_wk, period_mo, period_qtr, wk_offset, mo_offset) FROM '$data_dir/sales.csv' WITH (FORMAT csv, HEADER true)
\i '$source_dir/schema/seed_users.sql'
COMMIT;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
ALTER TABLE sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales FORCE ROW LEVEL SECURITY;
SQL
    psql "$admin_connection" --file "$load_script" >/dev/null
    rm -f "$load_script"
fi

for migration in \
    003_security.sql \
    004_optimize_rls.sql \
    005_runtime_access.sql \
    006_weekly_sales_covering_index.sql
do
    psql "$admin_connection" --set ON_ERROR_STOP=1 \
        --file "$source_dir/schema/migrations/$migration" >/dev/null
done

psql "$admin_connection" --set ON_ERROR_STOP=1 >/dev/null <<'SQL'
ANALYZE;
DO $quality$
BEGIN
  IF (SELECT count(*) FROM organizations) <> 40000 THEN
    RAISE EXCEPTION 'expected 40000 organizations';
  END IF;
  IF (SELECT count(*) FROM products) <> 40 THEN
    RAISE EXCEPTION 'expected 40 products';
  END IF;
  IF (SELECT count(*) FROM zip_territory) <> 29728 THEN
    RAISE EXCEPTION 'expected 29728 ZIP mappings';
  END IF;
  IF (SELECT count(*) FROM sales) <> 2000000 THEN
    RAISE EXCEPTION 'expected 2000000 sales';
  END IF;
  IF (SELECT count(*) FROM users) <> 23 THEN
    RAISE EXCEPTION 'expected 23 users';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_class AS index_relation
    JOIN pg_index AS index_metadata
      ON index_metadata.indexrelid = index_relation.oid
    WHERE index_relation.relname = 'sales_week_source_brand_org_cover_idx'
      AND index_relation.relnamespace = 'public'::regnamespace
      AND index_metadata.indisready
      AND index_metadata.indisvalid
  ) THEN
    RAISE EXCEPTION 'weekly sales covering index is missing or invalid';
  END IF;
END
$quality$;
SQL

if runtime_secret="$(aws secretsmanager get-secret-value \
    --secret-id "$runtime_secret_arn" \
    --query SecretString \
    --output text 2>/dev/null)"; then
    jq -e \
        '(.auth_password | type == "string" and length >= 32) and
         (.limited_password | type == "string" and length >= 32) and
         (.exec_password | type == "string" and length >= 32) and
         (.session_secret | type == "string" and length >= 32)' \
        <<<"$runtime_secret" >/dev/null
else
    runtime_secret="$(jq -cn \
        --arg auth_password "$(openssl rand -hex 24)" \
        --arg limited_password "$(openssl rand -hex 24)" \
        --arg exec_password "$(openssl rand -hex 24)" \
        --arg session_secret "$(openssl rand -hex 32)" \
        '{auth_password:$auth_password,limited_password:$limited_password,exec_password:$exec_password,session_secret:$session_secret}')"
    aws secretsmanager put-secret-value \
        --secret-id "$runtime_secret_arn" \
        --secret-string "$runtime_secret" >/dev/null
fi

auth_password="$(jq -er '.auth_password' <<<"$runtime_secret")"
limited_password="$(jq -er '.limited_password' <<<"$runtime_secret")"
exec_password="$(jq -er '.exec_password' <<<"$runtime_secret")"
session_secret="$(jq -er '.session_secret' <<<"$runtime_secret")"
openai_api_key="$(jq -r '.openai_api_key // empty' <<<"$runtime_secret")"
unset runtime_secret

psql "$admin_connection" \
    --set ON_ERROR_STOP=1 \
    --set auth_password="$auth_password" \
    --set limited_password="$limited_password" \
    --set exec_password="$exec_password" >/dev/null <<'SQL'
ALTER ROLE pharma_runtime_auth LOGIN PASSWORD :'auth_password';
ALTER ROLE pharma_runtime_limited LOGIN PASSWORD :'limited_password';
ALTER ROLE pharma_runtime_exec LOGIN PASSWORD :'exec_password';
SQL

cat >"$app_dir/backend.env" <<ENVFILE
PHARMA_ENVIRONMENT=demo
PHARMA_DB_HOST=$DATABASE_HOST
PHARMA_DB_PORT=$DATABASE_PORT
PHARMA_DB_NAME=$DATABASE_NAME
PHARMA_DB_AUTH_USER=pharma_runtime_auth
PHARMA_DB_AUTH_PASSWORD=$auth_password
PHARMA_DB_LIMITED_USER=pharma_runtime_limited
PHARMA_DB_LIMITED_PASSWORD=$limited_password
PHARMA_DB_EXEC_USER=pharma_runtime_exec
PHARMA_DB_EXEC_PASSWORD=$exec_password
PHARMA_SESSION_SECRET=$session_secret
PHARMA_COOKIE_SECURE=false
PHARMA_OPENAI_API_KEY=$openai_api_key
PHARMA_OPENAI_MODEL=gpt-5.6-sol
PHARMA_OPENAI_REASONING_EFFORT=medium
PHARMA_OPENAI_REQUEST_TIMEOUT_SECONDS=20
PHARMA_AGENT_REQUEST_TIMEOUT_SECONDS=42
PHARMA_AGENT_SUMMARY_TIMEOUT_SECONDS=6
PHARMA_AGENT_MAX_REPAIRS=1
PHARMA_AGENT_MAX_ROWS=100
ENVFILE
chmod 600 "$app_dir/backend.env"

unset PGPASSWORD master_password auth_password limited_password exec_password session_secret openai_api_key

docker build --file "$source_dir/backend/Dockerfile" --tag pharma-backend:latest "$source_dir"
docker build --file "$source_dir/frontend/Dockerfile" --tag pharma-frontend:latest "$source_dir/frontend"

docker network inspect "$network_name" >/dev/null 2>&1 || docker network create "$network_name" >/dev/null
docker rm --force "$frontend_container" "$backend_container" >/dev/null 2>&1 || true
systemctl disable --now nginx >/dev/null 2>&1 || true

docker run --detach \
    --name "$backend_container" \
    --network "$network_name" \
    --network-alias backend \
    --restart unless-stopped \
    --log-driver awslogs \
    --log-opt "awslogs-region=$AWS_REGION" \
    --log-opt "awslogs-group=$LOG_GROUP_NAME" \
    --log-opt "awslogs-stream=$backend_container" \
    --env-file "$app_dir/backend.env" \
    pharma-backend:latest >/dev/null

for _ in {1..60}; do
    if docker exec "$backend_container" python -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)" \
        >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

if ! docker exec "$backend_container" python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"; then
    docker logs "$backend_container" >&2
    exit 1
fi

docker run --detach \
    --name "$frontend_container" \
    --network "$network_name" \
    --restart unless-stopped \
    --log-driver awslogs \
    --log-opt "awslogs-region=$AWS_REGION" \
    --log-opt "awslogs-group=$LOG_GROUP_NAME" \
    --log-opt "awslogs-stream=$frontend_container" \
    --publish 80:80 \
    pharma-frontend:latest >/dev/null

for _ in {1..30}; do
    if curl --fail --silent http://127.0.0.1/health >/dev/null; then
        break
    fi
    sleep 2
done

if ! curl --fail --silent http://127.0.0.1/ready; then
    docker logs "$frontend_container" >&2
    exit 1
fi
printf '%s\n' "$release_id" >"$app_dir/current-release"
echo
echo "AWS application deployment passed for release $release_id with full-data quality and container health checks."
