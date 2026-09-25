#!/usr/bin/env sh
set -eu

admin_db="${POSTGRES_DB:-pharma}"
db_user="${POSTGRES_USER:-pharma_admin}"
full_db="${FULL_POSTGRES_DB:-pharma_full}"

case "$full_db" in
  *[!A-Za-z0-9_]*|'')
    echo "FULL_POSTGRES_DB must contain only letters, numbers, and underscores." >&2
    exit 2
    ;;
esac

for required_file in \
  schema/generated/organizations.csv \
  schema/generated/products.csv \
  schema/generated/sales.csv \
  schema/generated/zip_territory.csv
do
  if [ ! -f "$required_file" ]; then
    echo "Missing $required_file. Run: python3 schema/generate_data.py" >&2
    exit 2
  fi
done

database_exists="$(docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$admin_db" \
  --tuples-only \
  --no-align \
  --command "SELECT 1 FROM pg_database WHERE datname = '$full_db';" | sed '/^$/d')"

if [ "$database_exists" != "1" ]; then
  docker compose exec -T postgres createdb \
    --username "$db_user" \
    "$full_db"
fi

schema_exists="$(docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --tuples-only \
  --no-align \
  --command "SELECT to_regclass('public.sales') IS NOT NULL;" | sed '/^$/d')"

if [ "$schema_exists" = "t" ]; then
  echo "Database $full_db is already initialized; refusing to duplicate the full load." >&2
  echo "Choose another FULL_POSTGRES_DB value for a clean load." >&2
  exit 1
fi

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --set ON_ERROR_STOP=1 < schema/migrations/001_initial.sql

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --set ON_ERROR_STOP=1 \
  --command "
    COPY products (
      ndc, drug_name, generic_name, strength, form, brand_flag, specialty,
      market_category, market_subcategory, unit_conversion_factor, mg_equivalent
    ) FROM '/data/products.csv' WITH (FORMAT csv, HEADER true);
    COPY zip_territory (
      zip, state, territory_number, territory_name, region_number, region_name
    ) FROM '/data/zip_territory.csv' WITH (FORMAT csv, HEADER true);
    COPY organizations (
      org_id, org_name, org_type, org_status, org_archetype, specialty,
      address_line1, city, state, zip, parent_org_id, parent_org_name,
      grandparent_org_id, grandparent_org_name, gpo_name, is_340b
    ) FROM '/data/organizations.csv' WITH (FORMAT csv, HEADER true);
    COPY sales (
      org_id, ndc, drug_name, data_source, brand_flag, pack_units, total_mg,
      wac, transaction_date, week_ending_date, state, specialty, period_wk,
      period_mo, period_qtr, wk_offset, mo_offset
    ) FROM '/data/sales.csv' WITH (FORMAT csv, HEADER true);
  "

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --set ON_ERROR_STOP=1 < schema/seed_users.sql

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --set ON_ERROR_STOP=1 < schema/migrations/003_security.sql

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --set ON_ERROR_STOP=1 < schema/migrations/004_optimize_rls.sql

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --set ON_ERROR_STOP=1 < schema/migrations/006_weekly_sales_covering_index.sql

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --set ON_ERROR_STOP=1 \
  --command "ANALYZE;"

echo "Loaded full synthetic dataset into $full_db."
