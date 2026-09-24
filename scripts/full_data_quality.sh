#!/usr/bin/env sh
set -eu

db_user="${POSTGRES_USER:-pharma_admin}"
full_db="${FULL_POSTGRES_DB:-pharma_full}"

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --set ON_ERROR_STOP=1 \
  --command "
    DO \$quality\$
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
      IF (SELECT count(DISTINCT territory_name) FROM zip_territory) <> 15 THEN
        RAISE EXCEPTION 'expected 15 territories';
      END IF;
      IF (SELECT count(DISTINCT region_name) FROM zip_territory) <> 6 THEN
        RAISE EXCEPTION 'expected 6 regions';
      END IF;
      IF EXISTS (
        SELECT 1
        FROM sales AS s
        JOIN organizations AS o ON o.org_id = s.org_id
        WHERE o.org_status <> 'Active'
      ) THEN
        RAISE EXCEPTION 'sales include inactive organizations';
      END IF;
      IF EXISTS (
        SELECT 1 FROM sales
        WHERE data_source = 'hub_dispense' AND wac <> 0
      ) THEN
        RAISE EXCEPTION 'hub-dispense rows contain nonzero WAC';
      END IF;
    END
    \$quality\$;

    SELECT data_source, count(*) AS row_count
    FROM sales
    GROUP BY data_source
    ORDER BY data_source;

    SELECT
      min(transaction_date) AS min_transaction_date,
      max(transaction_date) AS max_transaction_date,
      min(mo_offset) AS min_month_offset,
      max(mo_offset) AS max_month_offset
    FROM sales;

    SELECT
      count(*) FILTER (WHERE brand_flag = 1) AS branded_market_rows,
      count(*) FILTER (WHERE brand_flag = 0) AS competitor_market_rows
    FROM sales
    WHERE data_source = 'market_data';
  "

echo "Full-data quality checks passed."
