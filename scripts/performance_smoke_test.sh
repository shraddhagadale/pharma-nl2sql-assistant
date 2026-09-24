#!/usr/bin/env sh
set -eu

db_user="${POSTGRES_USER:-pharma_admin}"
full_db="${FULL_POSTGRES_DB:-pharma_full}"

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$full_db" \
  --set ON_ERROR_STOP=1 \
  --tuples-only \
  --command "
    BEGIN;
    SET LOCAL ROLE pharma_app_exec;
    SET LOCAL app.user_id = 'U001';
    SET LOCAL statement_timeout = '5s';
    SELECT round(COALESCE(sum(wac), 0), 2)
    FROM sales
    WHERE data_source = 'distributor'
      AND brand_flag = 1
      AND mo_offset IN (0, 1, 2);
    ROLLBACK;

    BEGIN;
    SET LOCAL ROLE pharma_app_limited;
    SET LOCAL app.user_id = 'U009';
    SET LOCAL statement_timeout = '5s';
    SELECT COALESCE(o.grandparent_org_name, o.org_name) AS account_name,
           round(sum(s.pack_units * p.unit_conversion_factor), 3) AS equivalents
    FROM sales AS s
    JOIN organizations AS o ON o.org_id = s.org_id
    JOIN products AS p ON p.ndc = s.ndc
    WHERE s.data_source = 'distributor'
      AND s.brand_flag = 1
      AND s.mo_offset IN (0, 1, 2)
    GROUP BY COALESCE(o.grandparent_org_name, o.org_name)
    ORDER BY equivalents DESC
    LIMIT 10;
    ROLLBACK;

    BEGIN;
    SET LOCAL ROLE pharma_app_limited;
    SET LOCAL app.user_id = 'U003';
    SET LOCAL statement_timeout = '5s';
    WITH nova AS (
      SELECT p.market_subcategory,
             sum(s.pack_units * p.unit_conversion_factor) AS equivalents
      FROM sales AS s
      JOIN products AS p ON p.ndc = s.ndc
      WHERE s.data_source = 'distributor'
        AND s.brand_flag = 1
        AND s.mo_offset IN (0, 1, 2)
      GROUP BY p.market_subcategory
    ), market AS (
      SELECT p.market_subcategory,
             sum(s.pack_units * p.unit_conversion_factor) AS equivalents
      FROM sales AS s
      JOIN products AS p ON p.ndc = s.ndc
      WHERE s.data_source = 'market_data'
        AND s.mo_offset IN (0, 1, 2)
      GROUP BY p.market_subcategory
    )
    SELECT n.market_subcategory,
           round(100 * n.equivalents / NULLIF(m.equivalents, 0), 2) AS share_percent
    FROM nova AS n
    JOIN market AS m USING (market_subcategory)
    ORDER BY n.market_subcategory;
    ROLLBACK;
  " >/dev/null

echo "Performance smoke test passed: representative full-data queries completed within 5 seconds each."
