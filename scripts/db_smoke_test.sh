#!/usr/bin/env sh
set -eu

compose_cmd="docker compose"
db_name="${POSTGRES_DB:-pharma}"
db_user="${POSTGRES_USER:-pharma_admin}"

$compose_cmd exec -T postgres psql \
  --username "$db_user" \
  --dbname "$db_name" \
  --set ON_ERROR_STOP=1 \
  --tuples-only \
  --command "
    SELECT 'organizations=' || count(*) FROM organizations;
    SELECT 'products=' || count(*) FROM products;
    SELECT 'sales=' || count(*) FROM sales;
    SELECT 'zip_territory=' || count(*) FROM zip_territory;
    SELECT 'users=' || count(*) FROM users;
  "

$compose_cmd exec -T postgres psql \
  --username "$db_user" \
  --dbname "$db_name" \
  --set ON_ERROR_STOP=1 \
  --tuples-only \
  --command "
    DO \$\$
    BEGIN
      IF (SELECT count(*) FROM products) <> 40 THEN
        RAISE EXCEPTION 'expected 40 fixture products';
      END IF;
      IF (SELECT count(*) FROM users) <> 23 THEN
        RAISE EXCEPTION 'expected 23 fixture users';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM sales) THEN
        RAISE EXCEPTION 'expected fixture sales';
      END IF;
    END
    \$\$;
  "

echo "Database smoke test passed."
