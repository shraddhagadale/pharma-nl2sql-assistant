#!/usr/bin/env sh
set -eu

db_name="${POSTGRES_DB:-pharma}"
db_user="${POSTGRES_USER:-pharma_admin}"

raw_query_as() {
  db_role="$1"
  app_user_id="$2"
  query="$3"

  docker compose exec -T postgres psql \
    --username "$db_user" \
    --dbname "$db_name" \
    --set ON_ERROR_STOP=1 \
    --tuples-only \
    --no-align \
    --command "
      BEGIN;
      SET LOCAL ROLE $db_role;
      SET LOCAL app.user_id = '$app_user_id';
      $query
      ROLLBACK;
    "
}

query_as() {
  raw_output="$(raw_query_as "$1" "$2" "$3")"
  printf '%s\n' "$raw_output" | sed '/^SET$/d; /^BEGIN$/d; /^ROLLBACK$/d; /^$/d'
}

ram_territories="$(query_as pharma_app_limited U009 "
  SELECT string_agg(DISTINCT zt.territory_name, ',' ORDER BY zt.territory_name)
  FROM organizations AS o
  JOIN zip_territory AS zt ON zt.zip = o.zip;
")"
[ "$ram_territories" = "New York Metro" ] || {
  echo "RAM scope failed: $ram_territories" >&2
  exit 1
}

director_regions="$(query_as pharma_app_limited U003 "
  SELECT string_agg(DISTINCT zt.region_name, ',' ORDER BY zt.region_name)
  FROM organizations AS o
  JOIN zip_territory AS zt ON zt.zip = o.zip;
")"
[ "$director_regions" = "Northeast" ] || {
  echo "Director scope failed: $director_regions" >&2
  exit 1
}

exec_visible="$(query_as pharma_app_exec U001 "SELECT count(*) FROM organizations;")"
all_organizations="$(docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$db_name" \
  --tuples-only \
  --no-align \
  --command "SELECT count(*) FROM organizations;" | sed '/^$/d')"
[ "$exec_visible" = "$all_organizations" ] || {
  echo "Exec scope failed: visible=$exec_visible total=$all_organizations" >&2
  exit 1
}

exec_on_limited_pool="$(query_as pharma_app_limited U001 "SELECT count(*) FROM organizations;")"
[ "$exec_on_limited_pool" = "0" ] || {
  echo "Limited pool accepted an executive context" >&2
  exit 1
}

unknown_user_visible="$(query_as pharma_app_limited UNKNOWN "SELECT count(*) FROM organizations;")"
[ "$unknown_user_visible" = "0" ] || {
  echo "Unknown user context did not fail closed" >&2
  exit 1
}

ram_market_territories="$(query_as pharma_app_limited U009 "
  SELECT COALESCE(string_agg(DISTINCT zt.territory_name, ',' ORDER BY zt.territory_name), '')
  FROM sales AS s
  JOIN organizations AS o ON o.org_id = s.org_id
  JOIN zip_territory AS zt ON zt.zip = o.zip
  WHERE s.data_source = 'market_data';
")"
case "$ram_market_territories" in
  ""|"New York Metro") ;;
  *)
    echo "Market-data scope failed: $ram_market_territories" >&2
    exit 1
    ;;
esac

if raw_query_as pharma_app_limited U009 "SELECT wac FROM sales LIMIT 1;" >/dev/null 2>&1; then
  echo "Limited role unexpectedly read WAC" >&2
  exit 1
fi

raw_query_as pharma_app_exec U001 "SELECT wac FROM sales LIMIT 1;" >/dev/null

limited_wac_privilege="$(docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$db_name" \
  --tuples-only \
  --no-align \
  --command "SELECT has_column_privilege('pharma_app_limited', 'sales', 'wac', 'SELECT');" \
  | sed '/^$/d')"
[ "$limited_wac_privilege" = "f" ] || {
  echo "Limited role has a WAC column grant" >&2
  exit 1
}

forced_rls_tables="$(docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$db_name" \
  --tuples-only \
  --no-align \
  --command "
    SELECT count(*)
    FROM pg_class
    WHERE relname IN ('organizations', 'sales')
      AND relrowsecurity
      AND relforcerowsecurity;
  " | sed '/^$/d')"
[ "$forced_rls_tables" = "2" ] || {
  echo "Expected forced RLS on organizations and sales" >&2
  exit 1
}

echo "Security smoke test passed: RAM, director, exec, market-data, and WAC controls verified."
